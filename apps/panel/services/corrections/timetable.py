"""Мост CorrectObject ↔ ORM сущностей расписания для импорта."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from django.db import transaction

from apps.common.models import EventParticipant, EventPlace, Subject
from apps.common.services.timetable.load.resolution import (
    EntityType,
    ResolvedHit,
)
from apps.common.services.timetable.utilities.normalizers import (
    normalize_place_building_and_room,
)
from apps.panel.corrections.models import CorrectObject
from apps.panel.services.corrections.audit import stamp_update
from apps.panel.services.corrections.dictionaries import import_dictionary
from apps.panel.services.corrections.matching import get_or_create_scope
from apps.panel.services.corrections.pipeline import run_pipeline

logger = logging.getLogger(__name__)

ENTITY_TYPES: tuple[EntityType, ...] = ("teacher", "group", "subject", "place")

MODEL_LABEL_SUBJECT = "common.subject"
MODEL_LABEL_PARTICIPANT = "common.eventparticipant"
MODEL_LABEL_PLACE = "common.eventplace"


def external_id_for(model_label: str, pk: int) -> str:
    return f"{model_label}:{pk}"


def parse_external_id(external_id: str) -> tuple[str, int] | None:
    if not external_id or ":" not in external_id:
        return None
    label, _, raw_pk = external_id.rpartition(":")
    try:
        return label, int(raw_pk)
    except ValueError:
        return None


def place_canonical(building: str, room: str) -> str:
    return f"{building} {room}".strip()


def seed_dictionary_from_orm(
    *,
    entity_types: Iterable[EntityType] | None = None,
    pks: dict[EntityType, Iterable[int]] | None = None,
    actor: Any | None = None,
    scope_key: str = "global",
) -> dict[str, int]:
    """Upsert CorrectObject origin=imported из существующих ORM-записей."""
    types = tuple(entity_types) if entity_types is not None else ENTITY_TYPES
    totals = {"created": 0, "updated": 0, "aliases_linked": 0}

    for entity_type in types:
        items: list[dict[str, Any]] = []
        pk_filter = set(pks.get(entity_type, ())) if pks else None

        if entity_type == "subject":
            qs = Subject.objects.all()
            if pk_filter is not None:
                qs = qs.filter(pk__in=pk_filter)
            items.extend(
                {
                    "external_id": external_id_for(MODEL_LABEL_SUBJECT, obj.pk),
                    "canonical_value": obj.name,
                    "aliases": [obj.name],
                    "metadata": {"model": MODEL_LABEL_SUBJECT},
                }
                for obj in qs.iterator()
            )
        elif entity_type == "teacher":
            qs = EventParticipant.objects.filter(
                role=EventParticipant.Role.TEACHER, is_group=False
            )
            if pk_filter is not None:
                qs = qs.filter(pk__in=pk_filter)
            items.extend(
                {
                    "external_id": external_id_for(MODEL_LABEL_PARTICIPANT, obj.pk),
                    "canonical_value": obj.name,
                    "aliases": [obj.name],
                    "metadata": {"model": MODEL_LABEL_PARTICIPANT, "role": "teacher"},
                }
                for obj in qs.iterator()
            )
        elif entity_type == "group":
            qs = EventParticipant.objects.filter(
                role=EventParticipant.Role.STUDENT, is_group=True
            )
            if pk_filter is not None:
                qs = qs.filter(pk__in=pk_filter)
            items.extend(
                {
                    "external_id": external_id_for(MODEL_LABEL_PARTICIPANT, obj.pk),
                    "canonical_value": obj.name,
                    "aliases": [obj.name],
                    "metadata": {"model": MODEL_LABEL_PARTICIPANT, "role": "group"},
                }
                for obj in qs.iterator()
            )
        elif entity_type == "place":
            qs = EventPlace.objects.all()
            if pk_filter is not None:
                qs = qs.filter(pk__in=pk_filter)
            items.extend(
                {
                    "external_id": external_id_for(MODEL_LABEL_PLACE, obj.pk),
                    "canonical_value": place_canonical(obj.building, obj.room),
                    "aliases": [place_canonical(obj.building, obj.room)],
                    "metadata": {
                        "model": MODEL_LABEL_PLACE,
                        "building": obj.building,
                        "room": obj.room,
                    },
                }
                for obj in qs.iterator()
            )

        if not items:
            continue
        stats = import_dictionary(
            {"entity_type": entity_type, "scope_key": scope_key, "items": items},
            actor=actor,
            rematch_unlinked=False,
        )
        for key in totals:
            totals[key] += stats.get(key, 0)

    return totals


@transaction.atomic
def ensure_orm_for_object(
    correct_object: CorrectObject,
    *,
    actor: Any | None = None,
) -> ResolvedHit | None:
    """Создать ORM для clustered CorrectObject без external_id (однозначный случай)."""
    if correct_object.external_id:
        return hit_from_correct_object(correct_object, source="l2")

    entity_type = correct_object.entity_type
    if entity_type not in ENTITY_TYPES:
        return None

    # Не создаём ORM, если есть другие близкие объекты того же типа с external_id
    # (неоднозначность — зона L3).
    siblings = CorrectObject.objects.filter(
        scope_id=correct_object.scope_id,
        entity_type=entity_type,
    ).exclude(pk=correct_object.pk)
    if siblings.filter(external_id__gt="").exists() and siblings.count() > 0:
        # Есть конкуренты — только если текущий явно единственный кандидат политики.
        # Консервативно: при наличии других объектов с external_id не автосоздаём.
        competing = list(siblings.filter(external_id__gt="")[:5])
        if competing:
            logger.info(
                "ensure_orm_for_object skipped for #%s: competing external objects exist",
                correct_object.pk,
            )
            return None

    if entity_type == "subject":
        obj, _ = Subject.objects.get_or_create(name=correct_object.canonical_value)
        label = MODEL_LABEL_SUBJECT
        pk = obj.pk
        canonical = obj.name
    elif entity_type == "teacher":
        obj, _ = EventParticipant.objects.get_or_create(
            name=correct_object.canonical_value,
            role=EventParticipant.Role.TEACHER,
            is_group=False,
            defaults={},
        )
        label = MODEL_LABEL_PARTICIPANT
        pk = obj.pk
        canonical = obj.name
    elif entity_type == "group":
        obj, _ = EventParticipant.objects.get_or_create(
            name=correct_object.canonical_value,
            role=EventParticipant.Role.STUDENT,
            is_group=True,
            defaults={},
        )
        label = MODEL_LABEL_PARTICIPANT
        pk = obj.pk
        canonical = obj.name
    elif entity_type == "place":
        parsed = normalize_place_building_and_room(correct_object.canonical_value)
        if not parsed:
            return None
        building, room = parsed
        obj, _ = EventPlace.objects.get_or_create(building=building, room=room)
        label = MODEL_LABEL_PLACE
        pk = obj.pk
        canonical = place_canonical(obj.building, obj.room)
    else:
        return None

    correct_object.external_id = external_id_for(label, pk)
    stamp_update(correct_object, actor)
    correct_object.save(update_fields=["external_id", "updated_at", "updated_by"])
    return ResolvedHit(
        entity_type=entity_type,  # type: ignore[arg-type]
        canonical_value=canonical,
        model_label=label,
        pk=pk,
        source="l2",
    )


def hit_from_correct_object(
    correct_object: CorrectObject,
    *,
    source: str,
) -> ResolvedHit | None:
    parsed = parse_external_id(correct_object.external_id)
    if parsed is None:
        return None
    label, pk = parsed
    entity_type = correct_object.entity_type
    if entity_type not in ENTITY_TYPES:
        return None
    return ResolvedHit(
        entity_type=entity_type,  # type: ignore[arg-type]
        canonical_value=correct_object.canonical_value,
        model_label=label,
        pk=pk,
        source=source,  # type: ignore[arg-type]
    )


def _unique_linked_object(
    *,
    match,
    preferred_id: int | None = None,
) -> CorrectObject | None:
    """Выбрать единственный объект с external_id из match / preferred."""
    if preferred_id is not None:
        obj = CorrectObject.objects.filter(pk=preferred_id).first()
        if obj is not None and obj.external_id:
            return obj
        if obj is not None and not obj.external_id:
            return obj

    candidate_ids: list[int] = []
    if match.auto_linked_object_id:
        candidate_ids.append(match.auto_linked_object_id)
    for oid in match.linked_object_ids:
        if oid not in candidate_ids:
            candidate_ids.append(oid)

    if len(candidate_ids) == 1:
        return CorrectObject.objects.filter(pk=candidate_ids[0]).first()

    # Ровно один APPROVED среди candidates
    approved = [
        c
        for c in match.candidates
        if c.correct_object_id in match.linked_object_ids or c.source == "manual"
    ]
    if len(match.linked_object_ids) == 1:
        return CorrectObject.objects.filter(pk=match.linked_object_ids[0]).first()

    if len(match.candidates) == 1:
        return CorrectObject.objects.filter(pk=match.candidates[0].correct_object_id).first()

    _ = approved
    return None


class CorrectionsEntityResolver:
    """EntityResolver: L1→L2→L3 → ORM через external_id."""

    def __init__(self, *, scope_key: str = "global", actor: Any | None = None) -> None:
        self.scope_key = scope_key
        self.actor = actor
        get_or_create_scope(scope_key, actor=actor)

    def resolve(
        self,
        value: str,
        entity_type: EntityType,
        *,
        context: dict[str, Any] | None = None,
    ) -> ResolvedHit | None:
        text = (value or "").strip()
        if not text:
            return None

        match_value = text
        if entity_type == "place":
            # L1 на сырой строке, затем нормализация корпуса/аудитории для L2
            pipe_l1 = run_pipeline(
                text,
                entity_type=entity_type,
                scope_key=self.scope_key,
                layers=("l1",),
                context=context,
                actor=self.actor,
            )
            rewritten = pipe_l1.rewrite.output_text if pipe_l1.rewrite else text
            parsed = normalize_place_building_and_room(rewritten)
            match_value = place_canonical(*parsed) if parsed else rewritten
            result = run_pipeline(
                match_value,
                entity_type=entity_type,
                scope_key=self.scope_key,
                layers=("l2", "l3"),
                context=context,
                actor=self.actor,
            )
            # сохранить rewrite для отчёта (склеить)
            if pipe_l1.rewrite is not None:
                result = type(result)(
                    rewrite=pipe_l1.rewrite,
                    match=result.match,
                    resolution=result.resolution,
                )
        else:
            result = run_pipeline(
                match_value,
                entity_type=entity_type,
                scope_key=self.scope_key,
                layers=("l1", "l2", "l3"),
                context=context,
                actor=self.actor,
            )

        if result.match is None:
            return None

        preferred_id = None
        if result.resolution and result.resolution.selected_object_id:
            preferred_id = result.resolution.selected_object_id
            source = "l3"
        else:
            source = "l2"

        obj = _unique_linked_object(match=result.match, preferred_id=preferred_id)
        if obj is None:
            return None

        if not obj.external_id:
            # Однозначный clustered — создать ORM только если нет конкурентов
            if preferred_id is not None or (
                result.match.auto_linked_object_id == obj.pk
                or (
                    len(result.match.linked_object_ids) <= 1
                    and len(result.match.candidates) <= 1
                )
            ):
                return ensure_orm_for_object(obj, actor=self.actor)
            return None

        hit = hit_from_correct_object(obj, source=source)
        return hit


def rebind_abstract_event_entities(
    abstract_event,
    *,
    resolver: CorrectionsEntityResolver | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Preview/apply перепривязки subject/participants/places через L1–L2."""
    resolver = resolver or CorrectionsEntityResolver()
    preview: dict[str, Any] = {"changes": [], "unresolved": []}

    subject = abstract_event.subject
    if subject is not None:
        hit = resolver.resolve(subject.name, "subject")
        if hit and hit.pk != subject.pk:
            preview["changes"].append(
                {"field": "subject", "from": subject.name, "to": hit.canonical_value, "pk": hit.pk}
            )
            if apply:
                new_subject = Subject.objects.get(pk=hit.pk)
                abstract_event.subject = new_subject
        elif hit is None:
            preview["unresolved"].append({"field": "subject", "value": subject.name})

    for participant in list(abstract_event.participants.all()):
        et: EntityType = "group" if participant.is_group else "teacher"
        hit = resolver.resolve(participant.name, et)
        if hit and hit.pk != participant.pk:
            preview["changes"].append(
                {
                    "field": "participant",
                    "from": participant.name,
                    "to": hit.canonical_value,
                    "pk": hit.pk,
                }
            )
            if apply:
                new_p = EventParticipant.objects.get(pk=hit.pk)
                abstract_event.participants.remove(participant)
                abstract_event.participants.add(new_p)
        elif hit is None:
            preview["unresolved"].append({"field": "participant", "value": participant.name})

    for place in list(abstract_event.places.all()):
        raw = place_canonical(place.building, place.room)
        hit = resolver.resolve(raw, "place")
        if hit and hit.pk != place.pk:
            preview["changes"].append(
                {"field": "place", "from": raw, "to": hit.canonical_value, "pk": hit.pk}
            )
            if apply:
                new_place = EventPlace.objects.get(pk=hit.pk)
                abstract_event.places.remove(place)
                abstract_event.places.add(new_place)
        elif hit is None:
            preview["unresolved"].append({"field": "place", "value": raw})

    if apply and preview["changes"]:
        abstract_event.save()

    return preview

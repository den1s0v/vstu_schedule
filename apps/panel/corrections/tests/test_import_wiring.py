"""Тесты врезки L1/L2/L3 в импорт расписания."""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.common.models import EventParticipant, EventPlace, Subject, TimeSlot
from apps.common.services.timetable.load.event_importer import EventImporter
from apps.common.services.timetable.load.resolution import (
    ResolutionReport,
    ResolvedHit,
)
from apps.panel.corrections.models import CorrectObject, TextRewriteRule
from apps.panel.services.corrections.import_flags import resolve_import_flags
from apps.panel.services.corrections.links import forbid_link
from apps.panel.services.corrections.matching import get_or_create_scope, get_or_create_variant
from apps.panel.services.corrections.timetable import (
    CorrectionsEntityResolver,
    external_id_for,
    seed_dictionary_from_orm,
)


class _FixedResolver:
    def __init__(self, mapping: dict[tuple[str, str], ResolvedHit | None]) -> None:
        self.mapping = mapping

    def resolve(self, value, entity_type, *, context=None):
        return self.mapping.get((value, entity_type))


@pytest.mark.django_db
def test_event_importer_uses_resolver_hit():
    subject = Subject.objects.create(name="Математика")
    teacher = EventParticipant.objects.create(
        name="Иванов А.А.",
        role=EventParticipant.Role.TEACHER,
        is_group=False,
    )
    hit = ResolvedHit(
        entity_type="subject",
        canonical_value=subject.name,
        model_label="common.subject",
        pk=subject.pk,
        source="l2",
    )
    teacher_hit = ResolvedHit(
        entity_type="teacher",
        canonical_value=teacher.name,
        model_label="common.eventparticipant",
        pk=teacher.pk,
        source="l2",
    )
    resolver = _FixedResolver(
        {
            ("Матем.", "subject"): hit,
            ("Иванов И И", "teacher"): teacher_hit,
        }
    )
    report = ResolutionReport()
    entry = {
        "subject": "Матем.",
        "kind": "лекция",
        "participants": {"teachers": ["Иванов И И"], "student_groups": []},
        "places": [],
        "hours": [],
        "holds_on_date": [],
        "week": "first_week",
        "week_day_index": 0,
    }
    lookup = {
        "subjects": {},
        "kinds": {},
        "participants": {},
        "places": {},
        "time_slots": TimeSlot.objects.none(),
    }

    ok = EventImporter.apply_entity_resolution(
        entry,
        resolver=resolver,
        corrections_strict=False,
        report=report,
        reference_lookup=lookup,
    )
    assert ok is True
    assert entry["subject"] == "Математика"
    assert entry["participants"]["teachers"] == ["Иванов А.А."]
    assert lookup["subjects"][subject.name].pk == subject.pk
    assert report.resolved == 2


@pytest.mark.django_db
def test_strict_skips_unresolved():
    report = ResolutionReport()
    entry = {
        "subject": "Неизвестно",
        "kind": "лекция",
        "participants": {"teachers": [], "student_groups": []},
        "places": [],
    }
    lookup = {
        "subjects": {},
        "kinds": {},
        "participants": {},
        "places": {},
        "time_slots": TimeSlot.objects.none(),
    }
    ok = EventImporter.apply_entity_resolution(
        entry,
        resolver=_FixedResolver({}),
        corrections_strict=True,
        report=report,
        reference_lookup=lookup,
    )
    assert ok is False
    assert report.skipped == 1


@pytest.mark.django_db
def test_seed_dictionary_idempotent():
    subject = Subject.objects.create(name="Физика")
    stats1 = seed_dictionary_from_orm(entity_types=("subject",))
    stats2 = seed_dictionary_from_orm(entity_types=("subject",))
    assert stats1["created"] >= 1
    assert CorrectObject.objects.filter(
        entity_type="subject",
        external_id=external_id_for("common.subject", subject.pk),
    ).count() == 1
    assert stats2["created"] == 0
    assert stats2["updated"] >= 1


@pytest.mark.django_db
def test_corrections_resolver_l1_to_l2():
    teacher = EventParticipant.objects.create(
        name="Иванов А.А.",
        role=EventParticipant.Role.TEACHER,
        is_group=False,
    )
    seed_dictionary_from_orm(entity_types=("teacher",), pks={"teacher": [teacher.pk]})
    scope = get_or_create_scope("global")
    TextRewriteRule.objects.create(
        scope=scope,
        mode=TextRewriteRule.Mode.EXACT,
        search="Иванов И И",
        replacement="Иванов А.А.",
        priority=10,
        enabled=True,
    )
    resolver = CorrectionsEntityResolver()
    hit = resolver.resolve("Иванов И И", "teacher")
    assert hit is not None
    assert hit.pk == teacher.pk
    assert hit.canonical_value == "Иванов А.А."


@pytest.mark.django_db
def test_forbidden_blocks_autolink_and_strict_skips():
    t1 = EventParticipant.objects.create(
        name="Иванов А.А.",
        role=EventParticipant.Role.TEACHER,
        is_group=False,
    )
    t2 = EventParticipant.objects.create(
        name="Иванов А.Б.",
        role=EventParticipant.Role.TEACHER,
        is_group=False,
    )
    seed_dictionary_from_orm(entity_types=("teacher",), pks={"teacher": [t1.pk, t2.pk]})
    scope = get_or_create_scope("global")
    obj_ab = CorrectObject.objects.get(
        external_id=external_id_for("common.eventparticipant", t2.pk)
    )
    variant = get_or_create_variant(scope=scope, entity_type="teacher", value="Иванов А А")
    forbid_link(variant=variant, correct_object=obj_ab)

    resolver = CorrectionsEntityResolver()
    hit = resolver.resolve("Иванов А А", "teacher")
    # Может сматчиться на А.А. или остаться неоднозначным — FORBIDDEN на А.Б. не должен дать А.Б.
    if hit is not None:
        assert hit.pk != t2.pk

    report = ResolutionReport()
    hit2 = EventImporter._resolve_one(
        "Иванов А А",
        "teacher",
        resolver=_FixedResolver({}),
        corrections_strict=True,
        report=report,
        context={},
    )
    assert hit2 is False
    assert report.skipped == 1


@override_settings(IMPORT_USE_CORRECTIONS=True, IMPORT_CORRECTIONS_STRICT=False)
def test_resolve_import_flags_env_and_override():
    assert resolve_import_flags() == (True, False)
    assert resolve_import_flags(use_corrections=False) == (False, False)
    assert resolve_import_flags(use_corrections=True, corrections_strict=True) == (True, True)


@pytest.mark.django_db
def test_seed_place():
    place = EventPlace.objects.create(building="А", room="101")
    stats = seed_dictionary_from_orm(entity_types=("place",))
    assert stats["created"] >= 1
    obj = CorrectObject.objects.get(external_id=external_id_for("common.eventplace", place.pk))
    assert obj.canonical_value == "А 101"

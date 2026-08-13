"""Поиск кандидатов L2: точное и нечёткое сопоставление."""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from rapidfuzz.distance import JaroWinkler, Levenshtein

from apps.panel.corrections.models import (
    CorrectionScope,
    CorrectObject,
    EntityCreationPolicy,
    SpellingVariant,
    VariantObjectLink,
)
from apps.panel.services.corrections.audit import stamp_create, stamp_update
from apps.panel.services.corrections.dto import EntityCandidate, EntityMatchResult
from apps.panel.services.corrections.usage import record_usage

logger = logging.getLogger("apps.panel.services.corrections")

FUZZY_CANDIDATE_LIMIT = 50


def similarity(a: str, b: str) -> float:
    """Единая метрика L2: Jaro-Winkler [0..1]."""
    if a == b:
        return 1.0
    return float(JaroWinkler.normalized_similarity(a, b))


def tiebreak_similarity(a: str, b: str) -> float:
    """Тайбрейкер на шкале [0..1], не для порогов."""
    return float(Levenshtein.normalized_similarity(a, b))


def best_object_score(variant_value: str, obj: CorrectObject, known_spellings: list[str]) -> float:
    """Лучшая схожесть варианта с canonical и известными написаниями объекта."""
    texts = [obj.canonical_value, *known_spellings]
    return max((similarity(variant_value, t) for t in texts), default=0.0)


def get_or_create_scope(key: str = "global", *, actor: Any | None = None) -> CorrectionScope:
    scope, created = CorrectionScope.objects.get_or_create(
        key=key,
        defaults={"description": "Default correction scope"},
    )
    if created:
        stamp_create(scope, actor)  # CorrectionScope is not EditableModel — no-op fields
    return scope


def get_or_create_variant(
    *,
    scope: CorrectionScope,
    entity_type: str,
    value: str,
    actor: Any | None = None,
) -> SpellingVariant:
    variant, created = SpellingVariant.objects.get_or_create(
        scope=scope,
        entity_type=entity_type,
        value=value,
    )
    if created:
        stamp_create(variant, actor)
        variant.save(update_fields=["created_by", "updated_by"])
    return variant


def _forbidden_object_ids(variant: SpellingVariant) -> set[int]:
    return set(
        VariantObjectLink.objects.filter(
            variant=variant,
            status=VariantObjectLink.Status.FORBIDDEN,
        ).values_list("correct_object_id", flat=True)
    )


def _known_spellings_map(scope_id: int, entity_type: str) -> dict[int, list[str]]:
    links = (
        VariantObjectLink.objects.filter(
            variant__scope_id=scope_id,
            variant__entity_type=entity_type,
            status__in=[VariantObjectLink.Status.PENDING, VariantObjectLink.Status.APPROVED],
        )
        .select_related("variant")
        .values_list("correct_object_id", "variant__value")
    )
    result: dict[int, list[str]] = {}
    for object_id, value in links:
        result.setdefault(object_id, []).append(value)
    return result


def find_candidates(
    *,
    scope: CorrectionScope,
    entity_type: str,
    variant_value: str,
    suggest_threshold: float = 0.8,
    exclude_object_ids: set[int] | None = None,
) -> list[EntityCandidate]:
    """Найти кандидатов L2, исключая FORBIDDEN-пары."""
    exclude_object_ids = exclude_object_ids or set()
    objects = list(
        CorrectObject.objects.filter(scope=scope, entity_type=entity_type).exclude(
            id__in=exclude_object_ids
        )
    )
    if not objects:
        return []

    known = _known_spellings_map(scope.id, entity_type)
    scored: list[tuple[float, float, CorrectObject]] = []
    for obj in objects:
        # exact short-circuit
        spellings = known.get(obj.id, [])
        if variant_value == obj.canonical_value or variant_value in spellings:
            score = 1.0
            tie = 1.0
        else:
            score = best_object_score(variant_value, obj, spellings)
            if score < suggest_threshold:
                continue
            tie = max(
                (tiebreak_similarity(variant_value, t) for t in [obj.canonical_value, *spellings]),
                default=0.0,
            )
        scored.append((score, tie, obj))

    scored.sort(key=lambda item: (-item[0], -item[1], item[2].id))
    top = scored[:FUZZY_CANDIDATE_LIMIT]
    return [
        EntityCandidate(
            correct_object_id=obj.id,
            canonical_value=obj.canonical_value,
            score=score,
            origin=obj.origin,
            external_id=obj.external_id,
            source="exact" if score == 1.0 else "fuzzy",
        )
        for score, _tie, obj in top
    ]


@transaction.atomic
def match_variant(
    *,
    value: str,
    entity_type: str,
    scope_key: str = "global",
    actor: Any | None = None,
    record_stats: bool = True,
) -> EntityMatchResult:
    """
    Сопоставить вариант с объектами L2.

    Не выбирает единственного победителя при нескольких кандидатах.
    Auto-link только при единственном кандидате выше auto_link_threshold.
    """
    from apps.panel.services.corrections.policies import maybe_create_from_cluster

    scope = get_or_create_scope(scope_key, actor=actor)
    variant = get_or_create_variant(
        scope=scope, entity_type=entity_type, value=value, actor=actor
    )
    forbidden = _forbidden_object_ids(variant)

    policy = EntityCreationPolicy.objects.filter(
        scope=scope, entity_type=entity_type, enabled=True
    ).first()
    suggest_threshold = policy.suggest_threshold if policy else 0.8
    auto_link_threshold = policy.auto_link_threshold if policy else 0.95

    # Existing non-forbidden links
    existing_links = list(
        VariantObjectLink.objects.filter(variant=variant)
        .exclude(status=VariantObjectLink.Status.FORBIDDEN)
        .select_related("correct_object")
    )
    linked_ids = tuple(link.correct_object_id for link in existing_links)

    candidates = find_candidates(
        scope=scope,
        entity_type=entity_type,
        variant_value=value,
        suggest_threshold=suggest_threshold,
        exclude_object_ids=forbidden,
    )

    auto_linked_id: int | None = None
    created_id: int | None = None

    # Do not overwrite manual APPROVED links.
    has_manual_approved = any(
        link.status == VariantObjectLink.Status.APPROVED
        and link.source == VariantObjectLink.Source.MANUAL
        for link in existing_links
    )

    high = [c for c in candidates if c.score >= auto_link_threshold]
    if not has_manual_approved and len(high) == 1 and high[0].correct_object_id not in linked_ids:
        obj = CorrectObject.objects.get(pk=high[0].correct_object_id)
        link, created = VariantObjectLink.objects.get_or_create(
            variant=variant,
            correct_object=obj,
            defaults={
                "status": VariantObjectLink.Status.PENDING,
                "source": VariantObjectLink.Source.FUZZY,
                "score": high[0].score,
                "confirmation_count": 1,
            },
        )
        if created:
            stamp_create(link, actor)
            link.save(update_fields=["created_by", "updated_by"])
        elif link.status != VariantObjectLink.Status.FORBIDDEN:
            # strengthen but never revive forbidden / never demote manual approved
            if link.source != VariantObjectLink.Source.MANUAL:
                link.score = max(link.score, high[0].score)
                link.confirmation_count += 1
                stamp_update(link, actor)
                link.save(update_fields=["score", "confirmation_count", "updated_by", "updated_at"])
        auto_linked_id = obj.id
        linked_ids = tuple({*linked_ids, obj.id})
        if record_stats:
            record_usage(kind=CorrectionUsageKindObject, target_id=obj.id, input_text=value)

    elif not linked_ids and not high and not [c for c in candidates if c.score >= suggest_threshold]:
        created = maybe_create_from_cluster(
            scope=scope,
            entity_type=entity_type,
            seed_variant=variant,
            policy=policy,
            actor=actor,
        )
        if created is not None:
            created_id = created.id
            linked_ids = (created.id,)
            if record_stats:
                record_usage(kind=CorrectionUsageKindObject, target_id=created.id, input_text=value)

    elif record_stats:
        for object_id in linked_ids:
            record_usage(kind=CorrectionUsageKindObject, target_id=object_id, input_text=value)

    return EntityMatchResult(
        variant_value=value,
        entity_type=entity_type,
        candidates=tuple(candidates),
        linked_object_ids=linked_ids,
        created_object_id=created_id,
        auto_linked_object_id=auto_linked_id,
    )


# Avoid circular import of CorrectionUsage.Kind in hot path string
CorrectionUsageKindObject = "object"

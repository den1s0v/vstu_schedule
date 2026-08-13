"""Селекторы слоя корректировок."""

from __future__ import annotations

from django.db.models import Count, QuerySet, Sum

from apps.panel.corrections.models import (
    CorrectionUsage,
    CorrectObject,
    DisambiguationCase,
    SpellingVariant,
    TextRewriteRule,
    VariantObjectLink,
)


def active_rewrite_rules(scope_id: int) -> QuerySet[TextRewriteRule]:
    return TextRewriteRule.objects.filter(
        scope_id=scope_id, enabled=True
    ).order_by("priority", "id")


def rewrite_rules_for_scope(scope_id: int) -> QuerySet[TextRewriteRule]:
    return TextRewriteRule.objects.filter(scope_id=scope_id).order_by("priority", "id")


def correct_objects_for_type(scope_id: int, entity_type: str) -> QuerySet[CorrectObject]:
    return CorrectObject.objects.filter(
        scope_id=scope_id, entity_type=entity_type
    ).order_by("canonical_value", "id")


def variants_for_type(scope_id: int, entity_type: str) -> QuerySet[SpellingVariant]:
    return SpellingVariant.objects.filter(
        scope_id=scope_id, entity_type=entity_type
    ).prefetch_related("object_links__correct_object")


def open_disambiguation_cases(scope_id: int | None = None) -> QuerySet[DisambiguationCase]:
    qs = DisambiguationCase.objects.filter(
        status=DisambiguationCase.Status.OPEN
    ).select_related("variant", "selected_object", "scope").prefetch_related(
        "candidates__correct_object"
    )
    if scope_id is not None:
        qs = qs.filter(scope_id=scope_id)
    return qs.order_by("-updated_at")


def forbidden_links(scope_id: int) -> QuerySet[VariantObjectLink]:
    return VariantObjectLink.objects.filter(
        status=VariantObjectLink.Status.FORBIDDEN,
        variant__scope_id=scope_id,
    ).select_related("variant", "correct_object")


def usage_map(kind: str, target_ids: list[int]) -> dict[int, tuple[int, int]]:
    """target_id -> (total, unique)."""
    if not target_ids:
        return {}
    rows = (
        CorrectionUsage.objects.filter(kind=kind, target_id__in=target_ids)
        .values("target_id")
        .annotate(total=Sum("count"), unique=Count("id"))
    )
    return {
        int(row["target_id"]): (int(row["total"] or 0), int(row["unique"] or 0))
        for row in rows
    }

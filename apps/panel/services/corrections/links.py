"""Ручные команды L2: связать / запретить / снять связь."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.panel.corrections.models import CorrectObject, SpellingVariant, VariantObjectLink
from apps.panel.services.corrections.audit import stamp_create, stamp_update


@transaction.atomic
def approve_link(
    *,
    variant: SpellingVariant,
    correct_object: CorrectObject,
    actor: Any | None = None,
    score: float = 1.0,
) -> VariantObjectLink:
    """Явно связать любую пару; снимает FORBIDDEN."""
    if variant.scope_id != correct_object.scope_id:
        raise ValidationError("Вариант и объект должны быть в одной области.")
    if variant.entity_type != correct_object.entity_type:
        raise ValidationError("Вариант и объект должны иметь один entity_type.")

    link, created = VariantObjectLink.objects.get_or_create(
        variant=variant,
        correct_object=correct_object,
        defaults={
            "status": VariantObjectLink.Status.APPROVED,
            "source": VariantObjectLink.Source.MANUAL,
            "score": score,
            "confirmation_count": 1,
        },
    )
    if created:
        stamp_create(link, actor)
        link.save(update_fields=["created_by", "updated_by"])
        return link

    link.status = VariantObjectLink.Status.APPROVED
    link.source = VariantObjectLink.Source.MANUAL
    link.score = max(link.score, score)
    stamp_update(link, actor)
    link.save(
        update_fields=["status", "source", "score", "updated_by", "updated_at"]
    )
    return link


@transaction.atomic
def forbid_link(
    *,
    variant: SpellingVariant,
    correct_object: CorrectObject,
    actor: Any | None = None,
) -> VariantObjectLink:
    """Явно запретить конкретную пару."""
    link, created = VariantObjectLink.objects.get_or_create(
        variant=variant,
        correct_object=correct_object,
        defaults={
            "status": VariantObjectLink.Status.FORBIDDEN,
            "source": VariantObjectLink.Source.MANUAL,
            "score": 0.0,
            "confirmation_count": 0,
        },
    )
    if created:
        stamp_create(link, actor)
        link.save(update_fields=["created_by", "updated_by"])
        return link

    link.status = VariantObjectLink.Status.FORBIDDEN
    link.source = VariantObjectLink.Source.MANUAL
    stamp_update(link, actor)
    link.save(update_fields=["status", "source", "updated_by", "updated_at"])
    return link


@transaction.atomic
def remove_link(*, link: VariantObjectLink) -> None:
    """Полностью удалить связь (снимает и запрет)."""
    link.delete()

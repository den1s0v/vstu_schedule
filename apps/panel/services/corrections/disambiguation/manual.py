"""Ручное создание и разрешение кейсов L3."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.db import transaction

from apps.panel.corrections.models import (
    CorrectObject,
    DisambiguationCandidate,
    DisambiguationCase,
    SpellingVariant,
)
from apps.panel.services.corrections.audit import stamp_create, stamp_update
from apps.panel.services.corrections.disambiguation import get_resolver
from apps.panel.services.corrections.dto import EntityCandidate, ResolutionContext, ResolutionResult
from apps.panel.services.corrections.links import approve_link
from apps.panel.services.corrections.matching import get_or_create_scope


def context_fingerprint(context: dict[str, Any]) -> str:
    payload = json.dumps(context, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@transaction.atomic
def open_case(
    *,
    variant: SpellingVariant,
    candidates: list[EntityCandidate],
    context: dict[str, Any] | None = None,
    actor: Any | None = None,
) -> DisambiguationCase:
    """Создать/обновить кейс неоднозначности с кандидатами."""
    context = context or {}
    fp = context_fingerprint(context)
    scope = variant.scope
    case, created = DisambiguationCase.objects.get_or_create(
        scope=scope,
        variant=variant,
        fingerprint=fp,
        defaults={
            "entity_type": variant.entity_type,
            "context": context,
            "status": DisambiguationCase.Status.OPEN,
        },
    )
    if created:
        stamp_create(case, actor)
        case.save(update_fields=["created_by", "updated_by"])
    else:
        case.context = context
        case.status = DisambiguationCase.Status.OPEN
        case.selected_object = None
        stamp_update(case, actor)
        case.save(
            update_fields=[
                "context",
                "status",
                "selected_object",
                "updated_by",
                "updated_at",
            ]
        )
        case.candidates.all().delete()

    for cand in candidates:
        obj = CorrectObject.objects.get(pk=cand.correct_object_id)
        row = DisambiguationCandidate(
            case=case,
            correct_object=obj,
            score=cand.score,
            evidence={"source": cand.source, "origin": cand.origin},
            source=cand.source,
        )
        stamp_create(row, actor)
        row.save()

    return case


@transaction.atomic
def resolve_case_manually(
    *,
    case: DisambiguationCase,
    correct_object: CorrectObject | None,
    actor: Any | None = None,
) -> DisambiguationCase:
    """Ручной выбор объекта или сброс решения."""
    if correct_object is None:
        case.selected_object = None
        case.status = DisambiguationCase.Status.UNRESOLVED
    else:
        case.selected_object = correct_object
        case.status = DisambiguationCase.Status.RESOLVED
        approve_link(variant=case.variant, correct_object=correct_object, actor=actor)
    stamp_update(case, actor)
    case.save(
        update_fields=["selected_object", "status", "updated_by", "updated_at"]
    )
    return case


def try_strategy(
    *,
    candidates: list[EntityCandidate],
    context: ResolutionContext,
    strategy_name: str = "passthrough",
) -> ResolutionResult:
    """Вызвать зарегистрированную стратегию без побочных эффектов в БД."""
    resolver = get_resolver(strategy_name)
    if resolver is None:
        return ResolutionResult(
            selected_object_id=None,
            status="unresolved",
            evidence={"error": f"unknown strategy: {strategy_name}"},
            strategy=strategy_name,
        )
    return resolver.resolve(candidates, context)


# silence unused import warning for get_or_create_scope in public API surface
_ = get_or_create_scope

"""Опциональный оркестратор L1→L2→L3."""

from __future__ import annotations

from typing import Any, Literal

from apps.panel.corrections.models import TextRewriteRule
from apps.panel.services.corrections.disambiguation.manual import open_case, try_strategy
from apps.panel.services.corrections.dto import (
    PipelineResult,
    ResolutionContext,
    RewriteRuleDTO,
)
from apps.panel.services.corrections.matching import get_or_create_scope, match_variant
from apps.panel.services.corrections.rewrite import apply_rewrite
from apps.panel.services.corrections.usage import record_usage

LayerName = Literal["l1", "l2", "l3"]


def _rules_to_dto(scope_key: str) -> list[RewriteRuleDTO]:
    scope = get_or_create_scope(scope_key)
    rules = TextRewriteRule.objects.filter(scope=scope, enabled=True).order_by("priority", "id")
    return [
        RewriteRuleDTO(
            id=rule.id,
            mode=rule.mode,
            search=rule.search,
            replacement=rule.replacement,
            preprocess=tuple(rule.preprocess or []),
            priority=rule.priority,
            enabled=rule.enabled,
        )
        for rule in rules
    ]


def run_pipeline(
    text: str,
    *,
    entity_type: str,
    scope_key: str = "global",
    layers: tuple[LayerName, ...] = ("l1", "l2", "l3"),
    context: dict[str, Any] | None = None,
    actor: Any | None = None,
    l3_strategy: str = "passthrough",
) -> PipelineResult:
    """Запустить выбранные слои; неоднозначность L2 не скрывается."""
    rewrite = None
    match = None
    resolution = None
    current = text

    if "l1" in layers:
        rules = _rules_to_dto(scope_key)
        rewrite = apply_rewrite(current, rules)
        current = rewrite.output_text
        for rule_id in rewrite.applied_rule_ids:
            record_usage(kind="rule", target_id=rule_id, input_text=text)

    if "l2" in layers:
        match = match_variant(
            value=current,
            entity_type=entity_type,
            scope_key=scope_key,
            actor=actor,
        )

    if "l3" in layers and match is not None and len(match.candidates) > 1:
        from apps.panel.corrections.models import SpellingVariant

        variant = SpellingVariant.objects.get(
            scope__key=scope_key,
            entity_type=entity_type,
            value=match.variant_value,
        )
        case = open_case(
            variant=variant,
            candidates=list(match.candidates),
            context=context or {},
            actor=actor,
        )
        resolution = try_strategy(
            candidates=list(match.candidates),
            context=ResolutionContext(
                entities=(context or {}).get("entities", {}),
                relations=(context or {}).get("relations", []),
                features=(context or {}).get("features", {}),
                fingerprint=case.fingerprint,
            ),
            strategy_name=l3_strategy,
        )

    return PipelineResult(rewrite=rewrite, match=match, resolution=resolution)

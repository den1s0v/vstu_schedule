"""Django-free применение правил L1."""

from __future__ import annotations

import re

from apps.panel.services.corrections.dto import RewriteResult, RewriteRuleDTO, RewriteStep
from apps.panel.services.corrections.transformers import apply_transformer, decode_re_spaces


def _apply_preprocess(text: str, preprocess: tuple[str, ...]) -> tuple[str, list[RewriteStep]]:
    steps: list[RewriteStep] = []
    current = text
    for transformer_id in preprocess:
        before = current
        current = apply_transformer(transformer_id, current)
        if current != before:
            steps.append(
                RewriteStep(
                    kind="preprocess",
                    detail=transformer_id,
                    before=before,
                    after=current,
                )
            )
    # default strip + shrink like vstuxls pattern matching
    before = current
    current = current.strip()
    current = apply_transformer("shrink_extra_inner_spaces", current)
    if current != before:
        steps.append(
            RewriteStep(
                kind="preprocess",
                detail="strip+shrink_extra_inner_spaces",
                before=before,
                after=current,
            )
        )
    return current, steps


def _apply_one_rule(text: str, rule: RewriteRuleDTO) -> tuple[str, bool]:
    if rule.mode == "exact":
        if text == rule.search:
            return rule.replacement, True
        return text, False

    if rule.mode == "substring":
        if rule.search and rule.search in text:
            return text.replace(rule.search, rule.replacement), True
        return text, False

    if rule.mode == "re_spaces":
        pattern = decode_re_spaces(rule.search)
        compiled = re.compile(pattern)
        new_text, count = compiled.subn(rule.replacement, text, count=1)
        return new_text, count > 0

    raise ValueError(f"Неизвестный режим правила: {rule.mode}")


def apply_rewrite(text: str, rules: list[RewriteRuleDTO] | tuple[RewriteRuleDTO, ...]) -> RewriteResult:
    """
    Применить правила L1 в порядке priority, id.

    Без ORM и без семантических дополнений.
    """
    ordered = sorted(
        (r for r in rules if r.enabled),
        key=lambda r: (r.priority, r.id if r.id is not None else 10**9),
    )
    steps: list[RewriteStep] = []
    applied: list[int] = []
    current = text

    for rule in ordered:
        working, preprocess_steps = _apply_preprocess(current, rule.preprocess)
        steps.extend(preprocess_steps)
        # Match against preprocessed view, but rewrite the working string only when matched.
        # For EXACT/SUBSTRING we apply on preprocessed string result as the new current text.
        after, matched = _apply_one_rule(working, rule)
        if matched:
            steps.append(
                RewriteStep(
                    kind="rule",
                    detail=f"{rule.mode}:{rule.search!r}->{rule.replacement!r}",
                    before=current,
                    after=after,
                    rule_id=rule.id,
                )
            )
            current = after
            if rule.id is not None:
                applied.append(rule.id)

    return RewriteResult(
        input_text=text,
        output_text=current,
        steps=tuple(steps),
        applied_rule_ids=tuple(applied),
    )

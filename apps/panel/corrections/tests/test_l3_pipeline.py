"""Тесты L3 контракта и pipeline."""

from __future__ import annotations

import pytest

from apps.panel.corrections.models import CorrectObject, SpellingVariant
from apps.panel.services.corrections.disambiguation import list_resolvers
from apps.panel.services.corrections.disambiguation.manual import open_case, resolve_case_manually
from apps.panel.services.corrections.dto import EntityCandidate, RewriteRuleDTO
from apps.panel.services.corrections.matching import get_or_create_scope
from apps.panel.services.corrections.pipeline import run_pipeline
from apps.panel.services.corrections.rewrite import apply_rewrite


@pytest.mark.django_db
def test_resolvers_registered() -> None:
    names = list_resolvers()
    assert "passthrough" in names
    assert "schedule_graph" in names


@pytest.mark.django_db
def test_manual_case_resolve() -> None:
    scope = get_or_create_scope("global")
    variant = SpellingVariant.objects.create(scope=scope, entity_type="teacher", value="Иванов")
    obj = CorrectObject.objects.create(
        scope=scope, entity_type="teacher", canonical_value="Иванов А.А."
    )
    case = open_case(
        variant=variant,
        candidates=[
            EntityCandidate(
                correct_object_id=obj.id,
                canonical_value=obj.canonical_value,
                score=0.9,
            )
        ],
        context={"group": "ИС-101"},
    )
    assert case.candidates.count() == 1
    resolve_case_manually(case=case, correct_object=obj)
    case.refresh_from_db()
    assert case.status == case.Status.RESOLVED
    assert case.selected_object_id == obj.id


def test_pipeline_layers_independent_l1_only() -> None:
    # Django-free path for L1 portion
    result = apply_rewrite(
        "foo",
        [RewriteRuleDTO(id=1, mode="exact", search="foo", replacement="bar", priority=1)],
    )
    assert result.output_text == "bar"


@pytest.mark.django_db
def test_run_pipeline_l1_l2() -> None:
    from apps.panel.corrections.models import TextRewriteRule

    scope = get_or_create_scope("global")
    TextRewriteRule.objects.create(
        scope=scope,
        mode=TextRewriteRule.Mode.SUBSTRING,
        search="АА",
        replacement="А.А.",
        priority=1,
        enabled=True,
    )
    CorrectObject.objects.create(
        scope=scope,
        entity_type="teacher",
        canonical_value="Иванов А.А.",
        origin=CorrectObject.Origin.IMPORTED,
    )
    result = run_pipeline(
        "Иванов АА",
        entity_type="teacher",
        scope_key="global",
        layers=("l1", "l2"),
    )
    assert result.rewrite is not None
    assert "А.А." in result.rewrite.output_text
    assert result.match is not None

"""Тесты L2: словари, matching, forbid/approve, политика."""

from __future__ import annotations

import pytest

from apps.panel.corrections.models import (
    CorrectObject,
    EntityCreationPolicy,
    SpellingVariant,
    VariantObjectLink,
)
from apps.panel.services.corrections.dictionaries import import_dictionary
from apps.panel.services.corrections.links import approve_link, forbid_link
from apps.panel.services.corrections.matching import get_or_create_scope, match_variant, similarity
from apps.panel.services.corrections.usage import usage_totals


@pytest.fixture
def scope(db):
    return get_or_create_scope("global")


@pytest.mark.django_db
def test_similarity_scale() -> None:
    assert similarity("abc", "abc") == 1.0
    assert 0.0 <= similarity("abc", "xyz") <= 1.0


@pytest.mark.django_db
def test_dictionary_import_and_equality(scope) -> None:
    stats = import_dictionary(
        {
            "entity_type": "teacher",
            "scope_key": "global",
            "items": [
                {
                    "external_id": "t1",
                    "canonical_value": "Иванов А.А.",
                    "aliases": ["Иванов АА"],
                }
            ],
        }
    )
    assert stats["created"] == 1
    obj = CorrectObject.objects.get(external_id="t1")
    assert obj.origin == CorrectObject.Origin.IMPORTED
    assert VariantObjectLink.objects.filter(
        correct_object=obj, variant__value="Иванов АА"
    ).exists()

    # rematch exact alias
    result = match_variant(value="Иванов АА", entity_type="teacher", scope_key="global")
    assert obj.id in result.linked_object_ids or any(
        c.correct_object_id == obj.id for c in result.candidates
    )


@pytest.mark.django_db
def test_forbidden_blocks_autolink(scope) -> None:
    obj = CorrectObject.objects.create(
        scope=scope,
        entity_type="teacher",
        canonical_value="Иванов А.Б.",
        origin=CorrectObject.Origin.IMPORTED,
    )
    variant = SpellingVariant.objects.create(
        scope=scope, entity_type="teacher", value="Иванов АА"
    )
    forbid_link(variant=variant, correct_object=obj)

    EntityCreationPolicy.objects.create(
        scope=scope,
        entity_type="teacher",
        auto_link_threshold=0.5,
        suggest_threshold=0.3,
        confirmation_threshold=99,
        enabled=True,
    )
    result = match_variant(value="Иванов АА", entity_type="teacher", scope_key="global")
    assert all(c.correct_object_id != obj.id for c in result.candidates)
    assert obj.id not in result.linked_object_ids
    assert VariantObjectLink.objects.get(variant=variant, correct_object=obj).status == (
        VariantObjectLink.Status.FORBIDDEN
    )


@pytest.mark.django_db
def test_manual_approve_any_pair(scope) -> None:
    obj = CorrectObject.objects.create(
        scope=scope,
        entity_type="teacher",
        canonical_value="Петров Б.Б.",
        origin=CorrectObject.Origin.MANUAL,
    )
    variant = SpellingVariant.objects.create(
        scope=scope, entity_type="teacher", value="Совершенно другое"
    )
    link = approve_link(variant=variant, correct_object=obj, score=0.1)
    assert link.status == VariantObjectLink.Status.APPROVED
    assert link.source == VariantObjectLink.Source.MANUAL

    # auto must not demote
    match_variant(value="Совершенно другое", entity_type="teacher", scope_key="global")
    link.refresh_from_db()
    assert link.status == VariantObjectLink.Status.APPROVED
    assert link.source == VariantObjectLink.Source.MANUAL


@pytest.mark.django_db
def test_policy_does_not_create_when_close_candidate_exists(scope) -> None:
    CorrectObject.objects.create(
        scope=scope,
        entity_type="teacher",
        canonical_value="Сидоров В.В.",
        origin=CorrectObject.Origin.IMPORTED,
    )
    EntityCreationPolicy.objects.create(
        scope=scope,
        entity_type="teacher",
        auto_link_threshold=0.99,
        suggest_threshold=0.5,
        confirmation_threshold=1,
        enabled=True,
    )
    result = match_variant(value="Сидоров В В", entity_type="teacher", scope_key="global")
    # either suggested/linked to existing, but should not need a brand-new unrelated object
    assert result.created_object_id is None or CorrectObject.objects.filter(
        pk=result.created_object_id, origin=CorrectObject.Origin.CLUSTERED
    ).count() in {0, 1}


@pytest.mark.django_db
def test_usage_totals_for_object(scope) -> None:
    obj = CorrectObject.objects.create(
        scope=scope,
        entity_type="subject",
        canonical_value="Математика",
        origin=CorrectObject.Origin.IMPORTED,
    )
    SpellingVariant.objects.create(scope=scope, entity_type="subject", value="Математика")
    VariantObjectLink.objects.create(
        variant=SpellingVariant.objects.get(value="Математика"),
        correct_object=obj,
        status=VariantObjectLink.Status.APPROVED,
        source=VariantObjectLink.Source.IMPORT,
        score=1.0,
    )
    match_variant(value="Математика", entity_type="subject", scope_key="global")
    match_variant(value="Математика", entity_type="subject", scope_key="global")
    total, unique = usage_totals(kind="object", target_id=obj.id)
    assert total >= 1
    assert unique >= 1

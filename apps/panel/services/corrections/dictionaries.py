"""Импорт эталонных словарей в CorrectObject."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.panel.corrections.models import CorrectObject, VariantObjectLink
from apps.panel.services.corrections.audit import stamp_create, stamp_update
from apps.panel.services.corrections.matching import (
    get_or_create_scope,
    get_or_create_variant,
    match_variant,
)

DICTIONARY_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["entity_type", "items"],
    "additionalProperties": False,
    "properties": {
        "entity_type": {"type": "string", "minLength": 1},
        "scope_key": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["canonical_value"],
                "additionalProperties": False,
                "properties": {
                    "external_id": {"type": "string"},
                    "canonical_value": {"type": "string", "minLength": 1},
                    "aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "metadata": {"type": "object"},
                },
            },
        },
    },
}


def validate_dictionary_payload(payload: dict[str, Any]) -> None:
    """Лёгкая валидация по схеме без внешней jsonschema-зависимости."""
    if not isinstance(payload, dict):
        raise ValidationError("Корень словаря должен быть объектом.")
    if "entity_type" not in payload or not isinstance(payload["entity_type"], str):
        raise ValidationError("Требуется строковое поле entity_type.")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValidationError("Требуется массив items.")
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValidationError(f"items[{idx}] должен быть объектом.")
        if "canonical_value" not in item or not isinstance(item["canonical_value"], str):
            raise ValidationError(f"items[{idx}].canonical_value обязателен.")
        if "aliases" in item and not isinstance(item["aliases"], list):
            raise ValidationError(f"items[{idx}].aliases должен быть массивом.")
        if "metadata" in item and not isinstance(item["metadata"], dict):
            raise ValidationError(f"items[{idx}].metadata должен быть объектом.")


def load_dictionary_file(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_dictionary_payload(data)
    return data


@transaction.atomic
def import_dictionary(
    payload: dict[str, Any],
    *,
    actor: Any | None = None,
    rematch_unlinked: bool = True,
) -> dict[str, int]:
    """
    Upsert CorrectObject и aliases.

    Ключ: (scope, entity_type, external_id) или canonical_value при пустом external_id.
    """
    validate_dictionary_payload(payload)
    entity_type = payload["entity_type"]
    scope_key = payload.get("scope_key") or "global"
    scope = get_or_create_scope(scope_key, actor=actor)

    created = 0
    updated = 0
    aliases_linked = 0

    for item in payload["items"]:
        external_id = item.get("external_id") or ""
        canonical_value = item["canonical_value"]
        metadata = item.get("metadata") or {}

        obj: CorrectObject | None = None
        if external_id:
            obj = CorrectObject.objects.filter(
                scope=scope, entity_type=entity_type, external_id=external_id
            ).first()
        else:
            obj = CorrectObject.objects.filter(
                scope=scope,
                entity_type=entity_type,
                external_id="",
                canonical_value=canonical_value,
            ).first()

        if obj is None:
            obj = CorrectObject(
                scope=scope,
                entity_type=entity_type,
                external_id=external_id,
                canonical_value=canonical_value,
                origin=CorrectObject.Origin.IMPORTED,
                metadata=metadata,
            )
            stamp_create(obj, actor)
            obj.save()
            created += 1
        else:
            obj.canonical_value = canonical_value
            obj.metadata = metadata
            if obj.origin != CorrectObject.Origin.IMPORTED:
                obj.origin = CorrectObject.Origin.IMPORTED
            stamp_update(obj, actor)
            obj.save()
            updated += 1

        # canonical as approved alias
        variant = get_or_create_variant(
            scope=scope,
            entity_type=entity_type,
            value=canonical_value,
            actor=actor,
        )
        link, link_created = VariantObjectLink.objects.get_or_create(
            variant=variant,
            correct_object=obj,
            defaults={
                "status": VariantObjectLink.Status.APPROVED,
                "source": VariantObjectLink.Source.IMPORT,
                "score": 1.0,
                "confirmation_count": 1,
            },
        )
        if link_created:
            stamp_create(link, actor)
            link.save(update_fields=["created_by", "updated_by"])
            aliases_linked += 1
        elif link.status != VariantObjectLink.Status.FORBIDDEN:
            if link.status != VariantObjectLink.Status.APPROVED:
                link.status = VariantObjectLink.Status.APPROVED
                link.source = VariantObjectLink.Source.IMPORT
                link.score = 1.0
                stamp_update(link, actor)
                link.save(
                    update_fields=["status", "source", "score", "updated_by", "updated_at"]
                )

        for alias in item.get("aliases") or []:
            if not isinstance(alias, str) or not alias or alias == canonical_value:
                continue
            alias_variant = get_or_create_variant(
                scope=scope, entity_type=entity_type, value=alias, actor=actor
            )
            forbidden = VariantObjectLink.objects.filter(
                variant=alias_variant,
                correct_object=obj,
                status=VariantObjectLink.Status.FORBIDDEN,
            ).exists()
            if forbidden:
                continue
            a_link, a_created = VariantObjectLink.objects.get_or_create(
                variant=alias_variant,
                correct_object=obj,
                defaults={
                    "status": VariantObjectLink.Status.APPROVED,
                    "source": VariantObjectLink.Source.IMPORT,
                    "score": 1.0,
                    "confirmation_count": 1,
                },
            )
            if a_created:
                stamp_create(a_link, actor)
                a_link.save(update_fields=["created_by", "updated_by"])
                aliases_linked += 1

    rematched = 0
    if rematch_unlinked:
        from apps.panel.corrections.models import SpellingVariant

        unlinked = SpellingVariant.objects.filter(
            scope=scope, entity_type=entity_type
        ).exclude(
            object_links__status__in=[
                VariantObjectLink.Status.PENDING,
                VariantObjectLink.Status.APPROVED,
            ]
        )
        for variant in unlinked.iterator():
            match_variant(
                value=variant.value,
                entity_type=entity_type,
                scope_key=scope.key,
                actor=actor,
                record_stats=False,
            )
            rematched += 1

    return {
        "created": created,
        "updated": updated,
        "aliases_linked": aliases_linked,
        "rematched": rematched,
    }

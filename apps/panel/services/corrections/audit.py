"""Общие helpers для audit-полей EditableModel."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.utils import timezone


def stamp_create(instance: Any, actor: Any | None) -> None:
    """Установить created_by/updated_by при создании."""
    if hasattr(instance, "created_by_id") and instance.created_by_id is None:
        instance.created_by = actor
    if hasattr(instance, "updated_by_id"):
        instance.updated_by = actor


def stamp_update(instance: Any, actor: Any | None) -> None:
    """Установить updated_by при изменении."""
    if hasattr(instance, "updated_by_id"):
        instance.updated_by = actor


def bulk_stamp_update(queryset: QuerySet[Any], actor: Any | None, **fields: Any) -> int:
    """QuerySet.update с явным updated_at/updated_by (auto_now не срабатывает)."""
    payload = dict(fields)
    payload["updated_at"] = timezone.now()
    if actor is not None and "updated_by" not in payload and "updated_by_id" not in payload:
        payload["updated_by"] = actor
    return queryset.update(**payload)

"""Агрегированные счётчики total/unique usage."""

from __future__ import annotations

import hashlib

from django.db.models import F, Sum

from apps.panel.corrections.models import CorrectionUsage


def fingerprint_text(text: str) -> str:
    """Стабильный отпечаток входа без хранения сырого текста."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_usage(*, kind: str, target_id: int, input_text: str) -> CorrectionUsage:
    """Увеличить total для (kind, target, fingerprint)."""
    fp = fingerprint_text(input_text)
    usage, created = CorrectionUsage.objects.get_or_create(
        kind=kind,
        target_id=target_id,
        input_fingerprint=fp,
        defaults={"count": 1},
    )
    if not created:
        CorrectionUsage.objects.filter(pk=usage.pk).update(count=F("count") + 1)
        usage.refresh_from_db(fields=["count", "updated_at"])
    return usage


def usage_totals(*, kind: str, target_id: int) -> tuple[int, int]:
    """Вернуть (total, unique) для сущности."""
    qs = CorrectionUsage.objects.filter(kind=kind, target_id=target_id)
    unique = qs.count()
    total = qs.aggregate(s=Sum("count"))["s"] or 0
    return int(total), int(unique)

"""Агрегированная статистика применений правил и объектов."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import models
from django.db.models import UniqueConstraint


class CorrectionUsage(models.Model):
    """Счётчик применений на уровне правила L1 или CorrectObject L2."""

    class Kind(models.TextChoices):
        RULE = "rule", "Правило L1"
        OBJECT = "object", "Корректный объект L2"

    kind = models.CharField(max_length=16, choices=Kind.choices, verbose_name="Вид")
    target_id = models.PositiveBigIntegerField(verbose_name="ID сущности")
    input_fingerprint = models.CharField(max_length=64, verbose_name="Отпечаток входа")
    count = models.PositiveIntegerField(default=1, verbose_name="Число применений")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")

    if TYPE_CHECKING:
        id: int
        pk: int

    class Meta:
        app_label = "panel"
        db_table = "panel_correction_usage"
        verbose_name = "Использование корректировки"
        verbose_name_plural = "Использования корректировок"
        constraints: ClassVar = [
            UniqueConstraint(
                fields=["kind", "target_id", "input_fingerprint"],
                name="panel_cusage_kind_target_fp_uniq",
            ),
        ]
        indexes: ClassVar = [
            models.Index(fields=["kind", "target_id"], name="panel_cusage_kind_target_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.target_id} {self.input_fingerprint[:8]}…×{self.count}"

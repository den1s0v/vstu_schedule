"""Модели слоя L1: правила перезаписи строк."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.panel.corrections.models.base import CorrectionScope, EditableModel


class TextRewriteRule(EditableModel):
    """Детерминированное правило перезаписи текста без контекста."""

    class Mode(models.TextChoices):
        EXACT = "exact", "Точное совпадение всей строки"
        SUBSTRING = "substring", "Подстрока"
        RE_SPACES = "re_spaces", "Regex с упрощёнными пробелами"

    scope = models.ForeignKey(
        CorrectionScope,
        on_delete=models.CASCADE,
        related_name="rewrite_rules",
        verbose_name="Область",
    )
    if TYPE_CHECKING:
        scope_id: int
    mode = models.CharField(
        max_length=16,
        choices=Mode.choices,
        default=Mode.EXACT,
        verbose_name="Режим",
    )
    search = models.CharField(max_length=500, verbose_name="Искать")
    replacement = models.CharField(max_length=500, verbose_name="Заменить на")
    preprocess = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Препроцессоры",
        help_text="Список id трансформеров, применяемых до сопоставления.",
    )
    priority = models.IntegerField(
        default=100,
        validators=[MinValueValidator(0), MaxValueValidator(10_000)],
        verbose_name="Приоритет",
        help_text="Меньшее значение применяется раньше.",
    )
    enabled = models.BooleanField(default=True, verbose_name="Включено")

    class Meta(EditableModel.Meta):
        app_label = "panel"
        db_table = "panel_text_rewrite_rule"
        verbose_name = "Правило перезаписи"
        verbose_name_plural = "Правила перезаписи"
        ordering: ClassVar = ["priority", "id"]
        indexes: ClassVar = [
            models.Index(fields=["scope", "enabled", "priority"], name="panel_rewr_scope_en_prio_idx"),
            models.Index(fields=["mode", "priority"], name="panel_rewr_mode_prio_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.mode}:{self.search[:40]!r} → {self.replacement[:40]!r}"

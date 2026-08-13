"""Модели слоя L3: разрешение неоднозначностей."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import UniqueConstraint

from apps.panel.corrections.models.base import CorrectionScope, EditableModel
from apps.panel.corrections.models.matching import CorrectObject, SpellingVariant


class DisambiguationCase(EditableModel):
    """Кейс неоднозначности для варианта в контексте."""

    class Status(models.TextChoices):
        OPEN = "open", "Открыт"
        RESOLVED = "resolved", "Разрешён"
        UNRESOLVED = "unresolved", "Неразрешён"

    scope = models.ForeignKey(
        CorrectionScope,
        on_delete=models.CASCADE,
        related_name="disambiguation_cases",
        verbose_name="Область",
    )
    variant = models.ForeignKey(
        SpellingVariant,
        on_delete=models.CASCADE,
        related_name="disambiguation_cases",
        verbose_name="Вариант",
    )
    entity_type = models.SlugField(max_length=64, verbose_name="Тип сущности")
    context = models.JSONField(default=dict, blank=True, verbose_name="Контекст")
    fingerprint = models.CharField(max_length=64, verbose_name="Отпечаток контекста")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        verbose_name="Статус",
    )
    selected_object = models.ForeignKey(
        CorrectObject,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="selected_in_cases",
        verbose_name="Выбранный объект",
    )
    if TYPE_CHECKING:
        scope_id: int
        variant_id: int
        selected_object_id: int | None
        candidates: models.Manager[DisambiguationCandidate]

    class Meta(EditableModel.Meta):
        app_label = "panel"
        db_table = "panel_disambiguation_case"
        verbose_name = "Кейс неоднозначности"
        verbose_name_plural = "Кейсы неоднозначности"
        ordering: ClassVar = ["-updated_at", "id"]
        constraints: ClassVar = [
            UniqueConstraint(
                fields=["scope", "variant", "fingerprint"],
                name="panel_dcase_scope_var_fp_uniq",
            ),
        ]
        indexes: ClassVar = [
            models.Index(fields=["status"], name="panel_dcase_status_idx"),
            models.Index(fields=["scope", "entity_type", "status"], name="panel_dcase_scope_type_st_idx"),
        ]

    def __str__(self) -> str:
        return f"case#{self.pk} {self.variant_id} [{self.status}]"


class DisambiguationCandidate(EditableModel):
    """Кандидат на разрешение кейса L3."""

    case = models.ForeignKey(
        DisambiguationCase,
        on_delete=models.CASCADE,
        related_name="candidates",
        verbose_name="Кейс",
    )
    correct_object = models.ForeignKey(
        CorrectObject,
        on_delete=models.CASCADE,
        related_name="disambiguation_candidates",
        verbose_name="Корректный объект",
    )
    if TYPE_CHECKING:
        case_id: int
        correct_object_id: int
    score = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        verbose_name="Оценка [0..1]",
    )
    evidence = models.JSONField(default=dict, blank=True, verbose_name="Доказательства")
    source = models.CharField(max_length=64, default="l2", verbose_name="Источник")

    class Meta(EditableModel.Meta):
        app_label = "panel"
        db_table = "panel_disambiguation_candidate"
        verbose_name = "Кандидат разрешения"
        verbose_name_plural = "Кандидаты разрешения"
        ordering: ClassVar = ["-score", "id"]
        constraints: ClassVar = [
            UniqueConstraint(
                fields=["case", "correct_object"],
                name="panel_dcand_case_object_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"cand#{self.pk} case={self.case_id} obj={self.correct_object_id}"

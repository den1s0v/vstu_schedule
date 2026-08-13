"""Модели слоя L2: объекты, варианты написания и связи."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q, UniqueConstraint

from apps.panel.corrections.models.base import CorrectionScope, EditableModel


class CorrectObject(EditableModel):
    """Корректная сущность словаря (импорт, кластер или ручная)."""

    class Origin(models.TextChoices):
        IMPORTED = "imported", "Импортирован"
        CLUSTERED = "clustered", "Создан кластеризацией"
        MANUAL = "manual", "Создан вручную"

    scope = models.ForeignKey(
        CorrectionScope,
        on_delete=models.CASCADE,
        related_name="correct_objects",
        verbose_name="Область",
    )
    if TYPE_CHECKING:
        scope_id: int
    entity_type = models.SlugField(max_length=64, verbose_name="Тип сущности")
    external_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Внешний ID",
    )
    canonical_value = models.CharField(max_length=500, verbose_name="Каноническое значение")
    origin = models.CharField(
        max_length=16,
        choices=Origin.choices,
        default=Origin.MANUAL,
        verbose_name="Происхождение",
    )
    metadata = models.JSONField(default=dict, blank=True, verbose_name="Метаданные")

    class Meta(EditableModel.Meta):
        app_label = "panel"
        db_table = "panel_correct_object"
        verbose_name = "Корректный объект"
        verbose_name_plural = "Корректные объекты"
        ordering: ClassVar = ["entity_type", "canonical_value", "id"]
        indexes: ClassVar = [
            models.Index(fields=["scope", "entity_type"], name="panel_cobj_scope_type_idx"),
            models.Index(fields=["canonical_value"], name="panel_cobj_canonical_idx"),
            models.Index(fields=["external_id"], name="panel_cobj_external_idx"),
        ]
        constraints: ClassVar = [
            UniqueConstraint(
                fields=["scope", "entity_type", "external_id"],
                condition=~Q(external_id=""),
                name="panel_cobj_scope_type_ext_uniq",
            ),
            UniqueConstraint(
                fields=["scope", "entity_type", "canonical_value"],
                condition=Q(external_id=""),
                name="panel_cobj_scope_type_canon_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.entity_type}:{self.canonical_value[:50]}"


class SpellingVariant(EditableModel):
    """Вариант написания внутри scope и типа сущности."""

    scope = models.ForeignKey(
        CorrectionScope,
        on_delete=models.CASCADE,
        related_name="spelling_variants",
        verbose_name="Область",
    )
    if TYPE_CHECKING:
        scope_id: int
    entity_type = models.SlugField(max_length=64, verbose_name="Тип сущности")
    value = models.CharField(max_length=500, verbose_name="Значение")

    class Meta(EditableModel.Meta):
        app_label = "panel"
        db_table = "panel_spelling_variant"
        verbose_name = "Вариант написания"
        verbose_name_plural = "Варианты написания"
        ordering: ClassVar = ["entity_type", "value", "id"]
        constraints: ClassVar = [
            UniqueConstraint(
                fields=["scope", "entity_type", "value"],
                name="panel_svar_scope_type_value_uniq",
            ),
        ]
        indexes: ClassVar = [
            models.Index(fields=["scope", "entity_type", "value"], name="panel_svar_scope_type_val_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.entity_type}:{self.value[:50]}"


class VariantObjectLink(EditableModel):
    """Связь варианта написания с корректным объектом."""

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        APPROVED = "approved", "Утверждено"
        FORBIDDEN = "forbidden", "Запрещено"

    class Source(models.TextChoices):
        IMPORT = "import", "Импорт"
        FUZZY = "fuzzy", "Нечёткий поиск"
        CLUSTER = "cluster", "Кластеризация"
        MANUAL = "manual", "Вручную"

    variant = models.ForeignKey(
        SpellingVariant,
        on_delete=models.CASCADE,
        related_name="object_links",
        verbose_name="Вариант",
    )
    correct_object = models.ForeignKey(
        CorrectObject,
        on_delete=models.CASCADE,
        related_name="variant_links",
        verbose_name="Корректный объект",
    )
    if TYPE_CHECKING:
        variant_id: int
        correct_object_id: int
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Статус",
    )
    source = models.CharField(
        max_length=16,
        choices=Source.choices,
        default=Source.FUZZY,
        verbose_name="Источник",
    )
    score = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        verbose_name="Схожесть [0..1]",
    )
    confirmation_count = models.PositiveIntegerField(default=0, verbose_name="Подтверждения")

    class Meta(EditableModel.Meta):
        app_label = "panel"
        db_table = "panel_variant_object_link"
        verbose_name = "Связь варианта с объектом"
        verbose_name_plural = "Связи вариантов с объектами"
        ordering: ClassVar = ["-score", "id"]
        constraints: ClassVar = [
            UniqueConstraint(
                fields=["variant", "correct_object"],
                name="panel_volink_variant_object_uniq",
            ),
        ]
        indexes: ClassVar = [
            models.Index(fields=["status"], name="panel_volink_status_idx"),
            models.Index(fields=["variant", "status"], name="panel_volink_var_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.variant_id}→{self.correct_object_id} [{self.status}]"


class EntityCreationPolicy(EditableModel):
    """Политика авто-связывания и создания объектов для типа сущности."""

    scope = models.ForeignKey(
        CorrectionScope,
        on_delete=models.CASCADE,
        related_name="entity_policies",
        verbose_name="Область",
    )
    if TYPE_CHECKING:
        scope_id: int
    entity_type = models.SlugField(max_length=64, verbose_name="Тип сущности")
    confirmation_threshold = models.PositiveIntegerField(
        default=3,
        verbose_name="Порог кластера",
        help_text="Минимальное число похожих несвязанных вариантов для создания объекта.",
    )
    auto_link_threshold = models.FloatField(
        default=0.95,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        verbose_name="Порог авто-связи [0..1]",
    )
    suggest_threshold = models.FloatField(
        default=0.8,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        verbose_name="Порог кандидатов [0..1]",
    )
    enabled = models.BooleanField(default=True, verbose_name="Включено")

    class Meta(EditableModel.Meta):
        app_label = "panel"
        db_table = "panel_entity_creation_policy"
        verbose_name = "Политика создания сущностей"
        verbose_name_plural = "Политики создания сущностей"
        constraints: ClassVar = [
            UniqueConstraint(
                fields=["scope", "entity_type"],
                name="panel_epol_scope_type_uniq",
            ),
        ]

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if self.auto_link_threshold < self.suggest_threshold:
            raise ValidationError(
                {"auto_link_threshold": "auto_link_threshold должен быть >= suggest_threshold."}
            )

    def __str__(self) -> str:
        return f"{self.entity_type}@{self.scope_id}"

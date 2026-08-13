"""Общие модели и audit-база для курируемых сущностей корректировок."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.conf import settings
from django.db import models


class CorrectionScope(models.Model):
    """Область действия корректировок со стабильным строковым ключом."""

    key = models.SlugField(max_length=64, unique=True, verbose_name="Ключ")
    description = models.TextField(blank=True, default="", verbose_name="Описание")

    if TYPE_CHECKING:
        id: int
        pk: int

    class Meta:
        app_label = "panel"
        db_table = "panel_correction_scope"
        verbose_name = "Область корректировок"
        verbose_name_plural = "Области корректировок"
        ordering: ClassVar = ["key"]

    def __str__(self) -> str:
        return self.key


class EditableModel(models.Model):
    """Audit-поля для вручную курируемых сущностей."""

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="Кто создал",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="Кто изменил",
    )

    if TYPE_CHECKING:
        id: int
        pk: int
        created_by_id: int | None
        updated_by_id: int | None

    class Meta:
        abstract = True

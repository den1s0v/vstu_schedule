from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q, UniqueConstraint, CheckConstraint
from django.utils import timezone


class Scope(models.Model):
    """Область действия корректировок."""
    
    description = models.TextField(blank=True, null=True, verbose_name="Описание")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")
    
    class Meta:
        db_table = "scopes"
        verbose_name = "Область действия"
        verbose_name_plural = "Области действия"
        indexes = [
            models.Index(fields=["updated_at"], name="scopes_updated_at_idx"),
        ]
    
    def __str__(self) -> str:
        return f"Scope #{self.id}" + (f": {self.description[:50]}" if self.description else "")


class Occurrence(models.Model):
    """Входной объект из слоя входных данных (необработанные данные)."""
    
    value = models.CharField(max_length=500, verbose_name="Значение")
    context = models.JSONField(default=list, verbose_name="Контекст")
    score = models.FloatField(default=1.0, verbose_name="Оценка")
    approved = models.BooleanField(default=False, verbose_name="Утверждено")
    manual = models.BooleanField(default=False, verbose_name="Создано вручную")
    scope = models.ForeignKey(
        Scope,
        on_delete=models.CASCADE,
        related_name="occurrences",
        verbose_name="Область действия"
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")
    resolved_to = models.ForeignKey(
        "CorrectObject",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_occurrences",
        verbose_name="Разрешено в"
    )
    
    class Meta:
        db_table = "occurrences"
        verbose_name = "Вхождение"
        verbose_name_plural = "Вхождения"
        indexes = [
            models.Index(fields=["value"], name="occurrences_value_idx"),
            models.Index(fields=["scope"], name="occurrences_scope_idx"),
            models.Index(fields=["resolved_to"], name="occurrences_resolved_to_idx"),
        ]
        constraints = [
            # Уникальность по value и context (JSON сравнивается как текст)
            UniqueConstraint(
                fields=["value", "context"],
                name="occurrences_value_context_unique"
            ),
        ]
    
    def __str__(self) -> str:
        return f"Occurrence #{self.id}: {self.value[:50]}"


class CorrectObject(models.Model):
    """Корректный логический объект из слоя корректировок."""
    
    external_id = models.TextField(blank=True, null=True, unique=True, verbose_name="Внешний ID")
    value = models.CharField(max_length=500, verbose_name="Значение")
    required_context_elements = models.JSONField(default=list, verbose_name="Обязательные элементы контекста")
    context = models.JSONField(default=list, verbose_name="Контекст")
    score = models.FloatField(default=1.0, verbose_name="Оценка")
    approved = models.BooleanField(default=False, verbose_name="Утверждено")
    manual = models.BooleanField(default=False, verbose_name="Создано вручную")
    scope = models.ForeignKey(
        Scope,
        on_delete=models.CASCADE,
        related_name="correct_objects",
        verbose_name="Область действия"
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")
    name = models.TextField(blank=True, null=True, verbose_name="Название")
    description = models.TextField(blank=True, null=True, verbose_name="Описание")
    
    class Meta:
        db_table = "correct_objects"
        verbose_name = "Корректный объект"
        verbose_name_plural = "Корректные объекты"
        indexes = [
            models.Index(fields=["value"], name="correct_objects_value_idx"),
            models.Index(fields=["scope"], name="correct_objects_scope_idx"),
            models.Index(fields=["external_id"], name="correct_objects_external_id_idx"),
        ]
        constraints = [
            # Уникальность по external_id (если указан)
            UniqueConstraint(
                fields=["external_id"],
                condition=Q(external_id__isnull=False),
                name="correct_objects_external_id_unique"
            ),
            # Уникальность по value + required_context_elements (если external_id не указан)
            UniqueConstraint(
                fields=["value", "required_context_elements"],
                condition=Q(external_id__isnull=True),
                name="correct_objects_value_context_unique"
            ),
        ]
    
    def __str__(self) -> str:
        return f"CorrectObject #{self.id}: {self.value[:50]}"


class Resolution(models.Model):
    """Разрешение: связь Occurrence → CorrectObject."""
    
    class Status(models.IntegerChoices):
        PENDING = 0, "Ожидает проверки"
        APPROVED = 1, "Утверждено"
        INVALID = 9, "Аннулировано"
    
    occurrence = models.ForeignKey(
        Occurrence,
        on_delete=models.CASCADE,
        related_name="resolutions",
        verbose_name="Вхождение"
    )
    correct_object = models.ForeignKey(
        CorrectObject,
        on_delete=models.CASCADE,
        related_name="resolutions",
        verbose_name="Корректный объект"
    )
    manual = models.BooleanField(default=False, verbose_name="Создано вручную")
    status = models.IntegerField(
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Статус"
    )
    score = models.FloatField(default=0.0, verbose_name="Оценка")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")
    scope = models.ForeignKey(
        Scope,
        on_delete=models.CASCADE,
        related_name="resolutions",
        verbose_name="Область действия"
    )
    
    class Meta:
        db_table = "resolutions"
        verbose_name = "Разрешение"
        verbose_name_plural = "Разрешения"
        indexes = [
            models.Index(fields=["occurrence"], name="resolutions_occurrence_idx"),
            models.Index(fields=["correct_object"], name="resolutions_correct_object_idx"),
            models.Index(fields=["occurrence", "status"], name="resolutions_occurrence_status_idx"),
            models.Index(fields=["scope"], name="resolutions_scope_idx"),
            models.Index(fields=["status"], name="resolutions_status_idx"),
            models.Index(fields=["occurrence", "score"], name="resolutions_occurrence_score_idx"),
        ]
        constraints = [
            # Уникальность пары (Occurrence, CorrectObject)
            UniqueConstraint(
                fields=["occurrence", "correct_object"],
                name="resolutions_occurrence_correct_object_unique"
            ),
            # Проверка статуса
            CheckConstraint(
                check=Q(status__in=[0, 1, 9]),
                name="resolutions_status_check"
            ),
        ]
    
    def clean(self) -> None:
        """Валидация модели."""
        from django.core.exceptions import ValidationError
        
        # Проверка: максимум один APPROVED на occurrence_id
        if self.status == self.Status.APPROVED:
            existing_approved = Resolution.objects.filter(
                occurrence=self.occurrence,
                status=self.Status.APPROVED
            ).exclude(pk=self.pk if self.pk else None)
            
            if existing_approved.exists():
                raise ValidationError(
                    "Для данного вхождения уже существует утвержденное разрешение. "
                    "Сначала аннулируйте существующее."
                )
        
        super().clean()
    
    def save(self, *args, **kwargs) -> None:
        """Переопределение save для валидации."""
        self.full_clean()
        super().save(*args, **kwargs)
    
    def __str__(self) -> str:
        return f"Resolution #{self.id}: {self.occurrence.value[:30]} → {self.correct_object.value[:30]}"
    
    @property
    def is_pending(self) -> bool:
        """Проверка, является ли разрешение ожидающим проверки."""
        return self.status == self.Status.PENDING
    
    @property
    def is_approved(self) -> bool:
        """Проверка, является ли разрешение утвержденным."""
        return self.status == self.Status.APPROVED
    
    @property
    def is_invalid(self) -> bool:
        """Проверка, является ли разрешение аннулированным."""
        return self.status == self.Status.INVALID

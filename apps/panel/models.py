from typing import ClassVar

from django.db import models


class CeleryTaskConfig(models.Model):
    """Panel-managed runtime settings for a registered Celery task."""

    task_name = models.CharField(max_length=255, unique=True)
    execution_enabled = models.BooleanField(default=True)
    schedule_enabled = models.BooleanField(default=False)
    cron_minute = models.CharField(max_length=64, default="0")
    cron_hour = models.CharField(max_length=64, default="*")
    cron_day_of_week = models.CharField(max_length=64, default="*")
    cron_day_of_month = models.CharField(max_length=64, default="*")
    cron_month_of_year = models.CharField(max_length=64, default="*")
    soft_time_limit_seconds = models.PositiveIntegerField(null=True, blank=True)
    time_limit_seconds = models.PositiveIntegerField(null=True, blank=True)
    parameters = models.JSONField(default=dict, blank=True)
    periodic_task = models.OneToOneField(
        "django_celery_beat.PeriodicTask",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="panel_task_config",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "panel_celery_task_config"
        ordering: ClassVar = ["task_name"]

    def __str__(self) -> str:
        return self.task_name

    @property
    def cron_expression(self) -> str:
        return " ".join(
            [
                self.cron_minute,
                self.cron_hour,
                self.cron_day_of_month,
                self.cron_month_of_year,
                self.cron_day_of_week,
            ]
        )

    @property
    def actual_schedule_enabled(self) -> bool:
        if getattr(self, "periodic_task_id", None):
            return bool(self.periodic_task and self.periodic_task.enabled)
        return self.schedule_enabled


class CeleryTaskRun(models.Model):
    """Persisted status and result metadata for Celery task runs."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        STARTED = "STARTED", "Started"
        SUCCESS = "SUCCESS", "Success"
        FAILURE = "FAILURE", "Failure"
        RETRY = "RETRY", "Retry"
        REVOKED = "REVOKED", "Revoked"
        SKIPPED = "SKIPPED", "Skipped"

    task_id = models.CharField(max_length=255, unique=True)
    task_name = models.CharField(max_length=255, db_index=True)
    status = models.CharField(max_length=32, choices=Status, default=Status.PENDING)
    queued_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    result_text = models.TextField(blank=True, default="")
    traceback_text = models.TextField(blank=True, default="")

    class Meta:
        db_table = "panel_celery_task_run"
        ordering: ClassVar = ["-queued_at"]

    def __str__(self) -> str:
        return f"{self.task_name} [{self.status}]"


class CeleryTaskLog(models.Model):
    """Log records captured while a Celery task run is active."""

    run = models.ForeignKey(
        CeleryTaskRun,
        related_name="logs",
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    level = models.PositiveSmallIntegerField()
    level_name = models.CharField(max_length=16)
    logger_name = models.CharField(max_length=255)
    message = models.TextField()
    traceback_text = models.TextField(blank=True, default="")
    process = models.PositiveIntegerField(null=True, blank=True)
    thread = models.PositiveBigIntegerField(null=True, blank=True)
    pathname = models.CharField(max_length=1024, blank=True, default="")
    lineno = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "panel_celery_task_log"
        ordering: ClassVar = ["created_at", "id"]
        indexes: ClassVar = [
            models.Index(fields=["run", "created_at"]),
            models.Index(fields=["level"]),
        ]

    def __str__(self) -> str:
        return f"{self.level_name} {self.logger_name}: {self.message[:80]}"


from apps.panel.corrections.models import (  # noqa: E402
    CorrectionScope,
    CorrectionUsage,
    CorrectObject,
    DisambiguationCandidate,
    DisambiguationCase,
    EditableModel,
    EntityCreationPolicy,
    SpellingVariant,
    TextRewriteRule,
    VariantObjectLink,
)

__all__ = [
    "CeleryTaskConfig",
    "CeleryTaskLog",
    "CeleryTaskRun",
    "CorrectObject",
    "CorrectionScope",
    "CorrectionUsage",
    "DisambiguationCandidate",
    "DisambiguationCase",
    "EditableModel",
    "EntityCreationPolicy",
    "SpellingVariant",
    "TextRewriteRule",
    "VariantObjectLink",
]

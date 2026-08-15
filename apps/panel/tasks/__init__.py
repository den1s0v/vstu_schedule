import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from celery import current_app
from django.conf import settings
from django_celery_beat.models import CrontabSchedule, PeriodicTask

from apps.common.models import Alert
from apps.common.services.alerts import create_alert
from apps.panel.exceptions import CeleryTaskNotRegisteredError
from apps.panel.services.task_parameters import celery_task_kwargs
from vstu_schedule.tasks.decorators import project_task
from vstu_schedule.tasks.descriptors import get_task_descriptor

logger = logging.getLogger(__name__)

DISPATCH_CONFIGURED_TASK_NAME = "panel.tasks.dispatch_configured_task"


@project_task(name="panel.tasks.run_panel_action", max_retries=0)
def run_panel_action_task(
    self: Any,
    action_id: str,
    *,
    upload_path: str = "",
    mode: str = "",
) -> dict[str, str]:
    from apps.panel.services.actions import get_panel_action, run_panel_action

    action = get_panel_action(action_id)
    try:
        message = run_panel_action(action_id, upload_path=upload_path, mode=mode)
        logger.info(
            "Panel action completed: %s [id=%s]",
            action_id,
            self.request.id,
        )
        return {"status": "success", "action": action_id, "message": message}
    except Exception as exc:
        logger.error("Panel action failed: %s", action_id, exc_info=True)
        create_alert(
            title=f"Ошибка действия панели: {action.title}",
            body=str(exc),
            category=Alert.Category.DANGER,
            is_admin=True,
            is_dismissible=True,
        )
        raise
    finally:
        if upload_path:
            Path(upload_path).unlink(missing_ok=True)


def _task_apply_options(task_name: str) -> dict[str, Any]:
    from apps.panel.models import CeleryTaskConfig

    config = CeleryTaskConfig.objects.filter(task_name=task_name).first()
    if not config:
        return {}

    options = {}
    if config.soft_time_limit_seconds:
        options["soft_time_limit"] = config.soft_time_limit_seconds
    if config.time_limit_seconds:
        options["time_limit"] = config.time_limit_seconds
    descriptor = get_task_descriptor(task_name)
    if descriptor and descriptor.parameters:
        options["kwargs"] = celery_task_kwargs(descriptor.parameters, config.parameters)
    return options


@project_task(name=DISPATCH_CONFIGURED_TASK_NAME)
def dispatch_configured_task(self: Any, task_name: str) -> dict[str, str]:
    """Queue a configured task using the latest DB settings."""
    from apps.panel.models import CeleryTaskConfig

    config = CeleryTaskConfig.objects.filter(task_name=task_name).first()
    if not config or not config.execution_enabled:
        logger.info("Configured task dispatch skipped: %s", task_name)
        return {"status": "skipped", "task": task_name}

    celery_app = cast(Any, current_app)
    task = celery_app.tasks.get(task_name)
    if task is None:
        raise CeleryTaskNotRegisteredError(f"Celery task is not registered: {task_name}")

    result = task.apply_async(**_task_apply_options(task_name))
    logger.info(
        "Configured task dispatched: %s [dispatcher_id=%s, task_id=%s]",
        task_name,
        self.request.id,
        result.id,
    )
    return {"status": "queued", "task": task_name, "task_id": result.id}


@project_task(name="panel.tasks.update_timetable", max_retries=3)
def update_timetable(self: Any) -> dict[str, str]:
    """
    Celery-задача: скачивает файлы расписания и сохраняет новые версии локально.
    Запускается периодически через Celery Beat.
    Может быть запущена вручную из панели управления.
    """
    logger.info(f"Task started: update_timetable [id={self.request.id}]")
    try:
        from apps.common.services.timetable_update.update_timetable import run_timetable_update

        run_timetable_update()
        logger.info("Task update_timetable completed")
        return {"status": "success"}
    except Exception as exc:
        logger.error(f"Task update_timetable failed: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60) from exc


def _optional_flag(value: Any) -> bool | None:
    """Пустая строка / None → из env; иначе bool."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text == "":
        return None
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"Invalid flag value: {value!r}")


@project_task(name="panel.tasks.import_saved_timetables", max_retries=0)
def import_saved_timetables(
    self: Any,
    academic_year: str,
    semester: int,
    semester_start_date: Any,
    semester_end_date: Any,
    starting_day_number: int = 0,
    changed_only: bool = True,
    save_archive_schedules: bool = True,
    resource_ids: str = "",
    use_corrections: Any = None,
    corrections_strict: Any = None,
) -> dict[str, Any]:
    logger.info("Task started: import_saved_timetables [id=%s]", self.request.id)
    from apps.common.services.timetable.parse import (
        TimetableImportContext,
        run_saved_timetable_import_pipeline,
    )
    from apps.panel.services.corrections.import_flags import (
        build_import_resolver,
        resolve_import_flags,
    )

    def format_date(value: Any) -> str:
        if isinstance(value, datetime | date):
            return value.strftime("%d.%m.%Y")
        if isinstance(value, str):
            return date.fromisoformat(value).strftime("%d.%m.%Y")
        return str(value)

    selected_resource_ids = [
        int(value.strip()) for value in resource_ids.split(",") if value.strip()
    ]
    enabled, strict = resolve_import_flags(
        use_corrections=_optional_flag(use_corrections),
        corrections_strict=_optional_flag(corrections_strict),
    )
    resolver = build_import_resolver(use_corrections=enabled, seed=enabled)
    result = run_saved_timetable_import_pipeline(
        TimetableImportContext(
            academic_year=academic_year,
            semester=semester,
            semester_start_date=format_date(semester_start_date),
            semester_end_date=format_date(semester_end_date),
            starting_day_number=starting_day_number,
        ),
        changed_only=changed_only,
        save_archive_schedules=save_archive_schedules,
        resource_ids=selected_resource_ids or None,
        resolver=resolver,
        corrections_strict=strict,
        use_corrections=enabled,
    )
    logger.info("Task import_saved_timetables completed: %s", result.as_dict())
    return result.as_dict()


@project_task(name="panel.tasks.clear_storage")
def clear_storage_task(self: Any, component: str) -> dict[str, str]:
    """
    Celery-задача: очистка компонента системы.
    Запускается вручную из панели управления.

    :param component: "Вся система", "Хранилище" или "База данных"
    """
    logger.info(f"Task started: clear_storage [component={component!r}, id={self.request.id}]")
    try:
        from apps.common.services.timetable_update.clear_storage import (
            clear_storage_by_component,
        )

        clear_storage_by_component(component, preserve_task_id=self.request.id)
        logger.info(f"Task clear_storage completed: {component!r}")
        return {"status": "success", "component": component}
    except Exception as exc:
        logger.error(f"Task clear_storage failed: {exc}", exc_info=True)
        raise


@project_task(name="panel.tasks.delete_revoked_api_clients")
def delete_revoked_api_clients_task(self: Any) -> dict[str, int | str]:
    """Delete revoked API clients. Manual maintenance task, disabled by default."""
    logger.info("Task started: delete_revoked_api_clients [id=%s]", self.request.id)
    from apps.api.services.cleanup import delete_revoked_api_clients

    deleted_count = delete_revoked_api_clients()
    logger.info("Task delete_revoked_api_clients completed: deleted=%s", deleted_count)
    return {"status": "success", "deleted_count": deleted_count}


def configure_periodic_update(interval_minutes: int) -> None:
    """
    Создаёт или обновляет периодическую задачу обновления расписания в Celery Beat.
    Вызывается из view при сохранении настроек.

    :param interval_minutes: интервал запуска в минутах
    """
    from apps.panel.models import CeleryTaskConfig

    task_name = update_timetable.name
    config, _ = CeleryTaskConfig.objects.get_or_create(task_name=task_name)
    config.execution_enabled = True
    config.schedule_enabled = True
    config.cron_minute = "0"
    config.cron_hour = f"*/{interval_minutes // 60}" if interval_minutes >= 60 else "*"
    config.cron_day_of_week = "*"
    config.cron_day_of_month = "*"
    config.cron_month_of_year = "*"
    config.save()

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute=config.cron_minute,
        hour=config.cron_hour,
        day_of_week=config.cron_day_of_week,
        day_of_month=config.cron_day_of_month,
        month_of_year=config.cron_month_of_year,
        timezone=settings.TIME_ZONE,
    )
    periodic_task, _ = PeriodicTask.objects.update_or_create(
        name="Автообновление расписания",
        defaults={
            "task": DISPATCH_CONFIGURED_TASK_NAME,
            "crontab": schedule,
            "interval": None,
            "args": json.dumps([task_name]),
            "enabled": True,
        },
    )
    config.periodic_task = periodic_task
    config.save(update_fields=["periodic_task", "updated_at"])
    logger.info(f"Periodic update configured: every {interval_minutes} min")

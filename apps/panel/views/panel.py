import logging
import uuid
from pathlib import Path
from typing import Any, cast

from celery.result import AsyncResult
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from apps.common.models import Setting
from apps.panel.selectors import cancellation_departments
from apps.panel.services.actions import (
    PANEL_ACTIONS_BY_ID,
    PASSWORD_REQUIRED_ACTION_IDS,
    get_panel_action,
)

logger = logging.getLogger(__name__)

CLEAR_TYPES = ["Вся система", "Хранилище", "Логи задач", "Расписания"]


# ======================== ДЕЙСТВИЯ ========================


@staff_member_required
def actions_panel(request: HttpRequest) -> HttpResponse:
    context = {
        "active_nav": "actions",
        "cancellation_departments": cancellation_departments(),
        "file_actions": [
            action for action in PANEL_ACTIONS_BY_ID.values() if action.kind == "file"
        ],
        "button_actions": [
            action for action in PANEL_ACTIONS_BY_ID.values() if action.kind == "button"
        ],
    }
    return render(request, "panel/actions.html", context)


@staff_member_required
def run_panel_action(request: HttpRequest) -> JsonResponse | HttpResponse:
    if request.method == "GET" and "task_id" in request.GET:
        return _task_status_response(request.GET["task_id"])

    if request.method != "POST":
        return HttpResponse(status=405)

    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return _celery_disabled_response()

    action_id = request.POST.get("action_id", "")
    try:
        action = get_panel_action(action_id)
    except ValueError as exc:
        return JsonResponse({"status": "error", "error_message": str(exc)}, status=400)

    if action_id in PASSWORD_REQUIRED_ACTION_IDS:
        password_error = _check_confirm_password(request)
        if password_error is not None:
            return password_error

    upload_path = ""
    if action.kind == "file":
        upload = request.FILES.get(action.file_field)
        if upload is None:
            return JsonResponse(
                {"status": "error", "error_message": "Файл не выбран."},
                status=400,
            )
        upload_path = _save_panel_action_upload(upload)

    from apps.panel.tasks import run_panel_action_task

    result = run_panel_action_task.delay(
        action_id,
        upload_path=upload_path,
        mode=request.POST.get(action.mode_field, "") if action.mode_field else "",
    )
    logger.info("panel action launched: action=%s task_id=%s", action_id, result.id)
    return JsonResponse({"status": "running", "id": result.id}, status=202)


# ======================== НАСТРОЙКИ ========================


@staff_member_required
def set_system_params(request: HttpRequest) -> JsonResponse:
    """Сохраняет системные параметры: интервал обновления и URL анализа."""
    if request.method != "POST":
        return JsonResponse(
            {"status": "error", "error_message": "Метод не поддерживается"}, status=405
        )

    try:
        scan_frequency = request.POST.get("scanFrequency")
        root_url = request.POST.get("rootUrl")

        if scan_frequency:
            minutes = int(scan_frequency)
            setting, _ = Setting.objects.get_or_create(key="time_update")
            setting.value = str(minutes)
            setting.description = "Частота обновления расписания в минутах"
            setting.save()

            from apps.panel.tasks import configure_periodic_update

            configure_periodic_update(minutes)

        if root_url:
            setting, _ = Setting.objects.get_or_create(key="analyze_url")
            setting.value = root_url
            setting.description = "Корневая ссылка для анализа расписания"
            setting.save()

        return JsonResponse({"status": "success"})
    except ValueError:
        return JsonResponse(
            {"status": "error", "error_message": "Некорректное значение частоты"}, status=400
        )
    except Exception as e:
        logger.error(f"set_system_params error: {e}", exc_info=True)
        return JsonResponse({"status": "error", "error_message": str(e)}, status=500)


# ======================== ВСПОМОГАТЕЛЬНОЕ ========================


def _task_status_response(task_id: str) -> JsonResponse:
    """Возвращает текущий статус Celery-задачи по её ID."""
    result = AsyncResult(task_id)
    task_result = result.result if isinstance(result.result, dict) else {}
    if result.successful() and task_result.get("status") == "skipped":
        return JsonResponse(
            {
                "status": "error",
                "error_message": task_result.get(
                    "message", "Another maintenance task is already running."
                ),
            }
        )

    status_map = {
        "SUCCESS": "success",
        "FAILURE": "error",
        "PENDING": "running",
        "STARTED": "running",
        "RETRY": "running",
    }
    status = status_map.get(result.status, "running")
    error_message = str(result.result) if result.failed() else None
    return JsonResponse({"status": status, "error_message": error_message})


def _check_confirm_password(request: HttpRequest) -> JsonResponse | None:
    """Проверяет пароль текущего пользователя, переданный в POST["confirm_password"]."""
    password = request.POST.get("confirm_password", "")
    if not password or not request.user.check_password(password):
        return JsonResponse({"status": "error", "error_message": "Неверный пароль."}, status=403)
    return None


def _celery_disabled_response() -> JsonResponse:
    """Prevents long maintenance tasks from running inside a web request."""
    return JsonResponse(
        {
            "status": "error",
            "error_message": "Celery отключён: фоновые задачи нельзя запускать из web-процесса.",
        },
        status=503,
    )


def _save_panel_action_upload(upload: Any) -> str:
    upload_dir = settings.DATA_STORAGE_DIR / "panel_action_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(upload.name).suffix
    upload_path = upload_dir / f"{uuid.uuid4()}{suffix}"
    with upload_path.open("wb") as destination:
        for chunk in upload.chunks():
            destination.write(chunk)
    return str(upload_path)


# ======================== ЗАДАЧИ ========================


@staff_member_required
def run_update_timetable(request: HttpRequest) -> JsonResponse | HttpResponse:
    """
    POST — запускает задачу обновления расписания.
    GET ?task_id=... — возвращает статус запущенной задачи.
    """
    if request.method == "POST":
        if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
            return _celery_disabled_response()

        from apps.panel.tasks import _task_apply_options
        from apps.panel.tasks import update_timetable as update_task

        task_name = cast(str, cast(Any, update_task).name)
        result = cast(Any, update_task).apply_async(**_task_apply_options(task_name))
        logger.info(f"update_timetable launched: task_id={result.id}")
        return JsonResponse({"status": "running", "id": result.id}, status=202)

    if request.method == "GET" and "task_id" in request.GET:
        return _task_status_response(request.GET["task_id"])

    return HttpResponse(status=400)


@staff_member_required
def manage_storage(request: HttpRequest) -> JsonResponse | HttpResponse:
    """
    POST — запускает задачу очистки хранилища.
    GET ?task_id=... — возвращает статус задачи.
    """
    if request.method == "POST" and request.POST.get("action") == "dell":
        if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
            return _celery_disabled_response()

        password_error = _check_confirm_password(request)
        if password_error is not None:
            return password_error

        component = request.POST.get("component", "")
        from apps.panel.tasks import clear_storage_task

        result = clear_storage_task.delay(component)  # type: ignore[union-attr]
        logger.info(f"clear_storage launched: component={component!r}, task_id={result.id}")
        return JsonResponse({"status": "running", "id": result.id}, status=202)

    if request.method == "GET" and "task_id" in request.GET:
        return _task_status_response(request.GET["task_id"])

    return HttpResponse(status=400)

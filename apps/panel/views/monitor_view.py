import logging
import mimetypes
import re
from pathlib import Path

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.common.models import Alert, FileVersion, Resource, Setting
from apps.common.selectors import admin_alerts
from apps.common.services.alerts import render_alert_body
from apps.panel.selectors import cancellation_departments

logger = logging.getLogger(__name__)


# ======================== МОНИТОРИНГ ========================


SCAN_FREQUENCY_PRESETS = ("120", "180", "240", "360", "420")


@staff_member_required
def monitoring_panel(request: HttpRequest) -> HttpResponse:
    """Страница мониторинга состояния процесса скачивания расписания."""
    time_update_value, time_update_display = _get_current_scan_interval_minutes()
    analyze_url = (
        Setting.objects.filter(key="analyze_url").values_list("value", flat=True).first()
        or "https://www.vstu.ru/student/raspisaniya/zanyatiy/"
    )

    return render(
        request,
        "panel/timetable_update/monitoring.html",
        {
            "active_nav": "monitoring",
            "cancellation_departments": cancellation_departments(),
            "time_update_value": time_update_value,
            "time_update_display": time_update_display,
            "time_update_is_custom": time_update_value not in SCAN_FREQUENCY_PRESETS,
            "analyze_url_value": analyze_url,
        },
    )


@staff_member_required
def monitoring_stats(request: HttpRequest) -> JsonResponse:
    """
    API: возвращает статистику и данные для панели мониторинга.
    GET /panel/timetable_update/stats
    """
    total_resources = Resource.objects.count()
    active_resources = Resource.objects.filter(deprecated=False).count()
    deprecated_resources = Resource.objects.filter(deprecated=True).count()
    total_versions = FileVersion.objects.count()

    last_version = FileVersion.objects.order_by("-timestamp").first()
    last_update_time = last_version.timestamp.isoformat() if last_version else None

    recent_versions = list(
        FileVersion.objects.select_related("resource")
        .order_by("-timestamp")[:20]
        .values(
            "id",
            "timestamp",
            "last_changed",
            "mimetype",
            "hashsum",
            "resource__name",
            "resource__path",
            "resource__deprecated",
        )
    )
    for v in recent_versions:
        v["timestamp"] = v["timestamp"].isoformat() if v["timestamp"] else None
        v["last_changed"] = v["last_changed"].isoformat() if v["last_changed"] else None
        v["hashsum_hex"] = v["hashsum"] or None

    resources = list(
        Resource.objects.order_by("deprecated", "-last_update").values(
            "id", "name", "path", "deprecated", "last_update"
        )
    )
    for r in resources:
        r["last_update"] = r["last_update"].isoformat() if r["last_update"] else None
        if r["path"]:
            resource_dir = settings.DATA_STORAGE_DIR / r["path"].strip("/")
            r["has_file"] = resource_dir.exists() and any(resource_dir.rglob("*"))
        else:
            r["has_file"] = False

    return JsonResponse(
        {
            "stats": {
                "total_resources": total_resources,
                "active_resources": active_resources,
                "deprecated_resources": deprecated_resources,
                "total_versions": total_versions,
                "last_update_time": last_update_time,
            },
            "scheduler": _get_scheduler_info(),
            "recent_versions": recent_versions,
            "resources": resources,
        }
    )


@staff_member_required
def admin_alerts_feed(request: HttpRequest) -> JsonResponse:
    alerts = [
        {
            "id": alert.pk,
            "category": alert.category,
            "icon_name": alert.icon_name,
            "title": alert.display_title,
            "body": alert.display_body,
            "body_html": render_alert_body(alert.display_body),
            "is_dismissible": alert.is_dismissible,
            "dismiss_url": reverse("dismiss_admin_alert", args=[alert.pk]),
        }
        for alert in admin_alerts()
    ]
    return JsonResponse({"alerts": alerts})


@staff_member_required
@require_POST
def dismiss_admin_alert(request: HttpRequest, alert_id: int) -> JsonResponse:
    alert = Alert.objects.filter(pk=alert_id, is_admin=True).first()
    if not alert:
        raise Http404("Alert not found")

    deleted = False
    if alert.is_dismissible:
        alert.delete()
        deleted = True
    return JsonResponse({"ok": True, "deleted": deleted})


@staff_member_required
def download_resource(request: HttpRequest, resource_id: int) -> FileResponse | HttpResponse:
    """
    GET /panel/timetable_update/download/<resource_id>/
    Отдаёт актуальный файл ресурса из DATA_STORAGE_DIR для скачивания.
    """
    try:
        resource = Resource.objects.get(id=resource_id)
    except Resource.DoesNotExist:
        raise Http404("Ресурс не найден") from None

    if not resource.path:
        raise Http404("Путь к файлу не задан")

    # Нормализуем путь — убираем ведущий/завершающий слэш
    resource_path = resource.path.strip("/")
    resource_dir = settings.DATA_STORAGE_DIR / resource_path

    if not resource_dir.exists():
        raise Http404("Директория ресурса не найдена в хранилище")

    # Ищем все файлы рекурсивно
    files = sorted(
        (f for f in resource_dir.rglob("*") if f.is_file()),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise Http404("Файлы в директории ресурса отсутствуют")

    file_path: Path = files[0]
    # Отдаём файл под оригинальным именем ресурса
    original_name = resource.name + file_path.suffix
    content_type, _ = mimetypes.guess_type(str(file_path))
    content_type = content_type or "application/octet-stream"

    logger.info(f"Resource download: id={resource_id}, file={file_path.name}")
    return FileResponse(
        open(file_path, "rb"),
        as_attachment=True,
        filename=original_name,
        content_type=content_type,
    )


# ======================== ВСПОМОГАТЕЛЬНОЕ ========================


def _get_current_scan_interval_minutes() -> tuple[str, str]:
    """
    Определяет реальную частоту сканирования по фактическому cron-расписанию задачи
    update_timetable (а не по ранее сохранённому значению Setting, которое может
    разойтись с расписанием, если его поменяли напрямую в настройках задачи).

    Возвращает (value, display):
      - value — значение в минутах, пригодное для сравнения с опциями combobox'а
        (пустая строка, если расписание нельзя выразить как "каждые N минут");
      - display — то же значение, либо человекочитаемое cron-выражение для
        нестандартного расписания.
    """
    from apps.panel.models import CeleryTaskConfig
    from apps.panel.tasks import update_timetable

    config = CeleryTaskConfig.objects.filter(task_name=update_timetable.name).first()
    if not config or not config.schedule_enabled:
        return "180", "180"

    is_standard = (
        config.cron_minute == "0"
        and config.cron_day_of_week == "*"
        and config.cron_day_of_month == "*"
        and config.cron_month_of_year == "*"
    )
    if is_standard:
        if config.cron_hour == "*":
            return "60", "60"
        match = re.fullmatch(r"\*/(\d+)", config.cron_hour)
        if match:
            minutes = str(int(match.group(1)) * 60)
            return minutes, minutes

    cron_expr = (
        f"{config.cron_minute} {config.cron_hour} {config.cron_day_of_month} "
        f"{config.cron_month_of_year} {config.cron_day_of_week}"
    )
    return "", cron_expr


def _get_scheduler_info() -> dict:
    """Возвращает информацию о периодической задаче из Celery Beat."""
    try:
        from django_celery_beat.models import PeriodicTask

        task = PeriodicTask.objects.filter(name="Автообновление расписания").first()
        if not task:
            return {"configured": False}
        return {
            "configured": True,
            "enabled": task.enabled,
            "interval": str(task.interval or task.crontab)
            if task.interval or task.crontab
            else None,
            "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
            "total_run_count": task.total_run_count,
        }
    except Exception as e:
        logger.warning(f"Could not fetch scheduler info: {e}")
        return {"configured": False, "error": str(e)}

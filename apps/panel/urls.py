from django.urls import path
from django.views.generic import RedirectView

from apps.panel.views import api_clients, monitor_view, task_view
from apps.panel.views.corrections import (
    corrections_index,
    corrections_l1,
    corrections_l2,
    corrections_l3,
)

from .views import panel

urlpatterns = [
    path("corrections/", corrections_index, name="panel_corrections"),
    path("corrections/l1/", corrections_l1, name="panel_corrections_l1"),
    path("corrections/l2/", corrections_l2, name="panel_corrections_l2"),
    path("corrections/l3/", corrections_l3, name="panel_corrections_l3"),
    path("", RedirectView.as_view(url="/panel/timetable_update/", permanent=False)),
    path("login/", RedirectView.as_view(pattern_name="admin:login", permanent=False)),
    path("actions/", panel.actions_panel, name="panel_actions"),
    path("actions/run/", panel.run_panel_action, name="panel_action_run"),
    path("api-clients/", api_clients.api_clients_panel, name="panel_api_clients"),
    path(
        "api-clients/<int:client_id>/revoke/",
        api_clients.revoke_api_client,
        name="panel_api_client_revoke",
    ),
    path(
        "api-clients/<int:client_id>/rotate/",
        api_clients.rotate_api_client_secret,
        name="panel_api_client_rotate",
    ),
    # API и страница мониторинга — под /panel/timetable_update/ (см. обсуждение в PR)
    path("timetable_update/stats/", monitor_view.monitoring_stats, name="monitoring_stats"),
    path("alerts/", monitor_view.admin_alerts_feed, name="admin_alerts_feed"),
    path(
        "alerts/<int:alert_id>/dismiss/",
        monitor_view.dismiss_admin_alert,
        name="dismiss_admin_alert",
    ),
    path(
        "timetable_update/download/<int:resource_id>/",
        monitor_view.download_resource,
        name="download_resource",
    ),
    path("timetable_update/settings/", panel.set_system_params, name="set_system_params"),
    path("timetable_update/manage_storage/", panel.manage_storage, name="manage_storage"),
    path("timetable_update/update_timetable/", panel.run_update_timetable, name="update_timetable"),
    path("timetable_update/", monitor_view.monitoring_panel, name="monitoring_panel"),
    path("tasks/", task_view.tasks_panel, name="panel_tasks"),
    path("tasks/<str:task_name>/configure/", task_view.task_configure, name="panel_task_configure"),
    path("tasks/<str:task_name>/run/", task_view.task_run, name="panel_task_run"),
    path("tasks/<str:task_name>/stop/", task_view.task_stop, name="panel_task_stop"),
    path("tasks/<str:task_name>/log/", task_view.task_log, name="panel_task_log"),
]

"""URL конфигурация для приложения panel."""

from django.urls import path

from apps.panel.views import corrections

app_name = "panel"

urlpatterns = [
    path(
        "corrections/",
        corrections.resolution_list,
        name="corrections:resolution_list"
    ),
    path(
        "corrections/<int:resolution_id>/edit/",
        corrections.resolution_edit,
        name="corrections:resolution_edit"
    ),
]

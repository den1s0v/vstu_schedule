from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, JsonResponse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from apps.panel.forms import EventCancellationForm
from apps.panel.selectors import cancellations_for_period
from apps.panel.services.event_cancellations import (
    create_cancellations,
    delete_cancellations,
)


def _form_error(form: EventCancellationForm) -> JsonResponse:
    return JsonResponse(
        {"error": " ".join(str(error) for errors in form.errors.values() for error in errors)},
        status=400,
    )


@staff_member_required
@require_http_methods(["GET", "POST"])
def event_cancellations(request: HttpRequest) -> JsonResponse:
    form = EventCancellationForm(request.GET if request.method == "GET" else request.POST)
    if not form.is_valid():
        return _form_error(form)
    selection = form.selection()
    if request.method == "POST":
        try:
            return JsonResponse(create_cancellations(selection))
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
    cancellations = cancellations_for_period(
        selection.left_date, selection.right_date, selection.department_ids
    )
    return JsonResponse(
        {
            "count": cancellations.count(),
            "cancellations": [
                {"id": item.pk, "date": item.date.isoformat(), "department": item.department.name}
                for item in cancellations[:200]
            ],
        }
    )


@staff_member_required
@require_POST
def delete_event_cancellations(request: HttpRequest) -> JsonResponse:
    scope = request.POST.get("scope")
    if scope == "all":
        if request.POST.get("confirm_all") != "yes":
            return JsonResponse({"error": _("Подтвердите удаление всех отмен.")}, status=400)
        selection = None
    elif scope == "range":
        form = EventCancellationForm(request.POST)
        if not form.is_valid():
            return _form_error(form)
        selection = form.selection()
    else:
        return JsonResponse({"error": _("Выберите область удаления отмен.")}, status=400)
    try:
        return JsonResponse(delete_cancellations(selection))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

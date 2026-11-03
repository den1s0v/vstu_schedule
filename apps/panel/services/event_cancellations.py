from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.common.models import Department, Event, EventCancel
from apps.panel.selectors import cancellations_for_period

MAX_CANCELLATION_DAYS = 366


@dataclass(frozen=True)
class CancellationSelection:
    left_date: date
    right_date: date
    department_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.right_date < self.left_date:
            raise ValueError(_("Конечная дата должна быть не раньше начальной."))


def _lock_departments(department_ids: tuple[int, ...] = ()) -> list[int]:
    departments = Department.objects.select_for_update().order_by("pk")
    if department_ids:
        departments = departments.filter(pk__in=department_ids)
    locked_ids = list(departments.values_list("pk", flat=True))
    if department_ids and set(locked_ids) != set(department_ids):
        raise ValueError(_("Выбранное подразделение не найдено. Обновите страницу."))
    return locked_ids


@transaction.atomic
def create_cancellations(selection: CancellationSelection) -> dict[str, int]:
    if (selection.right_date - selection.left_date).days >= MAX_CANCELLATION_DAYS:
        raise ValueError(_("Для создания отмен выберите период не более 366 дней."))
    department_ids = _lock_departments(selection.department_ids)
    cancellations = {
        (day, department_id): cancellation_id
        for day, department_id, cancellation_id in cancellations_for_period(
            selection.left_date, selection.right_date, selection.department_ids
        ).values_list("date", "department_id", "pk")
    }
    existing_count = len(cancellations)
    missing = [
        EventCancel(date=selection.left_date + timedelta(days=offset), department_id=department_id)
        for offset in range((selection.right_date - selection.left_date).days + 1)
        for department_id in department_ids
        if (selection.left_date + timedelta(days=offset), department_id) not in cancellations
    ]
    # Apply cancellation flags in batches below instead of calling save() for each day/event.
    EventCancel.objects.bulk_create(missing, batch_size=1000)
    cancellations = {
        (day, department_id): cancellation_id
        for day, department_id, cancellation_id in cancellations_for_period(
            selection.left_date, selection.right_date, selection.department_ids
        ).values_list("date", "department_id", "pk")
    }
    events = (
        Event.objects.filter(
            date__range=(selection.left_date, selection.right_date),
            abstract_event__schedule__schedule_template__department_id__in=department_ids,
        )
        .exclude(is_event_canceled=True, event_cancel__isnull=True)
        .values_list("pk", "date", "abstract_event__schedule__schedule_template__department_id")
    )
    updates = [
        Event(
            pk=event_id,
            is_event_canceled=True,
            event_cancel_id=cancellations[(event_date, department_id)],
            datemodified=timezone.now(),
        )
        for event_id, event_date, department_id in events
    ]
    Event.objects.bulk_update(
        updates, ["is_event_canceled", "event_cancel", "datemodified"], batch_size=1000
    )
    return {"created": len(missing), "existing": existing_count, "events_updated": len(updates)}


@transaction.atomic
def delete_cancellations(selection: CancellationSelection | None) -> dict[str, int]:
    _lock_departments(selection.department_ids if selection else ())
    cancellations = (
        cancellations_for_period(
            selection.left_date, selection.right_date, selection.department_ids
        )
        if selection
        else EventCancel.objects.all()
    )
    cancellation_ids = list(cancellations.values_list("pk", flat=True))
    # Detach first so the model's deletion signals do not save every event separately.
    # Independently cancelled events (without event_cancel) must remain cancelled.
    restored = Event.objects.filter(event_cancel_id__in=cancellation_ids).update(
        is_event_canceled=False, event_cancel=None, datemodified=timezone.now()
    )
    cancellations.delete()
    return {"deleted": len(cancellation_ids), "events_restored": restored}

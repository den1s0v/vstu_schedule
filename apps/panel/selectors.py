from datetime import date

from django.db.models import QuerySet

from apps.common.models import Department, EventCancel


def cancellation_departments() -> QuerySet[Department]:
    return Department.objects.order_by("name", "pk")


def cancellations_for_period(
    left_date: date, right_date: date, department_ids: tuple[int, ...] = ()
) -> QuerySet[EventCancel]:
    cancellations = EventCancel.objects.filter(date__range=(left_date, right_date))
    if department_ids:
        cancellations = cancellations.filter(department_id__in=department_ids)
    return cancellations.select_related("department").order_by("date", "department__name", "pk")

from datetime import date, time

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from pytest_django.fixtures import Settings

from apps.common.models import (
    AbstractDay,
    AbstractEvent,
    Department,
    Event,
    EventCancel,
    Organization,
    Schedule,
    ScheduleTemplate,
    Subject,
    TimeSlot,
)
from apps.panel.services.event_cancellations import (
    CancellationSelection,
    create_cancellations,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def static_storage(settings: Settings) -> None:
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture
def sample_events() -> tuple[Event, Event, Event]:
    organization = Organization.objects.create(name="Example university")
    day = AbstractDay.objects.create(name="Example Monday", day_number=0)
    subject = Subject.objects.create(name="Example subject")
    slot = TimeSlot.objects.create(start_time=time(9), end_time=time(10))
    events = []
    for code in ("EX-A", "EX-B"):
        department = Department.objects.create(name=code, code=code, organization=organization)
        template = ScheduleTemplate.objects.create(
            department=department, repetition_period=7, repeatable=True, aligned_by_week_day=1
        )
        schedule = Schedule.objects.create(
            schedule_template=template,
            start_date=date(2026, 11, 2),
            end_date=date(2026, 11, 30),
            starting_day_number=day,
        )
        abstract_event = AbstractEvent.objects.create(
            subject=subject, abstract_day=day, time_slot=slot, schedule=schedule
        )
        events.append(
            Event.objects.create(
                date=date(2026, 11, 2),
                abstract_event=abstract_event,
                subject_override=subject,
                time_slot_override=slot,
            )
        )
    later = Event.objects.create(
        date=date(2026, 11, 5),
        abstract_event=events[0].abstract_event,
        subject_override=subject,
        time_slot_override=slot,
    )
    return events[0], events[1], later


@pytest.mark.parametrize("all_departments", [False, True])
def test_create_range_is_inclusive_idempotent_and_applies_to_events(
    admin_client: Client, sample_events: tuple[Event, Event, Event], all_departments: bool
) -> None:
    first, second, later = sample_events
    data = {"left_date": "2026-11-02", "right_date": "2026-11-04"}
    if not all_departments:
        data["departments"] = str(first.department.pk)
    expected_records = 6 if all_departments else 3

    response = admin_client.post(reverse("panel_event_cancellations"), data)

    assert response.status_code == 200
    assert response.json()["created"] == expected_records
    for event, canceled in ((first, True), (second, all_departments), (later, False)):
        event.refresh_from_db()
        assert event.is_event_canceled is canceled
    repeated = admin_client.post(reverse("panel_event_cancellations"), data)
    assert repeated.json()["created"] == 0
    assert repeated.json()["existing"] == expected_records
    assert EventCancel.objects.count() == expected_records
    future_event = Event.objects.create(
        date=date(2026, 11, 3),
        abstract_event=first.abstract_event,
        subject_override=first.subject_override,
        time_slot_override=first.time_slot_override,
    )
    assert future_event.is_event_canceled is True
    assert future_event.event_cancel is not None


def test_single_date_preview_and_delete_respect_department_filter(
    admin_client: Client, sample_events: tuple[Event, Event, Event]
) -> None:
    first, second, _ = sample_events
    create_cancellations(CancellationSelection(date(2026, 11, 2), date(2026, 11, 3)))
    filters = {"left_date": "2026-11-02", "departments": first.department.pk}

    preview = admin_client.get(reverse("panel_event_cancellations"), filters)
    assert preview.status_code == 200
    assert preview.json()["count"] == 1
    assert preview.json()["cancellations"][0]["department"] == first.department.name
    result = admin_client.post(
        reverse("panel_event_cancellations_delete"), {**filters, "scope": "range"}
    )
    assert result.json() == {"deleted": 1, "events_restored": 1}
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.is_event_canceled is False
    assert first.event_cancel is None
    assert second.is_event_canceled is True
    assert EventCancel.objects.count() == 3


def test_search_and_delete_allow_periods_longer_than_a_year(
    admin_client: Client, sample_events: tuple[Event, Event, Event]
) -> None:
    create_cancellations(CancellationSelection(date(2026, 11, 2), date(2026, 11, 2)))
    filters = {"left_date": "2025-01-01", "right_date": "2027-12-31"}
    preview = admin_client.get(reverse("panel_event_cancellations"), filters)
    assert preview.status_code == 200
    assert preview.json()["count"] == 2
    deleted = admin_client.post(
        reverse("panel_event_cancellations_delete"), {**filters, "scope": "range"}
    )
    assert deleted.json() == {"deleted": 2, "events_restored": 2}


def test_delete_all_restores_linked_events_and_preserves_manual_cancellations(
    admin_client: Client, sample_events: tuple[Event, Event, Event]
) -> None:
    first, second, manual = sample_events
    second.is_event_canceled = True
    second.save()
    create_cancellations(CancellationSelection(date(2026, 11, 2), date(2026, 11, 2)))
    manual.is_event_canceled = True
    manual.save()

    response = admin_client.post(
        reverse("panel_event_cancellations_delete"), {"scope": "all", "confirm_all": "yes"}
    )

    assert response.json() == {"deleted": 2, "events_restored": 1}
    assert not EventCancel.objects.exists()
    first.refresh_from_db()
    assert first.is_event_canceled is False
    assert first.event_cancel is None
    for event in (second, manual):
        event.refresh_from_db()
        assert event.is_event_canceled is True
        assert event.event_cancel is None


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"left_date": "bad"},
        {"left_date": "2026-02-30"},
        {"left_date": "2026-11-03", "right_date": "2026-11-02"},
        {"left_date": "2026-01-01", "right_date": "2027-01-02"},
        {"left_date": "2026-11-02", "departments": "999999"},
        {"left_date": "2026-11-02", "departments": "invalid"},
    ],
)
def test_invalid_selection_never_creates_cancellations(
    admin_client: Client, data: dict[str, str]
) -> None:
    response = admin_client.post(reverse("panel_event_cancellations"), data)
    assert response.status_code == 400
    assert not EventCancel.objects.exists()


@pytest.mark.parametrize("data", [{}, {"scope": "all"}, {"scope": "range"}, {"scope": "invalid"}])
def test_delete_requires_explicit_scope_and_confirmation(
    admin_client: Client, data: dict[str, str]
) -> None:
    response = admin_client.post(reverse("panel_event_cancellations_delete"), data)
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("endpoint", "method"),
    [
        ("panel_event_cancellations", "get"),
        ("panel_event_cancellations", "post"),
        ("panel_event_cancellations_delete", "post"),
    ],
)
@pytest.mark.parametrize("user_kind", ["anonymous", "nonstaff", "inactive"])
def test_endpoints_require_active_staff(
    client: Client, endpoint: str, method: str, user_kind: str
) -> None:
    if user_kind != "anonymous":
        user = User.objects.create_user(
            username="example", is_staff=user_kind == "inactive", is_active=user_kind != "inactive"
        )
        client.force_login(user)
    response = getattr(client, method)(reverse(endpoint))
    assert response.status_code == 302
    assert "/admin/login/" in response.url


@pytest.mark.parametrize(
    "endpoint", ["panel_event_cancellations", "panel_event_cancellations_delete"]
)
def test_mutations_require_csrf(admin_user: User, endpoint: str) -> None:
    client = Client(enforce_csrf_checks=True)
    client.force_login(admin_user)
    response = client.post(
        reverse(endpoint), {"scope": "all", "confirm_all": "yes", "left_date": "2026-11-02"}
    )
    assert response.status_code == 403


def test_staff_can_create_with_valid_csrf_and_export_reflects_cancellation(
    admin_user: User, sample_events: tuple[Event, Event, Event]
) -> None:
    client = Client(enforce_csrf_checks=True)
    client.force_login(admin_user)
    page = client.get(reverse("monitoring_panel"))
    assert page.status_code == 200
    response = client.post(
        reverse("panel_event_cancellations"),
        {"left_date": "2026-11-02"},
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )
    assert response.status_code == 200
    assert response.json()["created"] == 2
    exported = client.get(reverse("api:export"), {"date": "single_date", "left_date": "2026-11-02"})
    assert exported.status_code == 200
    assert len(exported.json()["events"]) == 2
    assert all(event["is_canceled"] for event in exported.json()["events"])


def test_delete_get_cannot_change_data(admin_client: Client) -> None:
    response = admin_client.get(reverse("panel_event_cancellations_delete"))
    assert response.status_code == 405


@pytest.mark.parametrize("page", ["monitoring_panel", "panel_actions"])
def test_cancellation_dialog_is_available_on_both_panels(admin_client: Client, page: str) -> None:
    response = admin_client.get(reverse(page))
    assert response.status_code == 200
    assert 'id="cancellationDialog"' in response.content.decode()
    assert "data-open-cancellations" in response.content.decode()


def test_preview_limits_rows_but_reports_total(
    admin_client: Client, sample_events: tuple[Event, Event, Event]
) -> None:
    create_cancellations(CancellationSelection(date(2026, 1, 1), date(2026, 12, 31)))
    response = admin_client.get(
        reverse("panel_event_cancellations"),
        {"left_date": "2026-01-01", "right_date": "2026-12-31"},
    )
    assert response.json()["count"] == 730
    assert len(response.json()["cancellations"]) == 200

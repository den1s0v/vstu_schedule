import base64
import csv
import io
from datetime import date, time
from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse
from icalendar import Calendar, vRecur

from apps.api.models import ApiClient
from apps.common.models import (
    AbstractDay,
    AbstractEvent,
    DayDateOverride,
    Department,
    Event,
    EventKind,
    EventParticipant,
    EventPlace,
    Organization,
    Schedule,
    ScheduleMetadata,
    ScheduleTemplate,
    ScheduleTemplateMetadata,
    Subject,
    TimeSlot,
)


@pytest.mark.django_db
def test_reference_endpoint_returns_public_contract(client):
    _create_event()

    response = client.get(reverse("api:reference"))

    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert set(payload) == {"groups", "teachers", "disciplines", "places"}
    assert payload["groups"][0]["name"] == "TEST-101"
    assert payload["disciplines"][0]["name"] == "Test discipline"


@pytest.mark.django_db
def test_export_json_returns_visualization_query(client):
    _create_event()

    response = client.get(reverse("api:export"), {"date": "single_date", "left_date": "2026-02-02"})

    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["count"] == 1
    assert payload["filters"] == {
        "date": "single_date",
        "left_date": "2026-02-02",
        "right_date": "",
        "group": [],
        "teacher": [],
        "place": [],
        "subject": [],
        "kind": [],
        "time_slot": [],
    }
    assert payload["events"][0]["subject"]["name"] == "Test discipline"


@pytest.mark.django_db
def test_export_without_date_params_returns_abstract_schedule(client):
    _create_event()

    response = client.get(reverse("api:export"), {"group": "TEST-101"})

    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["mode"] == "schedule"
    assert payload["filters"] == {
        "group": ["TEST-101"],
        "teacher": [],
        "place": [],
        "subject": [],
        "kind": [],
        "time_slot": [],
    }
    assert payload["schedule_event_count"] == 1
    assert payload["exception_count"] == 0
    assert "series" not in payload
    schedule_event = payload["schedule_events"][0]
    assert schedule_event["subject"]["name"] == "Test discipline"
    assert schedule_event["abstract_day"] == {
        "id": schedule_event["abstract_day"]["id"],
        "name": "Monday",
        "day_number": 0,
    }
    assert schedule_event["recurrence"] == {
        "kind": "recurring",
        "first_date": "2026-02-01",
        "last_date": "2026-05-31",
        "interval_days": 7,
        "occurrence_count": 18,
    }
    assert schedule_event["exceptions"] == []


@pytest.mark.django_db
def test_export_schedule_csv_uses_schedule_event_rows(client):
    _create_event()

    response = client.get(reverse("api:export"), {"format": "csv"})

    assert response.status_code == HTTPStatus.OK
    content = response.content.decode("utf-8-sig")
    assert content.splitlines()[0].startswith("record_type,schedule_event_id,event_id")
    assert "schedule_event" in content
    assert "Test discipline" in content


@pytest.mark.django_db
def test_export_schedule_ics_uses_recurring_event(client):
    event = _create_event()

    response = client.get(reverse("api:export"), {"format": "ics"})

    assert response.status_code == HTTPStatus.OK
    content = response.content.decode()
    assert f"UID:schedule-event-{event.abstract_event.pk}@vstu-schedule" in content
    assert "RRULE:FREQ=DAILY;COUNT=18;INTERVAL=7" in content
    assert "DTSTART;TZID=Europe/Volgograd:20260201T083000" in content


@pytest.mark.django_db
@pytest.mark.parametrize("format_name", ["json", "csv", "ics"])
@pytest.mark.parametrize(
    ("starting_day", "event_day", "expected_first"),
    [
        (1, 4, date(2026, 9, 4)),
        (1, 0, date(2026, 9, 14)),
        (1, 11, date(2026, 9, 11)),
        (8, 4, date(2026, 9, 11)),
        (8, 11, date(2026, 9, 4)),
        (13, 0, date(2026, 9, 2)),
        (0, 4, date(2026, 9, 5)),
    ],
)
def test_export_recurrence_matches_dated_events(
    client: Client, format_name: str, starting_day: int, event_day: int, expected_first: date
) -> None:
    event = _create_event()
    abstract_event = event.abstract_event
    assert abstract_event is not None
    schedule = abstract_event.schedule
    assert schedule is not None
    template = schedule.schedule_template
    assert template is not None
    template.repetition_period = 14
    template.save()
    abstract_event.abstract_day = AbstractDay.objects.create(
        day_number=event_day, name=f"Cycle day {event_day}"
    )
    abstract_event.save()
    schedule.start_date = date(2026, 9, 1)
    schedule.end_date = date(2026, 9, 30)
    schedule.starting_day_number = AbstractDay.objects.create(
        day_number=starting_day, name=f"Starting day {starting_day}"
    )
    schedule.save()

    dated_response = client.get(
        reverse("api:export"),
        {"date": "range_date", "left_date": "2026-09-01", "right_date": "2026-09-30"},
    )
    assert dated_response.status_code == HTTPStatus.OK
    dates = sorted(item["date"] for item in dated_response.json()["events"])
    assert dates[0] == expected_first.isoformat()

    response = client.get(reverse("api:export"), {"format": format_name})
    assert response.status_code == HTTPStatus.OK
    if format_name == "json":
        recurrence = response.json()["schedule_events"][0]["recurrence"]
        assert recurrence["first_date"] == dates[0]
        assert recurrence["last_date"] == dates[-1]
        assert recurrence["occurrence_count"] == len(dates)
    elif format_name == "csv":
        row = next(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        assert row["first_date"] == dates[0]
        assert row["last_date"] == dates[-1]
        assert int(row["occurrence_count"]) == len(dates)
    else:
        calendar_event = Calendar.from_ical(response.content).walk("VEVENT")[0]
        assert calendar_event.decoded("dtstart").date() == expected_first
        recurrence_rule = calendar_event["rrule"]
        assert isinstance(recurrence_rule, vRecur)
        assert recurrence_rule["COUNT"] == [len(dates)]


@pytest.mark.django_db
def test_export_schedule_includes_full_moved_exception(client):
    event = _create_event()
    event.date = date(2026, 2, 1)
    event.save()
    date_override = DayDateOverride.objects.create(
        day_source=date(2026, 2, 1),
        day_destination=date(2026, 2, 3),
        department=event.department,
    )
    event.refresh_from_db()
    assert event.date_override == date_override

    response = client.get(reverse("api:export"))

    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["exception_count"] == 1
    exception = payload["schedule_events"][0]["exceptions"][0]
    assert exception["event_id"] == event.pk
    assert exception["original_date"] == "2026-02-01"
    assert exception["date"] == "2026-02-03"
    assert exception["subject"]["name"] == "Test discipline"
    assert exception["groups"][0]["name"] == "TEST-101"
    assert exception["places"][0]["display_name"] == "B 101"
    assert exception["is_moved"] is True
    assert exception["is_modified"] is False


@pytest.mark.django_db
def test_export_schedule_ics_uses_recurrence_id_for_moved_exception(client):
    event = _create_event()
    event.date = date(2026, 2, 1)
    event.save()
    DayDateOverride.objects.create(
        day_source=date(2026, 2, 1),
        day_destination=date(2026, 2, 3),
        department=event.department,
    )

    response = client.get(reverse("api:export"), {"format": "ics"})

    content = response.content.decode()
    assert content.count(f"UID:schedule-event-{event.abstract_event.pk}@vstu-schedule") == 2
    assert "RECURRENCE-ID;TZID=Europe/Volgograd:20260201T083000" in content
    assert "DTSTART;TZID=Europe/Volgograd:20260203T083000" in content


@pytest.mark.django_db
def test_export_schedule_ignores_stale_overridden_flag(client):
    event = _create_event()
    Event.objects.filter(pk=event.pk).update(is_event_overriden=True)

    response = client.get(reverse("api:export"))

    assert response.status_code == HTTPStatus.OK
    assert response.json()["exception_count"] == 0
    assert response.json()["schedule_events"][0]["exceptions"] == []


@pytest.mark.django_db
def test_export_schedule_detects_actual_change_without_overridden_flag(client):
    event = _create_event()
    changed_subject = Subject.objects.create(name="Changed discipline")
    Event.objects.filter(pk=event.pk).update(
        subject_override=changed_subject,
        is_event_overriden=False,
    )

    response = client.get(reverse("api:export"))

    assert response.status_code == HTTPStatus.OK
    assert response.json()["exception_count"] == 1
    exception = response.json()["schedule_events"][0]["exceptions"][0]
    assert exception["subject"]["name"] == "Changed discipline"
    assert exception["is_modified"] is True


@pytest.mark.django_db
@pytest.mark.parametrize("relation", ["participants_override", "places_override"])
def test_export_schedule_detects_actual_relation_change(client, relation):
    event = _create_event()
    getattr(event, relation).clear()
    Event.objects.filter(pk=event.pk).update(is_event_overriden=False)

    response = client.get(reverse("api:export"))

    assert response.status_code == HTTPStatus.OK
    assert response.json()["exception_count"] == 1
    exception = response.json()["schedule_events"][0]["exceptions"][0]
    assert exception["is_modified"] is True


@pytest.mark.django_db
def test_export_schedule_filters_base_places(client):
    _create_event()

    matching = client.get(reverse("api:export"), {"place": "B 101"})
    missing = client.get(reverse("api:export"), {"place": "X 999"})

    assert matching.status_code == HTTPStatus.OK
    assert matching.json()["schedule_event_count"] == 1
    assert missing.status_code == HTTPStatus.OK
    assert missing.json()["schedule_event_count"] == 0


@pytest.mark.django_db
def test_export_schedule_excludes_inactive_schedules(client):
    event = _create_event()
    Schedule.objects.filter(pk=event.abstract_event.schedule_id).update(
        status=Schedule.Status.ARCHIVE
    )

    response = client.get(reverse("api:export"))

    assert response.status_code == HTTPStatus.OK
    assert response.json()["schedule_event_count"] == 0


@pytest.mark.django_db
def test_export_schedule_rejects_invalid_repetition_period(client):
    event = _create_event()
    ScheduleTemplate.objects.filter(pk=event.abstract_event.schedule.schedule_template_id).update(
        repetition_period=0
    )

    response = client.get(reverse("api:export"))

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "invalid repetition period" in response.json()["detail"][0]["msg"]


@pytest.mark.django_db
def test_export_schedule_enforces_combined_record_limit(client, monkeypatch):
    _create_event()
    monkeypatch.setattr("apps.api.controllers.CLIENT_MAX_FILTERED_EVENTS", 0)

    response = client.get(reverse("api:export"))

    assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE


@pytest.mark.django_db
def test_export_schedule_uses_single_recurrence_for_holds_on_date(client):
    event = _create_event()
    abstract_event = event.abstract_event
    abstract_event.holds_on_date = date(2026, 3, 10)
    AbstractEvent.objects.filter(pk=abstract_event.pk).update(
        holds_on_date=abstract_event.holds_on_date
    )

    response = client.get(reverse("api:export"))

    recurrence = response.json()["schedule_events"][0]["recurrence"]
    assert recurrence == {
        "kind": "single",
        "first_date": "2026-03-10",
        "last_date": "2026-03-10",
        "interval_days": None,
        "occurrence_count": 1,
    }


@pytest.mark.django_db
def test_export_schedule_ics_marks_canceled_occurrence(client):
    event = _create_event()
    event.date = date(2026, 2, 1)
    event.is_event_canceled = True
    event.save()

    response = client.get(reverse("api:export"), {"format": "ics"})

    content = response.content.decode()
    assert "RECURRENCE-ID;TZID=Europe/Volgograd:20260201T083000" in content
    assert "STATUS:CANCELLED" in content


@pytest.mark.django_db
def test_export_csv(client):
    _create_event()

    response = client.get(
        reverse("api:export"),
        {"date": "single_date", "left_date": "2026-02-02", "format": "csv"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response["Content-Type"].startswith("text/csv")
    assert "Content-Disposition" not in response
    assert response["X-Export-Filename"] == _encoded_filename("schedule_2026-02-02.csv")
    assert "Test discipline" in response.content.decode("utf-8-sig")


@pytest.mark.django_db
def test_export_filename_includes_selected_reference_filters(client):
    _create_event()

    response = client.get(
        reverse("api:export"),
        {
            "date": "single_date",
            "left_date": "2026-02-02",
            "group": "TEST-101",
            "teacher": "Teacher Example",
            "place": "B 101",
            "format": "json",
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert response["X-Export-Filename"] == _encoded_filename(
        "schedule_groups_TEST-101_teachers_Teacher-Example_rooms_B-101_2026-02-02.json"
    )


@pytest.mark.django_db
def test_export_filename_prefers_selected_reference_filters(client):
    _create_event()

    response = client.get(
        reverse("api:export"),
        {"group": "TEST-101", "format": "json"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response["X-Export-Filename"] == _encoded_filename("schedule_groups_TEST-101.json")


@pytest.mark.django_db
def test_export_filename_header_encodes_cyrillic_filters(client):
    _create_event()

    response = client.get(
        reverse("api:export"),
        {"group": "ГРУППА-101", "teacher": "Иванов Иван", "format": "json"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response["X-Export-Filename"] == _encoded_filename(
        "schedule_groups_ГРУППА-101_teachers_Иванов-Иван.json"
    )


@pytest.mark.django_db
def test_export_works_with_browser_accept_header(client):
    _create_event()

    response = client.get(
        reverse("api:export"),
        {"date": "single_date", "left_date": "2026-02-02", "format": "json"},
        HTTP_ACCEPT="text/html,application/xhtml+xml",
    )

    assert response.status_code == HTTPStatus.OK
    assert response["Content-Type"].startswith("application/json")


@pytest.mark.django_db
def test_model_endpoint_requires_auth(client: Client) -> None:
    response = client.get(reverse("api:event"))

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response["WWW-Authenticate"] == "Bearer"


@pytest.mark.django_db
def test_token_allows_model_endpoint(client):
    _create_event()
    api_client, secret = ApiClient.create_with_secret(name="Test client")

    token_response = client.post(
        reverse("api:token"),
        data={"client_id": api_client.client_id, "client_secret": secret},
        content_type="application/json",
    )

    assert token_response.status_code == HTTPStatus.OK
    token = token_response.json()["access_token"]
    response = client.get(
        reverse("api:event"),
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()[0]["fields"]["subject_override_id"] is not None


@pytest.mark.django_db
def test_swagger_requires_staff_login(client):
    response = client.get(reverse("api:docs"))

    assert response.status_code == HTTPStatus.FOUND


def _create_event() -> Event:
    org = Organization.objects.create(name="Test university")
    department = Department.objects.create(
        name="Test department",
        shortname="TD",
        code="TD",
        organization=org,
    )
    template_metadata = ScheduleTemplateMetadata.objects.create(
        faculty="TD",
        scope=ScheduleTemplateMetadata.Scope.BACHELOR,
    )
    template = ScheduleTemplate.objects.create(
        metadata=template_metadata,
        repetition_period=7,
        repeatable=True,
        aligned_by_week_day=1,
        department=department,
    )
    metadata = ScheduleMetadata.objects.create(years="2025-2026", course=1, semester=2)
    day = AbstractDay.objects.create(day_number=0, name="Monday")
    schedule = Schedule.objects.create(
        metadata=metadata,
        status=Schedule.Status.ACTIVE,
        start_date=date(2026, 2, 1),
        end_date=date(2026, 6, 1),
        starting_day_number=day,
        schedule_template=template,
    )
    kind = EventKind.objects.create(name="Lecture")
    subject = Subject.objects.create(name="Test discipline")
    time_slot = TimeSlot.objects.create(
        alt_name="1-2",
        start_time=time(8, 30),
        end_time=time(10, 0),
    )
    group = EventParticipant.objects.create(
        name="TEST-101",
        role=EventParticipant.Role.STUDENT,
        is_group=True,
        department=department,
    )
    teacher = EventParticipant.objects.create(
        name="Teacher Example",
        role=EventParticipant.Role.TEACHER,
        is_group=False,
        department=department,
    )
    place = EventPlace.objects.create(building="B", room="101")
    abstract_event = AbstractEvent.objects.create(
        kind=kind,
        subject=subject,
        abstract_day=day,
        time_slot=time_slot,
        schedule=schedule,
    )
    abstract_event.participants.set([group, teacher])
    abstract_event.places.set([place])
    event = Event.objects.create(
        date=date(2026, 2, 2),
        kind_override=kind,
        subject_override=subject,
        time_slot_override=time_slot,
        abstract_event=abstract_event,
    )
    event.participants_override.set([group, teacher])
    event.places_override.set([place])
    return event


def _encoded_filename(filename: str) -> str:
    return base64.b64encode(filename.encode("utf-8")).decode("ascii")

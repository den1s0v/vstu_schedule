from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from django.db.models import Prefetch, QuerySet
from django.http import QueryDict

from apps.api.schemas import (
    ApiAbstractDay,
    ApiScheduleEvent,
    ApiScheduleException,
    ApiScheduleRecurrence,
)
from apps.api.services.serialization import (
    serialize_kind,
    serialize_participants,
    serialize_places,
    serialize_schedule,
    serialize_subject,
    serialize_time_slot,
)
from apps.common.models import AbstractEvent, Event, EventParticipant, Schedule
from apps.common.services.timetable.read.filters import (
    PlaceFilter,
    TimeSlotFilter,
    _prefix_filter_query,
)

SCHEDULE_FILTER_NAMES = ("group", "teacher", "place", "subject", "kind", "time_slot")


def schedule_filters_from_query(query: Mapping[str, Any]) -> dict[str, list[str]]:
    return {name: _get_list(query, name) for name in SCHEDULE_FILTER_NAMES}


def get_schedule_events_for_query(query: Mapping[str, Any]) -> QuerySet[AbstractEvent]:
    filters = schedule_filters_from_query(query)
    schedule_events = AbstractEvent.objects.filter(schedule__status=Schedule.Status.ACTIVE)

    if filters["group"]:
        schedule_events = schedule_events.filter(
            participants__name__in=filters["group"], participants__is_group=True
        )
    if filters["teacher"]:
        schedule_events = schedule_events.filter(
            participants__name__in=filters["teacher"],
            participants__role__in=(
                EventParticipant.Role.TEACHER,
                EventParticipant.Role.ASSISTANT,
            ),
        )
    if filters["place"]:
        schedule_events = schedule_events.filter(
            _prefix_filter_query(PlaceFilter.by_building_and_room(filters["place"]), "places__")
        )
    if filters["subject"]:
        schedule_events = schedule_events.filter(subject__name__in=filters["subject"])
    if filters["kind"]:
        schedule_events = schedule_events.filter(kind__name__in=filters["kind"])
    if filters["time_slot"]:
        schedule_events = schedule_events.filter(
            **TimeSlotFilter.from_display_name_abstract_event_relative(filters["time_slot"])
        )

    related_events = Event.objects.select_related(
        "date_override",
        "subject_override",
        "kind_override",
        "time_slot_override",
    ).prefetch_related(
        "participants_override",
        "participants_override__department",
        "places_override",
    )
    return (
        schedule_events.select_related(
            "abstract_day",
            "kind",
            "subject",
            "time_slot",
            "schedule",
            "schedule__metadata",
            "schedule__starting_day_number",
            "schedule__schedule_template",
            "schedule__schedule_template__metadata",
            "schedule__schedule_template__department",
        )
        .prefetch_related(
            "participants",
            "participants__department",
            "places",
            Prefetch("event_set", queryset=related_events, to_attr="export_related_events"),
        )
        .distinct()
    )


def build_schedule_events(abstract_events: list[AbstractEvent]) -> list[ApiScheduleEvent]:
    result = []
    for abstract_event in abstract_events:
        recurrence = _build_recurrence(abstract_event)
        if recurrence is None:
            continue
        participants = list(abstract_event.participants.all())
        result.append(
            ApiScheduleEvent(
                id=abstract_event.pk,
                abstract_day=ApiAbstractDay(
                    id=abstract_event.abstract_day.pk,
                    name=abstract_event.abstract_day.name,
                    day_number=abstract_event.abstract_day.day_number,
                ),
                subject=serialize_subject(abstract_event.subject),
                kind=serialize_kind(abstract_event.kind) if abstract_event.kind else None,
                time_slot=serialize_time_slot(abstract_event.time_slot),
                groups=serialize_participants(
                    [participant for participant in participants if participant.is_group]
                ),
                teachers=serialize_participants(
                    [
                        participant
                        for participant in participants
                        if participant.role
                        in (EventParticipant.Role.TEACHER, EventParticipant.Role.ASSISTANT)
                    ]
                ),
                places=serialize_places(list(abstract_event.places.all())),
                schedule=serialize_schedule(abstract_event.schedule)
                if abstract_event.schedule
                else None,
                recurrence=recurrence,
                exceptions=_build_exceptions(abstract_event),
            )
        )
    return result


def schedule_export_record_count(schedule_events: list[ApiScheduleEvent]) -> int:
    return len(schedule_events) + sum(len(item.exceptions) for item in schedule_events)


def _build_recurrence(abstract_event: AbstractEvent) -> ApiScheduleRecurrence | None:
    if abstract_event.holds_on_date is not None:
        return ApiScheduleRecurrence(
            kind="single",
            first_date=abstract_event.holds_on_date,
            last_date=abstract_event.holds_on_date,
            interval_days=None,
            occurrence_count=1,
        )

    schedule = abstract_event.schedule
    if (
        schedule is None
        or schedule.start_date is None
        or schedule.end_date is None
        or schedule.starting_day_number is None
        or schedule.schedule_template is None
    ):
        raise ValueError(
            f"Active schedule event {abstract_event.pk} has incomplete recurrence data."
        )
    if schedule.end_date < schedule.start_date:
        raise ValueError(f"Active schedule event {abstract_event.pk} has invalid date boundaries.")

    interval = schedule.schedule_template.repetition_period
    if interval <= 0:
        raise ValueError(
            f"Active schedule event {abstract_event.pk} has invalid repetition period."
        )

    day_offset = abstract_event.abstract_day.day_number - schedule.starting_day_number.day_number
    first_date = schedule.start_date + timedelta(days=day_offset)
    while first_date < schedule.start_date:
        first_date += timedelta(days=interval)
    if first_date > schedule.end_date:
        return None

    if not schedule.schedule_template.repeatable:
        return ApiScheduleRecurrence(
            kind="single",
            first_date=first_date,
            last_date=first_date,
            interval_days=None,
            occurrence_count=1,
        )

    occurrence_count = ((schedule.end_date - first_date).days // interval) + 1
    last_date = first_date + timedelta(days=(occurrence_count - 1) * interval)
    return ApiScheduleRecurrence(
        kind="recurring",
        first_date=first_date,
        last_date=last_date,
        interval_days=interval,
        occurrence_count=occurrence_count,
    )


def _build_exceptions(abstract_event: AbstractEvent) -> list[ApiScheduleException]:
    exceptions = []
    for event in getattr(abstract_event, "export_related_events", []):
        is_modified = _event_differs_from_abstract(event, abstract_event)
        if event.is_event_canceled or event.date_override is not None or is_modified:
            exceptions.append(_serialize_exception(event, is_modified=is_modified))
    return exceptions


def _event_differs_from_abstract(event: Event, abstract_event: AbstractEvent) -> bool:
    if (
        event.subject_override != abstract_event.subject
        or event.kind_override != abstract_event.kind
        or event.time_slot_override != abstract_event.time_slot
    ):
        return True

    event_participant_ids = {participant.pk for participant in event.participants_override.all()}
    abstract_participant_ids = {participant.pk for participant in abstract_event.participants.all()}
    if event_participant_ids != abstract_participant_ids:
        return True

    event_place_ids = {place.pk for place in event.places_override.all()}
    abstract_place_ids = {place.pk for place in abstract_event.places.all()}
    return event_place_ids != abstract_place_ids


def _serialize_exception(event: Event, *, is_modified: bool) -> ApiScheduleException:
    if event.date is None:
        raise ValueError(f"Schedule exception {event.pk} has no date.")
    participants = list(event.participants_override.all())
    original_date: date = (
        event.date_override.day_source if event.date_override is not None else event.date
    )
    return ApiScheduleException(
        event_id=event.pk,
        original_date=original_date,
        date=event.date,
        subject=serialize_subject(event.subject_override) if event.subject_override else None,
        kind=serialize_kind(event.kind_override) if event.kind_override else None,
        time_slot=serialize_time_slot(event.time_slot_override)
        if event.time_slot_override
        else None,
        groups=serialize_participants(
            [participant for participant in participants if participant.is_group]
        ),
        teachers=serialize_participants(
            [
                participant
                for participant in participants
                if participant.role
                in (EventParticipant.Role.TEACHER, EventParticipant.Role.ASSISTANT)
            ]
        ),
        places=serialize_places(list(event.places_override.all())),
        is_canceled=event.is_event_canceled,
        is_moved=event.date_override is not None,
        is_modified=is_modified,
    )


def _get_list(query: Mapping[str, Any], name: str) -> list[str]:
    if isinstance(query, QueryDict):
        values = query.getlist(name) or query.getlist(f"{name}[]")
        return [str(value) for value in values if value]
    value = query.get(name, [])
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)] if value else []

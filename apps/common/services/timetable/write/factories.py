from collections.abc import Iterable
from datetime import date, timedelta

from apps.common.models import (
    AbstractDay,
    AbstractEvent,
    DayDateOverride,
    Event,
    EventCancel,
    EventKind,
    EventParticipant,
    EventPlace,
    Schedule,
    Subject,
    TimeSlot,
)
from apps.common.selectors import Selector
from apps.common.services.timetable.read.filters import DateFilter, EventFilter


def create_event_for_date(date_: str | date, abstract_event: AbstractEvent) -> None:
    """Creates new Event from given AbstractEvent on specified date"""

    if isinstance(date_, str):
        date_ = date.fromisoformat(date_)

    event = Event()

    event.date = date_
    event.kind_override = abstract_event.kind
    event.subject_override = abstract_event.subject
    event.time_slot_override = abstract_event.time_slot
    event.abstract_event = abstract_event
    event.is_event_canceled = False

    event.save()

    event.participants_override.add(*abstract_event.participants.all())
    event.places_override.add(*abstract_event.places.all())


def create_abstract_event(
    kind: EventKind,
    subject: Subject,
    participants: list[EventParticipant],
    places: list[EventPlace],
    abstract_day: AbstractDay,
    time_slot: TimeSlot,
    holds_on_date: date | None,
    schedule: Schedule,
) -> AbstractEvent:
    """Creates new AbstractEvent

    Returns created AbstractEvent
    """

    abstract_event = AbstractEvent()

    abstract_event.kind = kind
    abstract_event.subject = subject
    abstract_event.abstract_day = abstract_day
    abstract_event.time_slot = time_slot
    if holds_on_date:
        abstract_event.holds_on_date = holds_on_date
    abstract_event.schedule = schedule

    abstract_event.save()

    abstract_event.participants.set(participants)
    abstract_event.places.set(places)

    return abstract_event


def fill_semester_by_repeating(abstract_event: AbstractEvent) -> None:
    """Creates Events from given AbstractEvent
    for every semester working day
    using AbstractEvent Schedule parameters

    If AbstractEvent holds on single date
    then only one Event will be created

    Applies date overrides for new Events after creating
    """

    # creates single Event
    # if abstract_event holds only on expected date
    if abstract_event.holds_on_date is not None:
        create_event_for_date(abstract_event.holds_on_date, abstract_event)
    else:
        semester_start_date, semester_end_date, date_, repetition_period = (
            calculate_semester_filling_parameters(abstract_event)
        )

        while date_ <= semester_end_date:  # TODO: check < or <=
            if date_ >= semester_start_date:
                create_event_for_date(date_, abstract_event)

                # creating Event for only first acceptable date
                # if abstract_event is not repeatable
                if not abstract_event.schedule.schedule_template.repeatable:
                    break

            date_ += timedelta(days=repetition_period)

    check_for_day_date_override(abstract_event)


def fill_semester_for_dates(abstract_event: AbstractEvent, dates: list[date]) -> None:
    """Creates Events from given AbstractEvent for every given date

    Always creates Events even if it goes out of bounds the end date of the semester
    """

    # creates single Event
    # if abstract_event holds only on expected date
    if abstract_event.holds_on_date is not None:
        create_event_for_date(abstract_event.holds_on_date, abstract_event)
    else:
        for date_ in dates:
            create_event_for_date(date_, abstract_event)

    check_for_day_date_override(abstract_event)


def apply_day_date_override(
    date_override: DayDateOverride | None, event: Event, call_save_method: bool = True
) -> None:
    """Changes Event date to date from given DayDateOverride

    Use date_override=None to detach Event from date override

    Use call_save_method to save Event after changes
    """

    if date_override:
        event.date = date_override.day_destination
        event.date_override = date_override
    else:
        if event.date_override is None:
            return

        event.date = event.date_override.day_source

    if call_save_method:
        event.save()


def apply_event_cancel(
    event_cancel: EventCancel | None, event: Event, call_save_method: bool = True
) -> None:
    """Applies EventCancel to given Event

    Use event_cancel=None to undo event cancel
    """

    if event_cancel:
        event.is_event_canceled = True
        event.event_cancel = event_cancel
    else:
        event.is_event_canceled = False
        event.event_cancel = None

    if call_save_method:
        event.save()


def rewrite_events(abstract_event: AbstractEvent | Iterable[AbstractEvent]) -> bool:
    """Clears all related Events and
    recreate them again from given AbstractEvent

    Will delete only NOT overriden Events
    """

    # deleting only not overriden events
    filter_query = EventFilter.not_overriden()

    if isinstance(abstract_event, AbstractEvent):
        # deleting Events only for specified AbstractEvent
        filter_query.update({"abstract_event__pk": abstract_event.pk})

        Event.objects.filter(**filter_query).delete()

        # filling semester by Events from abstract_event
        fill_semester_by_repeating(abstract_event)
    # working with list of AbstractEvents
    else:
        abstract_events = list(abstract_event)

        # deleting Events only for specified AbstractEvents
        filter_query.update({"abstract_event__in": abstract_events})

        Event.objects.filter(**filter_query).delete()

        # filling semester by Events from every AbstractEvent
        for ae in abstract_events:
            fill_semester_by_repeating(ae)

    return True


def calculate_semester_filling_parameters(
    abstract_event: AbstractEvent,
) -> tuple[date, date, date, int]:
    """Calculates semester filling parameters for given AbstarctEvent

    Returns semester_start_date, semester_end_date, fill_from_date, repetition_period
    """

    semester_start_date = abstract_event.schedule.start_date

    day_number_difference = (
        abstract_event.abstract_day.day_number
        - abstract_event.schedule.starting_day_number.day_number
    )

    fill_from_date = semester_start_date + timedelta(day_number_difference)

    if day_number_difference < 0:
        fill_from_date += timedelta(abstract_event.schedule.schedule_template.repetition_period)

    return (
        semester_start_date,
        abstract_event.schedule.end_date,
        fill_from_date,
        abstract_event.schedule.schedule_template.repetition_period,
    )


def check_for_day_date_override(abstract_event: AbstractEvent) -> None:
    """Find and apply if exists DayDateOverride
    to Events from given AbstractEvent
    """

    from apps.common.services.timetable.write.factories import apply_day_date_override

    reader = Selector({"department": abstract_event.department})

    # getting all DayDateOverrides for AbstractEvent
    reader.find_models(DayDateOverride)
    date_overrides = reader.get_found_models()

    reader.clear_filter_query()
    reader.add_filter({"abstract_event": abstract_event})

    # applying date overrides to Events
    for ddo in date_overrides:
        reader.add_filter(DateFilter.from_singe_date(ddo.day_source))

        reader.find_models(Event)

        if reader.get_found_models().exists():
            for e in reader.get_found_models():
                apply_day_date_override(ddo, e)

        reader.remove_last_filter()


def refresh_related_events(
    abstract_event: AbstractEvent, update_non_m2m: bool = True, update_m2m: bool = True
) -> None:
    """Renew related Events with values from given AbstractEvent

    Use update_non_m2m to renew NOT many-to-many fields

    Use update_m2m to renew many-to-many fields

    update_non_m2m and update_m2m can be used at the same time

    Saves Event after changes
    """

    if not update_non_m2m and not update_m2m:
        return

    filter_query = {"abstract_event": abstract_event}
    filter_query.update(EventFilter.not_overriden())

    for e in Event.objects.filter(**filter_query):
        if e.is_event_overriden:
            continue

        if update_non_m2m:
            e.kind_override = abstract_event.kind
            e.subject_override = abstract_event.subject
            e.time_slot_override = abstract_event.time_slot

        if update_m2m:
            e.participants_override.clear()
            e.participants_override.add(*abstract_event.participants.all())
            e.places_override.clear()
            e.places_override.add(*abstract_event.places.all())

        e.save()

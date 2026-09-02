from datetime import date

from django.db.models import QuerySet, Count

from apps.common.models import (
    AbstractDay,
    AbstractEvent,
    Department,
    EventKind,
    EventParticipant,
    EventPlace,
    Schedule,
    Subject,
    TimeSlot,
)
from apps.common.services.timetable.read.filters import AbstractEventFilter


# TODO: tests
def create_common_abstract_days() -> bool:
    """Used for fast AbstractDays creating"""

    ABSTRACT_DAYS_DATA = [
        (0, "1 неделя, Понедельник"),
        (1, "1 неделя, Вторник"),
        (2, "1 неделя, Среда"),
        (3, "1 неделя, Четверг"),
        (4, "1 неделя, Пятница"),
        (5, "1 неделя, Суббота"),
        (6, "1 неделя, Воскресенье"),
        (7, "2 неделя, Понедельник"),
        (8, "2 неделя, Вторник"),
        (9, "2 неделя, Среда"),
        (10, "2 неделя, Четверг"),
        (11, "2 неделя, Пятница"),
        (12, "2 неделя, Суббота"),
        (13, "2 неделя, Воскресенье"),
    ]
    abstract_days_to_create = []

    for data in ABSTRACT_DAYS_DATA:
        try:
            AbstractDay.objects.get(day_number=data[0], name=data[1])
        except AbstractDay.DoesNotExist:
            abstract_days_to_create.append(AbstractDay(day_number=data[0], name=data[1]))

    if abstract_days_to_create:
        AbstractDay.objects.bulk_create(abstract_days_to_create)

        return True

    return False


# TODO: tests
def create_common_time_slots() -> bool:
    """Used for fast TimeSlots creating"""

    TIME_SLOTS_DATA = [
        ("1-2", "08:30", "10:00"),
        ("3-4", "10:10", "11:40"),
        ("5-6", "11:50", "13:20"),
        ("7-8", "13:40", "15:10"),
        ("9-10", "15:20", "16:50"),
        ("11-12", "17:00", "18:30"),
        ("13-14", "18:35", "20:00"),
        ("15-16", "20:05", "21:30"),
    ]
    time_slots_to_create = []

    for data in TIME_SLOTS_DATA:
        try:
            TimeSlot.objects.get(alt_name=data[0], start_time=data[1], end_time=data[2])
        except TimeSlot.DoesNotExist:
            time_slots_to_create.append(
                TimeSlot(alt_name=data[0], start_time=data[1], end_time=data[2])
            )

    if time_slots_to_create:
        TimeSlot.objects.bulk_create(time_slots_to_create)

        return True

    return False


def is_abstract_event_already_exists(
    kind: EventKind,
    subject: Subject,
    participants: list[EventParticipant],
    places: list[EventPlace],
    abstract_day: AbstractDay,
    time_slot: TimeSlot,
    date_: date | None,
    schedule: Schedule,
) -> bool:
    """Checks if AbstractEvent by given parameters already exists
    
    AbstractEvent must match in all participants and places
    """

    candidate_events = AbstractEvent.objects.filter(
        kind=kind,
        subject=subject,
        abstract_day=abstract_day,
        time_slot=time_slot,
        holds_on_date=date_,
        schedule=schedule,
    )

    candidate_events = candidate_events.annotate(prt_count=Count("participants")).filter(prt_count=len(participants))
    candidate_events = candidate_events.annotate(plc_count=Count("places")).filter(plc_count=len(places))

    for participant in participants:
        candidate_events = candidate_events.filter(participants=participant)

    for place in places:
            candidate_events = candidate_events.filter(places=place)

    return candidate_events.exists()


def is_place_already_exists(building: str, room: str) -> bool:
    """Checks if EventPlace by given building and room already exists"""

    return EventPlace.objects.filter(building=building, room=room).exists()


def is_subject_already_exists(name: str) -> bool:
    """Checks if Subject by given name already exists"""

    return Subject.objects.filter(name=name).exists()


def is_participant_already_exists(name: str, department: Department | None) -> bool:
    """Checks if EventParticipant by given name and department already exists"""

    return EventParticipant.objects.filter(name=name, department=department).exists()


def is_department_already_exists(name: str, shortname: str, code: str) -> bool:
    """Checks if Department by given parameters already exists"""

    return Department.objects.filter(name=name, shortname=shortname, code=code).exists()


def get_all_teachers() -> QuerySet[EventParticipant]:
    """Returns all existing EventParticipants
    with roles TEACHER and ASSISTANT
    """

    return EventParticipant.objects.filter(
        role__in=[EventParticipant.Role.TEACHER, EventParticipant.Role.ASSISTANT]
    )


def get_all_groups() -> QuerySet[EventParticipant]:
    """Returns all existing EventParticipants
    that counts as group
    """

    return EventParticipant.objects.filter(is_group=True)


def get_all_places() -> QuerySet[EventPlace]:
    """Returns all existing EventPlaces"""

    return EventPlace.objects.all()


def get_all_subjects() -> QuerySet[Subject]:
    """Returns all existing Subjects"""

    return Subject.objects.all()


def get_all_kinds() -> QuerySet[EventKind]:
    """Returns all existing EventKinds"""

    return EventKind.objects.all()


def get_all_time_slots() -> QuerySet[TimeSlot]:
    """Returns all existing TimeSlots"""

    return TimeSlot.objects.all()

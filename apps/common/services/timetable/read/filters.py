import re
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any, cast, overload

from django.db.models import Q

from apps.common.models import (
    AbstractDay,
    Event,
    EventKind,
    EventParticipant,
    EventPlace,
    Schedule,
    Subject,
    TimeSlot,
)
from apps.common.services.timetable.utilities.normalizers import normalize_place_building_and_room

type FilterDict = Mapping[str, Any]
type FilterQuery = FilterDict | Q


def _prefix_filter_query(filter_query: FilterQuery, prefix: str) -> FilterQuery:
    if isinstance(filter_query, Q):
        return _prefix_q(filter_query, prefix)

    return {f"{prefix}{key}": value for key, value in filter_query.items()}


def _prefix_q(q_filter: Q, prefix: str) -> Q:
    prefixed_children = []

    for child in q_filter.children:
        if isinstance(child, Q):
            prefixed_children.append(_prefix_q(child, prefix))
            continue

        key, value = cast(tuple[str, Any], child)
        prefixed_children.append((f"{prefix}{key}", value))

    prefixed_q = Q(*prefixed_children, _connector=q_filter.connector)

    if q_filter.negated:
        prefixed_q.negate()

    return prefixed_q


def prefix_filter_dict(filter_query: dict[str, str], prefix: str) -> dict[str, str]:
    return {f"{prefix}{key}": value for key, value in filter_query.items()}


class DateFilter:
    """Only for work with Event model fields"""

    @staticmethod
    def from_singe_date(date_: str | date) -> dict:
        return {"date": date_}

    @staticmethod
    def today() -> dict:
        return DateFilter.from_singe_date(date.today())

    @staticmethod
    def tomorrow() -> dict:
        return DateFilter.from_singe_date(date.today() + timedelta(days=1))

    @staticmethod
    def from_date(from_date: str | date, to_date: str | date) -> dict:
        if isinstance(from_date, str):
            from_date = date.fromisoformat(from_date)

        if isinstance(to_date, str):
            to_date = date.fromisoformat(to_date)

        return {"date__range": [from_date, to_date]}

    @staticmethod
    def around_date(date_: str | date, left_range: int, right_range: int) -> dict:
        if isinstance(date_, str):
            date_ = date.fromisoformat(date_)

        left_date = date_ - timedelta(days=left_range)
        right_date = date_ + timedelta(days=right_range)

        return {"date__range": [left_date, right_date]}

    @staticmethod
    def take_whole_week(date_) -> dict:
        return DateFilter.around_date(date_, date_.weekday(), 6 - date_.weekday())

    @staticmethod
    def this_week() -> dict:
        return DateFilter.take_whole_week(date.today())

    @staticmethod
    def next_week() -> dict:
        return DateFilter.take_whole_week(date.today() + timedelta(weeks=1))


class ParticipantFilter:
    @staticmethod
    def by_name(name: str | list[str]) -> dict:
        """Only for work with Event model fields

        Use list of participant names for OR behaviour
        """

        if type(name) is list:
            return {"participants_override__name__in": name}

        return {"participants_override__name": name}

    @staticmethod
    def by_role(role: str | list[str]) -> dict:
        """Only for work with Event model fields

        Use list of participant roles for OR behaviour
        """

        if type(role) is list:
            return {"participants_override__role__in": role}

        return {"participants_override__role": role}


class PlaceFilter:
    @classmethod
    def by_building_and_room_event_relative(cls, building_and_room: str | list[str]):
        """Only for work with Event model fields

        Use list of places for OR behaviour

        building_and_room must be in format: "{building} {room}" (separated by space)
        """

        return _prefix_filter_query(
            cls.by_building_and_room(building_and_room),
            "places_override__",
        )

    @classmethod
    @overload
    def by_building_and_room(cls, building_and_room: str) -> dict[str, Any]: ...

    @classmethod
    @overload
    def by_building_and_room(cls, building_and_room: list[str]) -> Q: ...

    @classmethod
    def by_building_and_room(cls, building_and_room: str | list[str]) -> FilterQuery:
        """

        Use list of places for OR behaviour

        building_and_room must be in format: "{building} {room}" (separated by space)
        """

        if isinstance(building_and_room, list):
            filter_ = Q()

            for r in building_and_room:
                filter_ |= Q(**cls._by_single_building_and_room(r))

            return filter_

        return cls._by_single_building_and_room(building_and_room)

    @classmethod
    def _by_single_building_and_room(cls, building_and_room: str) -> dict[str, Any]:
        normalized_place = normalize_place_building_and_room(building_and_room)

        if normalized_place is None:
            return {}

        building, room = normalized_place

        filter_ = cls.by_building(building)
        filter_.update(cls.by_room(room))

        return filter_

    @classmethod
    def by_repr(cls, building_and_room: str | list[str]) -> FilterQuery:
        return cls.by_building_and_room(building_and_room)

    @staticmethod
    def by_building(building: str | list[str]) -> dict:
        """

        Use list of place buildings for OR behaviour
        """

        if type(building) is list:
            return {"building__in": building}

        return {"building": building}

    @staticmethod
    def by_room(room: str | list[str]) -> dict:
        """

        Use list of place rooms for OR behaviour
        """

        if type(room) is list:
            return {"room__in": room}

        return {"room": room}


class SubjectFilter:
    """Only for work with Event model fields"""

    @staticmethod
    def by_name(name: str | list[str]):
        """

        Use list of subject names for OR behaviour
        """

        if type(name) is list:
            return {"subject_override__name__in": name}

        return {"subject_override__name": name}


class TimeSlotFilter:
    @classmethod
    def from_display_name_event_relative(cls, display_name: str | list[str]) -> dict[str, str]:
        """Only for work with Event model TimeSlot field

        Use list of time slot display_names for OR behaviour
        """

        filter_query = cls.from_display_name(display_name)

        return prefix_filter_dict(filter_query, "time_slot_override__") if filter_query else {}

    @classmethod
    def from_display_name_abstract_event_relative(
        cls, display_name: str | list[str]
    ) -> dict[str, str]:
        """Only for work with AbstractEvent model TimeSlot field

        Use list of time slot display_names for OR behaviour
        """

        filter_query = cls.from_display_name(display_name)

        return prefix_filter_dict(filter_query, "time_slot__") if filter_query else {}

    @classmethod
    def from_display_name(cls, display_name: str | list[str]) -> dict | None:
        """Gives filter query for TimeSlot by it start_time (firstly) OR alt_name (secondly)

        Correctly works with string in next formats:
            \\d-\\d for alt name
            HH:MM for start time
            HH:MM HH:MM for start and end times

        Use list of time slot display_names for OR behaviour

        Returns filter query for only one of start_time string OR alt_name string (!)

        Returns None when cannot create filter query from given string
        """

        ## TODO: remove _
        # making query from start time should be first
        # to prevent problem in some situations
        # e.g. 8:30-10.00
        filter_query_from_start_times, _ = cls.by_start_time(display_name)

        if filter_query_from_start_times:
            return filter_query_from_start_times

        ## TODO: remove _
        filter_query_from_alt_names, _ = cls.by_alt_name(display_name)

        if filter_query_from_alt_names:
            return filter_query_from_alt_names

        return None

    @classmethod
    def by_repr_event_relative(cls, display_name: str | list[str]) -> FilterQuery:
        return cls.from_display_name_event_relative(display_name)

    @classmethod
    def by_repr_abstract_event_relative(cls, display_name: str | list[str]) -> FilterQuery:
        return cls.from_display_name_abstract_event_relative(display_name)

    @classmethod
    def by_repr(cls, display_name: str | list[str]) -> dict | None:
        return cls.from_display_name(display_name)

    @staticmethod
    def by_start_time(start_time: str | list[str]) -> tuple[dict, list]:
        """Makes filter query for TimeSlot using it start_time.
        start_time must be in format: HH:MM (only colon separator acceptable)

        Use list of time slots start_time for OR behaviour

        Method can handle start_time combined with end_time ("8:30 10:00"). Result will be the same

        Returns a dict of filter queries and list of strings, that cannot be used for filtering by start_time
        """

        # 9:00
        # 13:01
        START_TIME_REG_EX = r"\d{1,2}\:{1}\d{2}"

        matches = []

        start_time_list: list[str] = (
            list(start_time) if isinstance(start_time, list) else [start_time]
        )

        for time in list(start_time_list):
            match_ = re.search(START_TIME_REG_EX, time)

            if match_:
                matches.append(match_[0])
                start_time_list.remove(time)

        if matches:
            if len(matches) == 1:
                return {"start_time__contains": matches[0]}, start_time_list

            return {"start_time__in": matches}, start_time_list

        return {}, start_time_list

    @staticmethod
    def by_alt_name(alt_name: str | list[str]) -> tuple[dict, list]:
        """Makes filter query for TimeSlot using it alt_name

        Use list of time slots alt_names for OR behaviour

        Returns a dict of filter queries and list of strings, that cannot be used for filtering by alt_name
        """

        # 11-12
        # 10-15
        # 0-0
        # 9-8
        ALT_NAME_REG_EX = r"\d{1,2}\-+\d{1,2}"

        matches = []

        alt_names_list: list[str] = list(alt_name) if isinstance(alt_name, list) else [alt_name]

        for name in list(alt_names_list):
            match_ = re.search(ALT_NAME_REG_EX, name)

            if match_:
                matches.append(match_[0])
                alt_names_list.remove(name)

        if matches:
            if len(matches) == 1:
                return {"alt_name": matches[0]}, alt_names_list

            return {"alt_name__in": matches}, alt_names_list

        return {}, alt_names_list


class KindFilter:
    """Only for work with Event model fields"""

    @staticmethod
    def by_name(name: str | list[str]) -> dict:
        """

        Use list of subject names for OR behaviour
        """

        if type(name) is list:
            return {"kind_override__name__in": name}

        return {"kind_override__name": name}


class EventFilter:
    """Only for work with Event model fields"""

    @staticmethod
    def overriden() -> dict:
        return {"is_event_overriden": True}

    @staticmethod
    def not_overriden() -> dict:
        return {"is_event_overriden": False}

    @staticmethod
    def by_schedule(schedule) -> dict:
        return {"abstract_event__schedule": schedule}

    @staticmethod
    def by_department(department) -> dict:
        return {"abstract_event__schedule__schedule_template__department": department}


class AbstractEventFilter:
    """Only for work with AbstractEvent model fields"""

    @staticmethod
    def with_existing_events() -> dict:
        return {
            "pk__in": cast(Any, Event)
            .objects.values_list("abstract_event__pk", flat=True)
            .distinct()
        }


class ScheduleFilter:
    """Only for work with Event model fields"""

    @staticmethod
    def is_active() -> dict:
        return {"abstract_event__schedule__status": Schedule.Status.ACTIVE}

import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, cast

from django.db.models import Q

from apps.common.models import (
    AbstractDay,
    Department,
    EventKind,
    EventParticipant,
    EventPlace,
    Schedule,
    Subject,
    TimeSlot,
)
from apps.common.selectors import Selector
from apps.common.services.timetable.load.resolution import (
    EntityResolver,
    EntityType,
    ResolutionReport,
    ResolvedHit,
)
from apps.common.services.timetable.read.filters import TimeSlotFilter
from apps.common.services.timetable.utilities import (
    get_number_from_month_name,
    get_scope_from_label,
    replace_roman_with_arabic_numerals,
)
from apps.common.services.timetable.utilities.model_helpers import (
    is_abstract_event_already_exists,
)
from apps.common.services.timetable.utilities.normalizers import (
    normalize_kind_name,
    normalize_participant_name,
    normalize_place_building_and_room,
    normalize_scope,
    normalize_subject_name,
    normalize_time_slot_display_name,
)
from apps.common.services.timetable.write.factories import (
    create_abstract_event,
    fill_semester_for_dates,
)

logger = logging.getLogger(__name__)


class EventImporter:
    @classmethod
    def import_events(
        cls,
        event_data: str,
        *,
        resolver: EntityResolver | None = None,
        corrections_strict: bool = False,
        resolution_report: ResolutionReport | None = None,
    ):
        """Import AbstractEvents and Events from given data"""

        json_data = json.loads(event_data)

        return cls.make_import(
            json_data["title"],
            json_data["table"]["grid"],
            json_data["table"]["datetime"]["weeks"],
            json_data["table"]["datetime"]["week_days"],
            json_data["table"]["datetime"]["months"],
            resolver=resolver,
            corrections_strict=corrections_strict,
            resolution_report=resolution_report,
        )

    @classmethod
    def make_import(
        cls,
        title: str,
        entries,
        weeks,
        week_days: list[str],
        months: list[str],
        *,
        resolver: EntityResolver | None = None,
        corrections_strict: bool = False,
        resolution_report: ResolutionReport | None = None,
    ):
        """Applies data on database"""

        report = resolution_report if resolution_report is not None else ResolutionReport()
        schedule = cls.find_schedule(replace_roman_with_arabic_numerals(title))
        reference_lookup = {
            "subjects": {},
            "kinds": {},
            "participants": {},
            "places": {},
            "time_slots": TimeSlot.objects.none(),
        }

        for entry in entries:
            cls.correct_event_data(schedule, entry)

            if resolver is not None:
                ok = cls.apply_entity_resolution(
                    entry,
                    resolver=resolver,
                    corrections_strict=corrections_strict,
                    report=report,
                    reference_lookup=reference_lookup,
                    context={"schedule_title": title},
                )
                if not ok:
                    continue

            reference_data = cls.collect_reference_data(entry)

            if not reference_data:
                continue

            cls.make_reference_lookup(reference_data, reference_lookup)

            calendar = cls.make_calendar(weeks, months, schedule)

            cls.create_events(
                schedule, *cls.parse_data(entry, calendar, week_days, reference_lookup)
            )

        return report

    @classmethod
    def apply_entity_resolution(
        cls,
        event_data: dict[str, Any],
        *,
        resolver: EntityResolver,
        corrections_strict: bool,
        report: ResolutionReport,
        reference_lookup: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> bool:
        """Прогнать teacher/group/subject/place через resolver.

        При hit переписывает строки в event_data на canonical и кладёт ORM в lookup.
        При miss + strict — False (пропустить занятие).
        При miss + не strict — оставляет строки для старого exact-create (fallback).
        """
        ctx = context or {}

        subject_raw = event_data.get("subject") or ""
        subject_hit = cls._resolve_one(
            subject_raw,
            "subject",
            resolver=resolver,
            corrections_strict=corrections_strict,
            report=report,
            context=ctx,
        )
        if subject_hit is False:
            return False
        if isinstance(subject_hit, ResolvedHit):
            event_data["subject"] = subject_hit.canonical_value
            cls._put_hit_in_lookup(subject_hit, reference_lookup)

        participants = event_data.setdefault("participants", {})
        teachers = list(participants.get("teachers") or [])
        resolved_teachers: list[str] = []
        for raw in teachers:
            hit = cls._resolve_one(
                raw,
                "teacher",
                resolver=resolver,
                corrections_strict=corrections_strict,
                report=report,
                context=ctx,
            )
            if hit is False:
                return False
            if isinstance(hit, ResolvedHit):
                resolved_teachers.append(hit.canonical_value)
                cls._put_hit_in_lookup(hit, reference_lookup)
            else:
                resolved_teachers.append(raw)
        participants["teachers"] = resolved_teachers

        groups = list(participants.get("student_groups") or [])
        resolved_groups: list[str] = []
        for raw in groups:
            hit = cls._resolve_one(
                raw,
                "group",
                resolver=resolver,
                corrections_strict=corrections_strict,
                report=report,
                context=ctx,
            )
            if hit is False:
                return False
            if isinstance(hit, ResolvedHit):
                resolved_groups.append(hit.canonical_value)
                cls._put_hit_in_lookup(hit, reference_lookup)
            else:
                resolved_groups.append(raw)
        participants["student_groups"] = resolved_groups

        places = list(event_data.get("places") or [])
        resolved_places: list[str] = []
        for raw in places:
            hit = cls._resolve_one(
                raw,
                "place",
                resolver=resolver,
                corrections_strict=corrections_strict,
                report=report,
                context=ctx,
            )
            if hit is False:
                return False
            if isinstance(hit, ResolvedHit):
                resolved_places.append(hit.canonical_value)
                cls._put_hit_in_lookup(hit, reference_lookup)
            else:
                resolved_places.append(raw)
        event_data["places"] = resolved_places
        return True

    @staticmethod
    def _resolve_one(
        value: str,
        entity_type: EntityType,
        *,
        resolver: EntityResolver,
        corrections_strict: bool,
        report: ResolutionReport,
        context: dict[str, Any],
    ) -> ResolvedHit | None | bool:
        """ResolvedHit | None (fallback) | False (skip entry)."""
        raw = (value or "").strip()
        if not raw:
            return None
        hit = resolver.resolve(raw, entity_type, context=context)
        if hit is not None:
            report.note_resolved(raw, hit)
            return hit
        report.note_ambiguous(raw, entity_type)
        if corrections_strict:
            report.note_skipped(raw, entity_type)
            return False
        report.note_fallback(raw, entity_type)
        return None

    @staticmethod
    def _put_hit_in_lookup(hit: ResolvedHit, reference_lookup: dict[str, Any]) -> None:
        if hit.model_label == "common.subject":
            obj = Subject.objects.filter(pk=hit.pk).first()
            if obj is not None:
                reference_lookup["subjects"][obj.name] = obj
        elif hit.model_label == "common.eventparticipant":
            obj = EventParticipant.objects.filter(pk=hit.pk).first()
            if obj is not None:
                reference_lookup["participants"][obj.name] = obj
        elif hit.model_label == "common.eventplace":
            obj = EventPlace.objects.filter(pk=hit.pk).first()
            if obj is not None:
                reference_lookup["places"][(obj.building, obj.room)] = obj
                # parse_data нормализует place-строку; канон должен разбираться
                # в тот же (building, room).

    @classmethod
    def correct_event_data(cls, schedule: Schedule, event_data) -> None:
        """Corrects inaccuracies and defects in given event_data"""

        # Fixing dates
        corrected_holds_on_date = cls.correct_holds_on_date_data(
            schedule, event_data["holds_on_date"]
        )

        if corrected_holds_on_date:
            event_data["holds_on_date"] = corrected_holds_on_date

    @staticmethod
    def correct_holds_on_date_data(
        schedule: Schedule, holds_on_date: list[str]
    ) -> list[str] | None:
        """Replaces ".." and ";" in holds_on_date with correct dates

        Returns corrected sorted list holds_on_date of unique dates

        Returns None when nothing changed
        """

        # 03.09.2024
        COMMON_DATE_REG_EX = r"\d{1,2}.\d{1,2}.\d{4}"

        # 03.09..01.10
        DOUBLE_RANGE_DATE_REG_EX = r"(\d{1,2}.\d{1,2})..(\d{1,2}.\d{1,2})"

        # с 03.09
        # с03.09
        # с   03.09
        SINGLE_RANGE_DATE_REG_EX = r"с\s*(\d{1,2}.\d{1,2})"

        # 03.09
        #   03.09
        DAY_MONTH_DATE_REG_EX = r"(\d{1,2}.\d{1,2})"

        LEFT_YEAR, RIGHT_YEAR = schedule.metadata.years.split("-", 1)
        is_something_corrected = False
        corrected_holds_on_date: set[str] = set()

        for date_ in holds_on_date:
            if re.search(COMMON_DATE_REG_EX, date_):
                corrected_holds_on_date.add(date_)

                continue

            if ";" in date_:
                for splited_date in date_.split(";"):
                    day, month = splited_date.strip().split(".", 1)

                    corrected_holds_on_date.add(
                        f"{day}.{month}.{LEFT_YEAR if int(month) > 6 else RIGHT_YEAR}"
                    )

                is_something_corrected = True

                continue

            match = re.search(DOUBLE_RANGE_DATE_REG_EX, date_)

            if match:
                from_day, from_month = match.group(1).split(".", 1)
                to_day, to_month = match.group(2).split(".", 1)

                from_date = datetime.strptime(
                    f"{from_day}.{from_month}.{LEFT_YEAR if int(from_month) > 6 else RIGHT_YEAR}",
                    "%d.%m.%Y",
                ).date()
                to_date = datetime.strptime(
                    f"{to_day}.{to_month}.{LEFT_YEAR if int(from_month) > 6 else RIGHT_YEAR}",
                    "%d.%m.%Y",
                ).date()

                while from_date <= to_date:
                    corrected_holds_on_date.add(from_date.strftime("%d.%m.%Y"))

                    from_date += timedelta(days=schedule.schedule_template.repetition_period)

                is_something_corrected = True

                continue

            match = re.search(SINGLE_RANGE_DATE_REG_EX, date_)

            if match:
                from_day, from_month = match.group(1).split(".", 1)

                from_date = datetime.strptime(
                    f"{from_day}.{from_month}.{LEFT_YEAR if int(from_month) > 6 else RIGHT_YEAR}",
                    "%d.%m.%Y",
                ).date()

                while from_date <= schedule.end_date:
                    corrected_holds_on_date.add(from_date.strftime("%d.%m.%Y"))

                    from_date += timedelta(days=schedule.schedule_template.repetition_period)

                is_something_corrected = True

                continue

            match = re.search(DAY_MONTH_DATE_REG_EX, date_)

            if match:
                day, month = match.group(1).strip().split(".", 1)

                corrected_holds_on_date.add(
                    f"{day}.{month}.{LEFT_YEAR if int(month) > 6 else RIGHT_YEAR}"
                )

                is_something_corrected = True

                continue

            raise ValueError(
                f"Неправильный формат даты '{date_}' в holds_on_date '{holds_on_date}'."
            )

        return sorted(corrected_holds_on_date) if is_something_corrected else None

    @staticmethod
    def collect_reference_data(event_data) -> dict:
        """Collects and prepares data"""

        subjects: set[str] = set()
        kinds: set[str] = set()
        teachers: set[str] = set()
        groups: set[str] = set()
        places: set[tuple[str, str]] = set()
        time_slots: set[tuple[str, str, str]] = set()

        subjects.add(normalize_subject_name(event_data["subject"]))

        kinds.add(normalize_kind_name(event_data["kind"]))

        for teacher in event_data.get("participants", {}).get("teachers", []):
            normalized_teacher = normalize_participant_name(teacher)

            if normalized_teacher:
                teachers.add(normalized_teacher)

        for group in event_data.get("participants", {}).get("student_groups", []):
            normalized_group = normalize_participant_name(group)

            if normalized_group:
                groups.add(normalized_group)

        for place in event_data.get("places", []):
            normalized_place = normalize_place_building_and_room(place)

            if normalized_place:
                places.add(normalized_place)

        for time_slot in event_data.get("hours", []):
            normalized_time_slot = normalize_time_slot_display_name(time_slot)

            if normalized_time_slot:
                time_slots.add(normalized_time_slot)

        return {
            "subjects": subjects,
            "kinds": kinds,
            "teachers": teachers,
            "groups": groups,
            "places": places,
            "time_slots": time_slots,
        }

    @staticmethod
    def make_reference_lookup(reference_data: dict, reference_lookup: dict) -> None:
        """Creates models for reference_data that not exist in database.
        Then updates reference_lookup
        """

        subjects = reference_data.get("subjects", set())

        if subjects:
            existing_subjects = Subject.objects.filter(name__in=subjects)
            existing_subject_names = list(
                existing_subjects.values_list("name", flat=True).distinct()
            )

            for subject in list(existing_subjects):
                if subject.name not in reference_lookup["subjects"]:
                    reference_lookup["subjects"].update({subject.name: subject})

            subjects_to_create = [
                Subject(name=name) for name in subjects if name not in existing_subject_names
            ]

            if subjects_to_create:
                created_subjects = Subject.objects.bulk_create(subjects_to_create)

                for subject in created_subjects:
                    reference_lookup["subjects"].update({subject.name: subject})

        kinds = reference_data.get("kinds", set())

        if kinds:
            existing_kinds = EventKind.objects.filter(name__in=kinds)
            existing_kind_names = list(existing_kinds.values_list("name", flat=True).distinct())

            for kind in list(existing_kinds):
                if kind.name not in reference_lookup["kinds"]:
                    reference_lookup["kinds"].update({kind.name: kind})

            kinds_to_create = [
                EventKind(name=name) for name in kinds if name not in existing_kind_names
            ]

            if kinds_to_create:
                created_kinds = EventKind.objects.bulk_create(kinds_to_create)

                for kind in created_kinds:
                    reference_lookup["kinds"].update({kind.name: kind})

        teachers = reference_data.get("teachers", set())
        groups = reference_data.get("groups", set())
        participants = teachers | groups

        if participants:
            existing_participants = EventParticipant.objects.filter(name__in=participants)
            existing_participants_names = list(
                existing_participants.values_list("name", flat=True).distinct()
            )

            for participant in list(existing_participants):
                if participant.name not in reference_lookup["participants"]:
                    reference_lookup["participants"].update({participant.name: participant})

            participants_to_create = []

            participants_to_create = [
                EventParticipant(
                    name=name,
                    role=EventParticipant.Role.TEACHER,
                    is_group=False,
                    # TODO: add department
                )
                for name in teachers
                if name not in existing_participants_names
            ]

            participants_to_create.extend(
                EventParticipant(
                    name=name,
                    role=EventParticipant.Role.STUDENT,
                    is_group=True,
                    # TODO: add department
                )
                for name in groups
                if name not in existing_participants_names
            )

            if participants_to_create:
                created_participants = EventParticipant.objects.bulk_create(participants_to_create)

                for participant in created_participants:
                    if participant.name not in reference_lookup["participants"]:
                        reference_lookup["participants"].update({participant.name: participant})

        places = reference_data.get("places", set())

        if places:
            rooms = {room for _, room in places}

            existing_places = EventPlace.objects.filter(room__in=rooms)
            existing_places_reprs = list(existing_places.values_list("building", "room").distinct())

            for place in list(existing_places):
                if (place.building, place.room) not in reference_lookup["places"]:
                    reference_lookup["places"].update({(place.building, place.room): place})

            places_to_create = []

            for building, room in places:
                if (building, room) not in existing_places_reprs:
                    places_to_create.append(EventPlace(building=building, room=room))

            if places_to_create:
                created_places = EventPlace.objects.bulk_create(places_to_create)

                for place in created_places:
                    if (place.building, place.room) not in reference_lookup["places"]:
                        reference_lookup["places"].update({(place.building, place.room): place})

        time_slots = reference_data.get("time_slots", set())

        if time_slots:
            existing_time_slots = TimeSlot.objects.none()

            for time_slot in time_slots:
                filter_query = Q()

                # alt_name
                if time_slot[0]:
                    filter_query &= Q(alt_name=time_slot[0])

                # start_time
                if time_slot[1]:
                    filter_query &= Q(start_time=time_slot[1])

                # end_time
                if time_slot[2]:
                    filter_query &= Q(end_time=time_slot[2])

                if filter_query:
                    existing_time_slots |= TimeSlot.objects.filter(filter_query)
            existing_time_slots_alt_names = existing_time_slots.values_list(
                "alt_name", flat=True
            ).distinct()
            existing_time_slots_start_times = existing_time_slots.values_list(
                "start_time", flat=True
            ).distinct()
            existing_time_slots_end_times = existing_time_slots.values_list(
                "end_time", flat=True
            ).distinct()

            reference_lookup["time_slots"] = existing_time_slots

            time_slots_to_create = []

            for alt_name, start_time, end_time in time_slots:
                # At this moment, we auto creating TimeSlots ONLY from start_time
                if (
                    start_time
                    and datetime.strptime(start_time, "%H:%M").time()
                    not in existing_time_slots_start_times
                    and (not alt_name or alt_name not in existing_time_slots_alt_names)
                    and (
                        not end_time
                        or datetime.strptime(end_time, "%H:%M").time()
                        not in existing_time_slots_end_times
                    )
                ):
                    time_slots_to_create.append(
                        TimeSlot(
                            alt_name=alt_name,
                            start_time=datetime.strptime(start_time, "%H:%M"),
                            end_time=datetime.strptime(end_time, "%H:%M") if end_time else None,
                        )
                    )

            if time_slots_to_create:
                created_time_slots = TimeSlot.objects.bulk_create(time_slots_to_create)

                reference_lookup["time_slots"] |= TimeSlot.objects.filter(
                    pk__in={time_slot.pk for time_slot in created_time_slots}
                )

    @staticmethod
    def find_schedule(title: str) -> Schedule:
        """Finds Schedule from given title. If Schedule not exists then creates it

        Title must contain course, faculty, scope, semester and years information
        """

        # 4 курса
        # 4 курс
        # 4курса
        # 4   курса
        # 1ый курс
        # 5-ого курса
        # 3-го курса
        COURSE_REG_EX = r"(\d)(\-?[а-яА-ЯёЁ]*)?\s*курса?"

        # ФЭВТ
        # ТК
        # курсФЭВТна
        # TODO: ФАСТиВ
        FACULTY_REG_EX = r"[А-ЯЁ]{2,}"

        # Бакалавры
        # бакалавриат
        # магистров
        # Аспирантура
        # консульт.
        SCOPE_REG_EX = r"(([бБ]акалавр|[мМ]агистр|[аА]спирант|[кК]онсульт)[а-яА-ЯёЁ]*)"

        # 2 семестр
        # 2семестр
        # 2   семестр
        # 2-ой семестр
        # 2-й семестр
        # 1ый семестр
        ARABIC_NUMERALS_SEMESTER_REG_EX = r"(\d)(\-?[а-яА-ЯёЁ]*)?\s*семестра?"

        # 2024-2025
        # 2024 -  2025
        FULL_YEARS_REG_EX = r"(\d{4}\s*-\s*\d{4})"

        reader = Selector()

        course_match = re.search(COURSE_REG_EX, title, flags=re.IGNORECASE)
        if course_match:
            reader.add_filter({"metadata__course": int(course_match.group(1))})

        faculty_matches = re.findall(FACULTY_REG_EX, title)
        if not faculty_matches:
            raise ValueError(
                f"Не удалось извлечь подразделение или факультет из заголовка '{title}'."
            )

        is_faculty_found = False

        for match in faculty_matches:
            try:
                Department.objects.get(shortname=match)
            except Department.DoesNotExist:
                continue

            # take first existing faculty from title
            reader.add_filter({"schedule_template__metadata__faculty__iexact": match})

            is_faculty_found = True

            break

        if not is_faculty_found:
            raise ValueError(
                f"Не удалось найти подходящее подразделение или факультет для заголовка '{title}'."
            )

        scope_match = re.search(SCOPE_REG_EX, title)
        if scope_match:
            reader.add_filter(
                {
                    "schedule_template__metadata__scope": get_scope_from_label(
                        normalize_scope(scope_match.group(1))
                    )
                }
            )

        semester_match = re.search(ARABIC_NUMERALS_SEMESTER_REG_EX, title, flags=re.IGNORECASE)
        if semester_match:
            reader.add_filter({"metadata__semester": int(semester_match.group(1))})

        full_years_match = re.search(FULL_YEARS_REG_EX, title)
        if full_years_match:
            reader.add_filter({"metadata__years": full_years_match.group(1).replace(" ", "")})

        if not reader.has_any_filter_added():
            raise ValueError(f"Не удалось извлечь параметры расписания из заголовка '{title}'.")

        reader.add_filter({"status": Schedule.Status.ACTIVE})
        reader.find_models(Schedule)

        if not reader.is_any_model_found():
            raise Schedule.DoesNotExist(
                f"Расписание с параметрами {reader.get_filter_query()} не найдено."
                f"Заголовок: '{title}'."
            )

        if not reader.is_single_model_found():
            raise Schedule.MultipleObjectsReturned(
                f"Найдено несколько расписаний, удовлетворяющих параметрам {reader.get_filter_query()}."
                "Уточните заголовок."
            )

        schedule = reader.get_found_models().first()
        if schedule is None:
            raise Schedule.DoesNotExist(
                f"Расписание с параметрами {reader.get_filter_query()} не найдено."
                f"Заголовок: '{title}'."
            )

        return schedule

    @staticmethod
    def make_calendar(weeks, months: list[str], schedule: Schedule) -> dict:
        """Makes calendar of dates for Event creating in format:

        parsed_weeks = {
            week_id : {
                week_day_index : [
                    dd.mm.YYYY
                ]
            }
        }
        """

        normalized_weeks = {}

        if not len(weeks):
            raise ValueError("Отсутствуют данные недель в импортируемом файле.")

        if isinstance(weeks, dict):
            normalized_weeks = weeks
        elif isinstance(weeks, list):
            for week in weeks:
                if isinstance(week, dict):
                    for key, data in week.items():
                        normalized_weeks[key] = data
                else:
                    raise ValueError("Некорректный формат данных недель в импортируемом файле.")
        else:
            raise ValueError("Некорректный формат данных недель в импортируемом файле.")

        calendar = {}

        LEFT_YEAR, RIGHT_YEAR = schedule.metadata.years.split("-", 1)

        for key in normalized_weeks:
            calendar[key] = {}

            for week_day in normalized_weeks[key]:
                calendar[key][week_day["week_day_index"]] = []

                for month in week_day["calendar"]:
                    month_number = get_number_from_month_name(months[month["month_index"]])

                    for month_day in month["month_days"]:
                        calendar[key][week_day["week_day_index"]].append(
                            datetime.strptime(
                                f"{month_day}.{month_number}.{LEFT_YEAR if month_number > 6 else RIGHT_YEAR}",
                                "%d.%m.%Y",
                            ).date()
                        )

        return calendar

    @staticmethod
    def parse_data(
        event_data, calendar, week_days: list[str], reference_lookup: dict
    ) -> tuple[
        EventKind,
        Subject,
        list[EventParticipant],
        list[EventPlace],
        AbstractDay,
        list[TimeSlot],
        list[date] | list[None],
        list[date],
    ]:
        """Finds existing models for Event data

        Method uses pre-prepared reference data

        Raise DoesNotExist if model not found
        """

        week_id = event_data["week"]
        week_day_index = event_data["week_day_index"]

        kind_name = normalize_kind_name(event_data["kind"])
        kind = reference_lookup["kinds"].get(kind_name)
        if kind is None:
            raise EventKind.DoesNotExist(
                f"Тип события '{kind_name}' не найден после подготовки справочников."
            )

        subject_name = normalize_subject_name(event_data["subject"])
        subject = reference_lookup["subjects"].get(subject_name)
        if subject is None:
            raise Subject.DoesNotExist(
                f"Предмет '{subject_name}' не найден после подготовки справочников."
            )

        participants = []
        missing_participants = []

        for teacher_name in event_data.get("participants", {}).get("teachers", []):
            normalized = normalize_participant_name(teacher_name)
            participant = reference_lookup["participants"].get(normalized)
            if participant:
                participants.append(participant)
            else:
                missing_participants.append(normalized)

        for group_name in event_data.get("participants", {}).get("student_groups", []):
            normalized = normalize_participant_name(group_name)
            participant = reference_lookup["participants"].get(normalized)
            if participant:
                participants.append(participant)
            else:
                missing_participants.append(normalized)

        if missing_participants:
            raise EventParticipant.DoesNotExist(
                f"Не удалось найти участников: {', '.join(missing_participants)}"
            )

        places = []
        missing_places = []
        for place_repr in event_data.get("places", []):
            normalized_place = normalize_place_building_and_room(place_repr)

            if not normalized_place:
                continue

            place = reference_lookup["places"].get(normalized_place)
            if place:
                places.append(place)
            else:
                missing_places.append(place_repr)

        if missing_places:
            raise EventPlace.DoesNotExist(
                f"Не удалось найти аудитории: {', '.join(missing_places)}"
            )

        abstract_day = AbstractDay.objects.get(
            name__startswith=1 if week_id == "first_week" else 2,
            name__endswith=week_days[week_day_index].capitalize(),
        )

        time_slots = []
        missing_time_slots = []
        for time_slot_repr in event_data.get("hours", []):
            normalized_time_slot = normalize_time_slot_display_name(time_slot_repr)

            if not normalized_time_slot:
                continue

            ## TODO: select timeslot with alt_name > without altname
            time_slot = (
                reference_lookup["time_slots"]
                .filter(
                    **cast(
                        dict[str, object],
                        TimeSlotFilter.from_display_name(
                            normalized_time_slot[1] or normalized_time_slot[0]
                        ),
                    )
                )
                .first()
            )

            if time_slot:
                time_slots.append(time_slot)
            else:
                missing_time_slots.append(time_slot_repr)

        if missing_time_slots:
            raise TimeSlot.DoesNotExist(
                f"Не найден учебный час для значений: {', '.join(missing_time_slots)}"
            )

        holds_on_date_values = event_data.get("holds_on_date") or []
        if holds_on_date_values:
            holds_on_dates = [
                datetime.strptime(date_, "%d.%m.%Y").date() for date_ in holds_on_date_values
            ]
        else:
            holds_on_dates = [None]

        event_dates = calendar[week_id][week_day_index]

        return (
            kind,
            subject,
            participants,
            places,
            abstract_day,
            time_slots,
            holds_on_dates,
            event_dates,
        )

    @staticmethod
    def create_events(
        schedule: Schedule,
        kind: EventKind,
        subject: Subject,
        participants: list[EventParticipant],
        places: list[EventPlace],
        abstract_day: AbstractDay,
        time_slots: list[TimeSlot],
        holds_on_dates: list[date] | list[None],
        calendar: list[date],
    ) -> None:
        """Creates AbstractEvents and Events for given TimeSlots and dates

        Not create duplicates
        """

        for date_ in holds_on_dates:
            for time_slot in time_slots:
                if is_abstract_event_already_exists(
                    kind, subject, participants, places, abstract_day, time_slot, date_, schedule
                ):
                    continue

                created_abstract_event = create_abstract_event(
                    kind, subject, participants, places, abstract_day, time_slot, date_, schedule
                )

                fill_semester_for_dates(created_abstract_event, calendar)

from datetime import datetime

from django.test import TestCase

from apps.common.models import (
    AbstractDay,
    AbstractEvent,
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
from apps.common.services.timetable.load.reference_importer import ReferenceImporter
from apps.common.services.timetable.utilities.model_helpers import (
    create_common_abstract_days,
    create_common_time_slots,
)
from apps.common.services.timetable.write.factories import calculate_semester_filling_parameters

"""python manage.py test apps.common.tests.test_writeapi
"""


class TestWriteAPI(TestCase):
    def setUp(self):
        FACULTY_REFERENCE_DATA = """
        [
            {
                "faculty_id" : "111",
                "faculty_fullname" : "ФАКУЛЬТЕТ",
                "faculty_code" : "000000111",
                "faculty_shortname" : "ФАКУЛЬТ"
            }
        ]
        """
        DEPARTMENT_REFERENCE_DATA = """
            [
                {
                    "department_id" : "0",
                    "department_code" : "000000000",
                    "department_fullname" : "ПОДРАЗДЕЛЕНИЕ",
                    "department_shortname" : "ПОДРАЗД",
                    "faculty_id" : "111",
                    "faculty_shortname" : "ФАКУЛЬТ"
                }
            ]
        """
        SCHEDULE_REFERENCE_DATA = """
            [
                {
                    "course": "1",
                    "schedule_template_metadata_faculty_shortname": "ФАКУЛЬТ",
                    "semester": "1",
                    "years": "2026-2027",
                    "start_date": "01.09.2026",
                    "end_date": "01.02.2027",
                    "starting_day_number": "1",
                    "scope": "Магистратура",
                    "department_shortname": "ФАКУЛЬТ"
                }
            ]
        """

        create_common_abstract_days()
        create_common_time_slots()
        Organization.objects.create(name="ВолгГТУ")
        ReferenceImporter.import_faculty_reference(FACULTY_REFERENCE_DATA)
        ReferenceImporter.import_department_reference(DEPARTMENT_REFERENCE_DATA)
        ReferenceImporter.import_schedule(SCHEDULE_REFERENCE_DATA, True)

    def test_calculate_semester_filling_parameters_for_14_rep_period(self):
        schedule = Schedule.objects.get(
            schedule_template__metadata__faculty="ФАКУЛЬТ",
            schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.MASTER,
            metadata__course=1,
            metadata__semester=1,
        )
        KIND = EventKind.objects.create(name="Лекция")
        SUBJECT = Subject.objects.create(name="ПРЕДМЕТ")
        DEPARTMENT = Department.objects.get(shortname="ФАКУЛЬТ")
        PARTICIPANTS = [
            EventParticipant.objects.create(
                name="Преподаватель И.О.",
                role=EventParticipant.Role.TEACHER,
                is_group=False,
                department=DEPARTMENT,
            ),
            EventParticipant.objects.create(
                name="Группа-123",
                role=EventParticipant.Role.STUDENT,
                is_group=True,
                department=DEPARTMENT,
            ),
        ]
        PLACES = [EventPlace.objects.create(building="КОРПУС", room="123")]
        abs_event = AbstractEvent.objects.create(
            kind=KIND,
            subject=SUBJECT,
            abstract_day=AbstractDay.objects.get(day_number=0),
            time_slot=TimeSlot.objects.get(alt_name="1-2", start_time="08:30", end_time="10:00"),
            schedule=schedule,
        )
        abs_event.participants.set(PARTICIPANTS)
        abs_event.places.set(PLACES)

        TEST_DATA = [
            # FIRST week
            # abs_event BEFORE start_date
            {
                "schedule_start_date": "01.09.2026",
                "schedule_starting_day_number": 1,
                "abs_event_day_number": 0,
                "expected_fill_from_date": "14.09.2026",
            },
            {
                "schedule_start_date": "03.09.2026",
                "schedule_starting_day_number": 3,
                "abs_event_day_number": 1,
                "expected_fill_from_date": "15.09.2026",
            },
            # abs_event AFTER start_date
            {
                "schedule_start_date": "02.09.2026",
                "schedule_starting_day_number": 2,
                "abs_event_day_number": 5,
                "expected_fill_from_date": "5.09.2026",
            },
            {
                "schedule_start_date": "1.09.2026",
                "schedule_starting_day_number": 1,
                "abs_event_day_number": 13,
                "expected_fill_from_date": "13.09.2026",
            },
            # abs_event ON SAME DAY AS start_date
            {
                "schedule_start_date": "6.09.2026",
                "schedule_starting_day_number": 6,
                "abs_event_day_number": 6,
                "expected_fill_from_date": "6.09.2026",
            },
            # SECOND week
            # abs_event BEFORE start_date (SAME week)
            {
                "schedule_start_date": "10.09.2026",
                "schedule_starting_day_number": 10,
                "abs_event_day_number": 7,
                "expected_fill_from_date": "21.09.2026",
            },
            # abs_event AFTER start_date (SAME week)
            {
                "schedule_start_date": "10.09.2026",
                "schedule_starting_day_number": 10,
                "abs_event_day_number": 13,
                "expected_fill_from_date": "13.09.2026",
            },
            # abs_event BEFORE start_date (FIRST week)
            {
                "schedule_start_date": "7.09.2026",
                "schedule_starting_day_number": 7,
                "abs_event_day_number": 6,
                "expected_fill_from_date": "20.09.2026",
            },
            {
                "schedule_start_date": "13.09.2026",
                "schedule_starting_day_number": 13,
                "abs_event_day_number": 0,
                "expected_fill_from_date": "14.09.2026",
            },
            # abs_event ON SAME DAY AS start_date
            {
                "schedule_start_date": "13.09.2026",
                "schedule_starting_day_number": 13,
                "abs_event_day_number": 13,
                "expected_fill_from_date": "13.09.2026",
            },
        ]

        for data in TEST_DATA:
            schedule.start_date = datetime.strptime(data["schedule_start_date"], "%d.%m.%Y").date()
            schedule.starting_day_number = AbstractDay.objects.get(
                day_number=data["schedule_starting_day_number"]
            )
            schedule.schedule_template.aligned_by_week_day = data["schedule_starting_day_number"]
            schedule.save()

            abs_event.abstract_day = AbstractDay.objects.get(
                day_number=data["abs_event_day_number"]
            )
            abs_event.save()

            self.assertSequenceEqual(
                calculate_semester_filling_parameters(abs_event),
                (
                    datetime.strptime(data["schedule_start_date"], "%d.%m.%Y").date(),
                    schedule.end_date,
                    datetime.strptime(data["expected_fill_from_date"], "%d.%m.%Y").date(),
                    schedule.schedule_template.repetition_period,
                ),
            )

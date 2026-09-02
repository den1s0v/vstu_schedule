import json
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
from apps.common.services.timetable.load.event_importer import EventImporter
from apps.common.services.timetable.load.reference_importer import ReferenceImporter
from apps.common.services.timetable.read.filters import (
    PlaceFilter,
    TimeSlotFilter,
)
from apps.common.services.timetable.utilities.model_helpers import (
    create_common_abstract_days,
    create_common_time_slots,
)

"""python manage.py test apps.common.tests.test_import
"""


class TestEventImporter(TestCase):
    FACULTY_REFERENCE_DATA = """
        [
            {
                "faculty_id" : "111",
                "faculty_fullname" : "Факультет электроники и вычислительной техники",
                "faculty_code" : "000000111",
                "faculty_shortname" : "ФЭВТ"
            },
            {
                "faculty_id" : "222",
                "faculty_fullname" : "Химико-технологический факультет",
                "faculty_code" : "000000222",
                "faculty_shortname" : "ХТФ"
            }
        ]
    """
    SCHEDULE_REFERENCE_DATA = """
        [
            {
                "course": "4",
                "schedule_template_metadata_faculty_shortname": "ФЭВТ",
                "semester": "2",
                "years": "2024-2025",
                "start_date": "01.09.2024",
                "end_date": "01.02.2025",
                "scope": "Бакалавриат",
                "department_shortname": "ФЭВТ"
            },
            {
                "course": "2",
                "schedule_template_metadata_faculty_shortname": "ФЭВТ",
                "semester": "1",
                "years": "2024-2025",
                "start_date": "01.09.2024",
                "end_date": "01.02.2025",
                "scope": "магистры",
                "department_shortname": "ФЭВТ"
            },
            {
                "course": "1",
                "schedule_template_metadata_faculty_shortname": "ФЭВТ",
                "semester": "2",
                "years": "2024-2025",
                "start_date": "01.09.2024",
                "end_date": "01.02.2025",
                "scope": "аспиранты",
                "department_shortname": "ФЭВТ"
            }
        ]
    """

    def setUp(self):
        create_common_abstract_days()
        create_common_time_slots()
        Organization.objects.create(name="ВолгГТУ")
        ReferenceImporter.import_faculty_reference(self.FACULTY_REFERENCE_DATA)
        ReferenceImporter.import_schedule(self.SCHEDULE_REFERENCE_DATA, True)

    def test_find_schedule(self):
        self.assertEqual(
            EventImporter.find_schedule(
                "Учебные занятия 4 курса ФЭВТ бакалавриат на 2 семестр 2024-2025 учебного года"
            ),
            Schedule.objects.get(
                schedule_template__metadata__faculty="ФЭВТ",
                schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
            ),
        )
        self.assertEqual(
            EventImporter.find_schedule(
                "Учебные занятия 4 курса ФЭВТ бакалавриат на 2 семестр 2024 -  2025 учебного года"
            ),
            Schedule.objects.get(
                schedule_template__metadata__faculty="ФЭВТ",
                schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
            ),
        )
        self.assertRaises(ValueError, EventImporter.find_schedule, "")
        self.assertRaises(
            ValueError,
            EventImporter.find_schedule,
            "Учебные занятия 4 курса бакалавриат на 2 семестр 2024-2025 учебного года",
        )

        ReferenceImporter.import_schedule(
            """
            [
                {
                    "course": "4",
                    "schedule_template_metadata_faculty_shortname": "ФЭВТ",
                    "semester": "2",
                    "years": "2024-2025",
                    "start_date": "01.09.2024",
                    "end_date": "01.02.2025",
                    "scope": "Бакалавриат",
                    "department_shortname": "ФЭВТ"
                }
            ]
        """,
            True,
        )

        second_schedule = Schedule.objects.get(status=Schedule.Status.ARCHIVE)
        second_schedule.status = Schedule.Status.ACTIVE
        second_schedule.save()

        self.assertRaises(
            Schedule.MultipleObjectsReturned,
            EventImporter.find_schedule,
            "Учебные занятия 4 курса ФЭВТ бакалавриат на 2 семестр 2024-2025 учебного года",
        )

    def test_find_schedule_scopes(self):
        self.assertEqual(
            EventImporter.find_schedule("4 курс ФЭВТ Баколавры II-ого семестра 2024-2025"),
            Schedule.objects.get(
                schedule_template__metadata__faculty="ФЭВТ",
                schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
                metadata__course=4,
                metadata__semester=2,
            ),
        )
        self.assertEqual(
            EventImporter.find_schedule("4 курс ФЭВТ баколавров II-ого семестра 2024-2025"),
            Schedule.objects.get(
                schedule_template__metadata__faculty="ФЭВТ",
                schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
                metadata__course=4,
                metadata__semester=2,
            ),
        )
        self.assertEqual(
            EventImporter.find_schedule(
                "Учебные занятия ФЭВТ магистров 2 курса I-ого семестра 2024-2025"
            ),
            Schedule.objects.get(
                schedule_template__metadata__faculty="ФЭВТ",
                schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.MASTER,
                metadata__course=2,
                metadata__semester=1,
            ),
        )
        self.assertEqual(
            EventImporter.find_schedule(
                "Учебные занятия ФЭВТ магистратуры 2 курса I-ого семестра 2024-2025"
            ),
            Schedule.objects.get(
                schedule_template__metadata__faculty="ФЭВТ",
                schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.MASTER,
                metadata__course=2,
                metadata__semester=1,
            ),
        )
        self.assertEqual(
            EventImporter.find_schedule("ФЭВТ 1 курс аспирантов на II-й семестр 2024-2025"),
            Schedule.objects.get(
                schedule_template__metadata__faculty="ФЭВТ",
                schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.POSTGRADUATE,
                metadata__course=1,
                metadata__semester=2,
            ),
        )

    def test_find_schedule_multiple_department(self):
        self.assertEqual(
            EventImporter.find_schedule(
                "Учебные занятия 4 курса АБЬЪ-999, ФЭВТ бакалавриат на 2 семестр 2024-2025 учебного года"
            ),
            Schedule.objects.get(
                schedule_template__metadata__faculty="ФЭВТ",
                schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
            ),
        )
        self.assertEqual(
            EventImporter.find_schedule(
                "Учебные занятия 4 курса ФЭВТ ХТФ бакалавриат на 2 семестр 2024-2025 учебного года"
            ),
            Schedule.objects.get(
                schedule_template__metadata__faculty="ФЭВТ",
                schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
            ),
        )

        WRONG_SCHEDULE_TITLE = "Учебные занятия 4 курса АБВГ, ПРИН-466 бакалавриат на 2 семестр 2024-2025 учебного года"

        self.assertRaisesMessage(
            ValueError,
            f"Не удалось найти подходящее подразделение или факультет для заголовка '{WRONG_SCHEDULE_TITLE}'.",
            EventImporter.find_schedule,
            WRONG_SCHEDULE_TITLE,
        )

    def test_find_schedule_semester(self):
        self.assertEqual(
            EventImporter.find_schedule(
                "Учебные занятия 4 курса ФЭВТ бакалавриат на II-ой семестр 2024-2025 учебного года"
            ),
            Schedule.objects.get(
                schedule_template__metadata__faculty="ФЭВТ",
                schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
                metadata__course=4,
                metadata__semester=2,
            ),
        )
        self.assertEqual(
            EventImporter.find_schedule(
                "Учебные занятия 4 курса ФЭВТ бакалавриат на 2семестр 2024-2025 учебного года"
            ),
            Schedule.objects.get(
                schedule_template__metadata__faculty="ФЭВТ",
                schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
                metadata__course=4,
                metadata__semester=2,
            ),
        )
        self.assertEqual(
            EventImporter.find_schedule(
                "Учебные занятия 2 курса ФЭВТ магистров 1-ого семестра 2024-2025 учебного года"
            ),
            Schedule.objects.get(
                schedule_template__metadata__faculty="ФЭВТ",
                schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.MASTER,
                metadata__course=2,
                metadata__semester=1,
            ),
        )
        self.assertEqual(
            EventImporter.find_schedule(
                "Учебные занятия 1 курса ФЭВТ аспирантов II-огосеместра 2024-2025 учебного года"
            ),
            Schedule.objects.get(
                schedule_template__metadata__faculty="ФЭВТ",
                schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.POSTGRADUATE,
                metadata__course=1,
                metadata__semester=2,
            ),
        )

    def test_find_schedule_course(self):
        self.assertEqual(
            EventImporter.find_schedule("ФЭВТ 4ыйкурс бакалавр. 2 семестра 2024-2025"),
            Schedule.objects.get(
                schedule_template__metadata__faculty="ФЭВТ",
                schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
                metadata__course=4,
                metadata__semester=2,
            ),
        )
        self.assertEqual(
            EventImporter.find_schedule("ФЭВТ 2-ого курса  Магистров 1ый семестр 2024-2025"),
            Schedule.objects.get(
                schedule_template__metadata__faculty="ФЭВТ",
                schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.MASTER,
                metadata__course=2,
                metadata__semester=1,
            ),
        )
        self.assertEqual(
            EventImporter.find_schedule(
                "Учебные занятия 1ый курс ФЭВТ аспиранты 2-ой семестр 2024-2025 учебного года"
            ),
            Schedule.objects.get(
                schedule_template__metadata__faculty="ФЭВТ",
                schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.POSTGRADUATE,
                metadata__course=1,
                metadata__semester=2,
            ),
        )

    def test_find_schedule_upper_and_lower_chars(self):
        # TODO: ФАСТиВ
        pass

    def test_correct_holds_on_date_data(self):
        SCHEDULE = Schedule.objects.get(
            schedule_template__metadata__faculty="ФЭВТ",
            schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
            metadata__course=4,
            metadata__semester=2,
        )

        self.assertEqual(
            EventImporter.correct_holds_on_date_data(
                SCHEDULE, ["10.09.2001", "11.09.2002", "12.09.2003", "14.09.2004"]
            ),
            None,
        )
        self.assertEqual(
            EventImporter.correct_holds_on_date_data(
                SCHEDULE,
                [
                    "12.09.1999",
                    "04.09..02.10",
                    "12.07;12.08",
                    "05.09",
                    "с 03.09",
                ],
            ),
            sorted(
                [
                    "12.09.1999",
                    "04.09.2024",
                    "18.09.2024",
                    "02.10.2024",
                    "12.07.2024",
                    "12.08.2024",
                    "05.09.2024",
                    "03.09.2024",
                    "17.09.2024",
                    "01.10.2024",
                    "15.10.2024",
                    "29.10.2024",
                    "12.11.2024",
                    "26.11.2024",
                    "10.12.2024",
                    "24.12.2024",
                    "07.01.2025",
                    "21.01.2025",
                ]
            ),
        )

        self.assertEqual(
            EventImporter.correct_holds_on_date_data(
                SCHEDULE,
                ["10.09.1999", "11.09.1999", "04.09..02.10", "12.09.1999", "03.09", "14.09.1999"],
            ),
            sorted(
                [
                    "10.09.1999",
                    "11.09.1999",
                    "04.09.2024",
                    "18.09.2024",
                    "02.10.2024",
                    "12.09.1999",
                    "03.09.2024",
                    "14.09.1999",
                ]
            ),
        )

    def test_correct_holds_on_date_data_double_range(self):
        SCHEDULE = Schedule.objects.get(
            schedule_template__metadata__faculty="ФЭВТ",
            schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
            metadata__course=4,
            metadata__semester=2,
        )

        self.assertEqual(
            EventImporter.correct_holds_on_date_data(SCHEDULE, ["03.09..01.10"]),
            sorted(["03.09.2024", "17.09.2024", "01.10.2024"]),
        )
        self.assertEqual(
            EventImporter.correct_holds_on_date_data(SCHEDULE, ["03.09..01.10", "03.09..01.10"]),
            sorted(["03.09.2024", "17.09.2024", "01.10.2024"]),
        )

    def test_correct_holds_on_date_data_single_range(self):
        SCHEDULE = Schedule.objects.get(
            schedule_template__metadata__faculty="ФЭВТ",
            schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
            metadata__course=4,
            metadata__semester=2,
        )

        self.assertEqual(
            EventImporter.correct_holds_on_date_data(SCHEDULE, ["с 03.09"]),
            sorted(
                [
                    "03.09.2024",
                    "17.09.2024",
                    "01.10.2024",
                    "15.10.2024",
                    "29.10.2024",
                    "12.11.2024",
                    "26.11.2024",
                    "10.12.2024",
                    "24.12.2024",
                    "07.01.2025",
                    "21.01.2025",
                ]
            ),
        )
        self.assertEqual(
            EventImporter.correct_holds_on_date_data(SCHEDULE, ["с 03.09", "с 03.09"]),
            sorted(
                [
                    "03.09.2024",
                    "17.09.2024",
                    "01.10.2024",
                    "15.10.2024",
                    "29.10.2024",
                    "12.11.2024",
                    "26.11.2024",
                    "10.12.2024",
                    "24.12.2024",
                    "07.01.2025",
                    "21.01.2025",
                ]
            ),
        )

    def test_correct_holds_on_date_data_colon(self):
        SCHEDULE = Schedule.objects.get(
            schedule_template__metadata__faculty="ФЭВТ",
            schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
            metadata__course=4,
            metadata__semester=2,
        )

        self.assertEqual(
            EventImporter.correct_holds_on_date_data(SCHEDULE, ["12.09;10.10;07.11;05.12"]),
            sorted(["12.09.2024", "10.10.2024", "07.11.2024", "05.12.2024"]),
        )
        self.assertEqual(
            EventImporter.correct_holds_on_date_data(
                SCHEDULE, [" 13.09;  11.10  ; 08.11 ;06.12   "]
            ),
            sorted(["13.09.2024", "11.10.2024", "08.11.2024", "06.12.2024"]),
        )

    def test_correct_holds_on_date_data_add_year(self):
        SCHEDULE = Schedule.objects.get(
            schedule_template__metadata__faculty="ФЭВТ",
            schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
            metadata__course=4,
            metadata__semester=2,
        )

        self.assertEqual(
            EventImporter.correct_holds_on_date_data(SCHEDULE, ["03.09"]), ["03.09.2024"]
        )
        self.assertEqual(
            EventImporter.correct_holds_on_date_data(SCHEDULE, ["12.12."]), ["12.12.2024"]
        )
        self.assertEqual(
            EventImporter.correct_holds_on_date_data(SCHEDULE, ["03.09", "03.09", "04.09"]),
            sorted(["03.09.2024", "04.09.2024"]),
        )

    def test_make_calendar(self):
        SCHEDULE = Schedule.objects.get(
            schedule_template__metadata__faculty="ФЭВТ",
            schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
            metadata__course=4,
            metadata__semester=2,
        )
        MONTHS = ["февраль", "март", "апрель", "май", "июнь", "сентябрь"]
        weeks_as_dict = {
            "first_week": [
                {
                    "week_day_index": 0,
                    "calendar": [
                        {"month_index": 0, "month_days": ["1", "15"]},
                        {"month_index": 1, "month_days": ["20", "28"]},
                    ],
                }
            ],
            "second_week": [
                {"week_day_index": 0, "calendar": [{"month_index": 0, "month_days": ["8", "22"]}]},
                {"week_day_index": 1, "calendar": [{"month_index": 0, "month_days": ["9", "23"]}]},
            ],
        }
        weeks_as_list = [
            {
                "first_week": [
                    {
                        "week_day_index": 0,
                        "calendar": [
                            {"month_index": 0, "month_days": ["1", "15"]},
                            {"month_index": 1, "month_days": ["20", "28"]},
                        ],
                    }
                ]
            },
            {
                "second_week": [
                    {
                        "week_day_index": 0,
                        "calendar": [{"month_index": 0, "month_days": ["8", "22"]}],
                    },
                    {
                        "week_day_index": 1,
                        "calendar": [{"month_index": 0, "month_days": ["9", "23"]}],
                    },
                ]
            },
        ]

        FIRST_WEEK_EXPECTED_RESULT = {
            "first_week": {
                0: [
                    datetime.strptime("1.02.2025", "%d.%m.%Y").date(),
                    datetime.strptime("15.02.2025", "%d.%m.%Y").date(),
                    datetime.strptime("20.03.2025", "%d.%m.%Y").date(),
                    datetime.strptime("28.03.2025", "%d.%m.%Y").date(),
                ]
            }
        }
        SECOND_WEEK_EXPECTED_RESULT = {
            "second_week": {
                0: [
                    datetime.strptime("8.02.2025", "%d.%m.%Y").date(),
                    datetime.strptime("22.02.2025", "%d.%m.%Y").date(),
                ],
                1: [
                    datetime.strptime("9.02.2025", "%d.%m.%Y").date(),
                    datetime.strptime("23.02.2025", "%d.%m.%Y").date(),
                ],
            }
        }
        expected_result: dict = {}
        expected_result.update(FIRST_WEEK_EXPECTED_RESULT)
        expected_result.update(SECOND_WEEK_EXPECTED_RESULT)

        self.assertEqual(
            EventImporter.make_calendar(weeks_as_dict, MONTHS, SCHEDULE), expected_result
        )
        self.assertEqual(
            EventImporter.make_calendar(weeks_as_list, MONTHS, SCHEDULE), expected_result
        )

        weeks_as_dict.pop("first_week")
        weeks_as_list.pop(1)

        self.assertEqual(
            EventImporter.make_calendar(weeks_as_dict, MONTHS, SCHEDULE),
            SECOND_WEEK_EXPECTED_RESULT,
        )
        self.assertEqual(
            EventImporter.make_calendar(weeks_as_list, MONTHS, SCHEDULE), FIRST_WEEK_EXPECTED_RESULT
        )

        self.assertEqual(
            EventImporter.make_calendar(
                {
                    "first_week": [
                        {
                            "week_day_index": 0,
                            "calendar": [
                                {"month_index": 0, "month_days": ["1"]},
                                {"month_index": 1, "month_days": ["1"]},
                            ],
                        }
                    ]
                },
                ["декабрь", "февраль"],
                SCHEDULE,
            ),
            {
                "first_week": {
                    0: [
                        datetime.strptime("1.12.2024", "%d.%m.%Y").date(),
                        datetime.strptime("1.02.2025", "%d.%m.%Y").date(),
                    ]
                }
            },
        )

        self.assertRaises(ValueError, EventImporter.make_calendar, set(), MONTHS, SCHEDULE)
        self.assertRaises(
            ValueError, EventImporter.make_calendar, [["qwe"], ["asd"]], MONTHS, SCHEDULE
        )
        self.assertRaises(ValueError, EventImporter.make_calendar, {}, MONTHS, SCHEDULE)

    def test_create_events(self):
        SCHEDULE = Schedule.objects.get(
            schedule_template__metadata__faculty="ФЭВТ",
            schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
            metadata__course=4,
            metadata__semester=2,
        )
        DEPARTMENT = Department.objects.get(shortname="ФЭВТ")
        CALENDAR = [
            datetime.strptime("1.02.2025", "%d.%m.%Y").date(),
            datetime.strptime("15.02.2025", "%d.%m.%Y").date(),
        ]
        KIND = EventKind.objects.create(name="Лекция")
        SUBJECT = Subject.objects.create(name="ВКР")
        PARTICIPANTS = [
            EventParticipant.objects.create(
                name="Гилка В.В.",
                role=EventParticipant.Role.TEACHER,
                is_group=False,
                department=DEPARTMENT,
            ),
            EventParticipant.objects.create(
                name="ПрИн-466",
                role=EventParticipant.Role.STUDENT,
                is_group=True,
                department=DEPARTMENT,
            ),
        ]
        PLACES = [EventPlace.objects.create(building="В", room="902")]
        TIME_SLOTS = [TimeSlot.objects.get(alt_name="1-2"), TimeSlot.objects.get(alt_name="3-4")]

        EventImporter.create_events(
            SCHEDULE,
            KIND,
            SUBJECT,
            PARTICIPANTS,
            PLACES,
            AbstractDay.objects.get(day_number=0),
            TIME_SLOTS,
            [None],
            CALENDAR,
        )

        self.assertEqual(AbstractEvent.objects.all().count(), 2)
        self.assertEqual(Event.objects.all().count(), 4)

        # trying to create duplicate
        EventImporter.create_events(
            SCHEDULE,
            KIND,
            SUBJECT,
            PARTICIPANTS,
            PLACES,
            AbstractDay.objects.get(day_number=0),
            TIME_SLOTS,
            [None],
            CALENDAR,
        )

        self.assertEqual(AbstractEvent.objects.all().count(), 2)
        self.assertEqual(Event.objects.all().count(), 4)

        # still able to create AbstractEvents with holds_on_date
        # method creates 4 AbstractEvents (for 2 holds_on_date with 2 time_slots)
        # and 4 Events
        EventImporter.create_events(
            SCHEDULE,
            KIND,
            SUBJECT,
            PARTICIPANTS,
            PLACES,
            AbstractDay.objects.get(day_number=0),
            TIME_SLOTS,
            [
                datetime.strptime("10.03.2025", "%d.%m.%Y").date(),
                datetime.strptime("11.03.2025", "%d.%m.%Y").date(),
            ],
            [],
        )

        self.assertEqual(AbstractEvent.objects.all().count(), 6)
        self.assertEqual(Event.objects.all().count(), 8)

        # trying to create duplicate
        EventImporter.create_events(
            SCHEDULE,
            KIND,
            SUBJECT,
            PARTICIPANTS,
            PLACES,
            AbstractDay.objects.get(day_number=0),
            TIME_SLOTS,
            [
                datetime.strptime("10.03.2025", "%d.%m.%Y").date(),
                datetime.strptime("11.03.2025", "%d.%m.%Y").date(),
            ],
            [],
        )

        self.assertEqual(AbstractEvent.objects.all().count(), 6)
        self.assertEqual(Event.objects.all().count(), 8)

    def test_import_data(self):
        IMPORT_DATA = """
            {
                "title": "Учебные занятия 4 курса ФЭВТ бакалавриат на 2 семестр 2024-2025 учебного года",
                "table": {
                    "grid": [
                        {
                            "subject": "ВКР",
                            "kind": "лекция",
                            "participants": {
                                "teachers": [
                                    "Гилка В.В.",
                                    "Кузнецова А.С."
                                ],
                                "student_groups": [
                                    "ИВТ-460"
                                ]
                            },
                            "places": [
                                "В 902а",
                                "В 902б"
                            ],
                            "hours": [
                                "11-12",
                                "8.30",
                                "10.10"
                            ],
                            "week_day_index": 0,
                            "week": "first_week",
                            "holds_on_date": [
                                "09.11.2024"
                            ]
                        },
                        {
                            "subject": "МИКРОПРОЦЕССОРЫ",
                            "kind": "лабораторная работа",
                            "participants": {
                                "teachers": [
                                    "Синкевич Д.",
                                    "Дмитриев А.С."
                                ],
                                "student_groups": [
                                    "ПрИн-466",
                                    "ПрИн-467"
                                ]
                            },
                            "places": [
                                "В 903",
                                "В 908"
                            ],
                            "hours": [
                                "11.50 - 13:20"
                            ],
                            "week_day_index": 1,
                            "week": "second_week",
                            "holds_on_date": []
                        }
                    ],
                    "datetime": {
                        "weeks": {
                            "first_week": [
                                {
                                    "week_day_index": 0,
                                    "calendar": [
                                        {
                                            "month_index": 0,
                                            "month_days": [
                                                "1", 
                                                "15"
                                            ]
                                        },
                                        {
                                            "month_index": 1,
                                            "month_days": [
                                                "20", 
                                                "28"
                                            ]
                                        }
                                    ]
                                }
                            ],
                            "second_week": [
                                {
                                    "week_day_index": 0,
                                    "calendar": [
                                        {
                                            "month_index": 0,
                                            "month_days": [
                                                "8", 
                                                "22"
                                            ]
                                        }
                                    ]
                                },
                                {
                                    "week_day_index": 1,
                                    "calendar": [
                                        {
                                            "month_index": 0,
                                            "month_days": [
                                                "9", 
                                                "23"
                                            ]
                                        }
                                    ]
                                }
                            ]
                        },
                        "week_days": [
                            "ПОНЕДЕЛЬНИК",
                            "ВТОРНИК",
                            "СРЕДА",
                            "ЧЕТВЕРГ",
                            "ПЯТНИЦА",
                            "СУББОТА"
                        ],
                        "months": [
                            "февраль",
                            "март",
                            "апрель",
                            "май",
                            "июнь",
                            "сентябрь"
                        ]
                    }
                }
            }
        """

        EventImporter.import_events(IMPORT_DATA)

        try:
            self.assertNotEqual(
                Event.objects.filter(
                    **TimeSlotFilter.from_display_name_event_relative("11-12")
                ).first(),
                None,
            )
            self.assertNotEqual(
                Event.objects.filter(
                    **TimeSlotFilter.from_display_name_event_relative("11:50")
                ).first(),
                None,
            )
            self.assertNotEqual(
                Event.objects.filter(
                    **TimeSlotFilter.from_display_name_event_relative("17:00")
                ).first(),
                None,
            )
        except Event.DoesNotExist:
            self.fail()

        try:
            self.assertNotEqual(
                AbstractEvent.objects.filter(
                    **TimeSlotFilter.from_display_name_abstract_event_relative("11-12")
                ).first(),
                None,
            )
            self.assertNotEqual(
                AbstractEvent.objects.filter(
                    **TimeSlotFilter.from_display_name_abstract_event_relative("11:50")
                ).first(),
                None,
            )
            self.assertNotEqual(
                AbstractEvent.objects.filter(
                    **TimeSlotFilter.from_display_name_abstract_event_relative("17:00")
                ).first(),
                None,
            )
            self.assertNotEqual(
                AbstractEvent.objects.filter(participants__name="Гилка В.В.").first(), None
            )
            self.assertNotEqual(
                AbstractEvent.objects.filter(
                    participants__name="ИВТ-460", participants__role="student"
                ).first(),
                None,
            )
        except AbstractEvent.DoesNotExist:
            self.fail()

        try:
            self.assertNotEqual(
                TimeSlot.objects.get(**TimeSlotFilter.by_start_time("17:00")[0]), None
            )
            self.assertNotEqual(
                TimeSlot.objects.get(**TimeSlotFilter.by_start_time("10:10")[0]), None
            )
        except TimeSlot.DoesNotExist:
            self.fail()

        try:
            self.assertNotEqual(
                EventPlace.objects.get(**PlaceFilter.by_building_and_room("В 902а")), None
            )
        except EventPlace.DoesNotExist:
            self.fail()

    def test_collect_reference_data(self):
        REFERENCE_DATA = [
            {
                "subject": "ВКР",
                "kind": "лекция",
                "participants": {
                    "teachers": ["Гилка В.В.", "Кузнецова А.С."],
                    "student_groups": ["ИВТ-460"],
                },
                "places": ["В 902а", "В 902б"],
                "hours": ["1-2", "3-4"],
                "week_day_index": 0,
                "week": "first_week",
                "holds_on_date": ["09.11.2024"],
            },
            {
                "subject": "МИКРОПРОЦЕССОРЫ",
                "kind": "лабораторная работа",
                "participants": {
                    "teachers": ["Синкевич Д.", "Дмитриев А.С."],
                    "student_groups": ["ПрИн-466", "ПрИн-467"],
                },
                "places": ["ГУК101", "312"],
                "hours": ["18.30", "11:11 -  12.01"],
                "week_day_index": 1,
                "week": "second_week",
                "holds_on_date": [],
            },
        ]
        EXPECTED_REFERENCE_DATA = [
            {
                "subjects": {"ВКР"},
                "kinds": {"Лекция"},
                "teachers": {"Гилка В.В.", "Кузнецова А.С."},
                "groups": {"ИВТ-460"},
                "places": {("В", "902а"), ("В", "902б")},
                "time_slots": {
                    ("1-2", "", ""),
                    ("3-4", "", ""),
                },
            },
            {
                "subjects": {"МИКРОПРОЦЕССОРЫ"},
                "kinds": {"Лабораторная работа"},
                "teachers": {"Синкевич Д.", "Дмитриев А.С."},
                "groups": {"ПрИн-466", "ПрИн-467"},
                "places": {("", "ГУК101"), ("", "312")},
                "time_slots": {
                    ("", "18:30", ""),
                    ("", "11:11", "12:01"),
                },
            },
        ]

        for i in range(0, 2):
            return_value = EventImporter.collect_reference_data(REFERENCE_DATA[i])

            self.assertEqual(return_value, EXPECTED_REFERENCE_DATA[i])

    def test_make_reference_lookup(self):
        # with empty reference_lookup

        INPUT_REFERENCE_DATA = {
            "subjects": {"ВКР", "МИКРОПРОЦЕССОРЫ"},
            "kinds": {"Лекция", "Лабораторная работа"},
            "teachers": {"Гилка В.В.", "Кузнецова А.С.", "Синкевич Д.", "Дмитриев А.С."},
            "groups": {"ИВТ-460", "ПрИн-466", "ПрИн-467"},
            "places": {("Й", "111"), ("Ц", "222"), ("", "ЯЧС333"), ("", "444"), ("", "exist")},
            "time_slots": {
                ("1-2", "8:30", ""),  # Must not create duplicative time_slot created in SetUp()
                ("", "11:55", ""),
                ("5-6", "13:40", "14:01"),
                ("", "15:09", "15:10"),
                ("11-12", "", ""),  # Using common time_slot created in SetUp()
            },
        }

        reference_lookup = {
            "subjects": {},
            "kinds": {},
            "participants": {},
            "places": {},
            "time_slots": TimeSlot.objects.none(),
        }

        EventPlace.objects.create(building="", room="exist")

        INIT_TIME_SLOTS_COUNT = TimeSlot.objects.all().count()

        EventImporter.make_reference_lookup(INPUT_REFERENCE_DATA, reference_lookup)

        try:
            self.assertEqual(EventPlace.objects.all().count(), 5)
            self.assertEqual(len(reference_lookup["places"]), 5)
            self.assertNotEqual(EventPlace.objects.get(building="Й", room="111"), None)
            self.assertNotEqual(EventPlace.objects.get(building="Ц", room="222"), None)
            self.assertNotEqual(EventPlace.objects.get(room="ЯЧС333"), None)
            self.assertNotEqual(EventPlace.objects.get(room="444"), None)
        except EventPlace.DoesNotExist:
            self.fail()

        try:
            self.assertEqual(TimeSlot.objects.all().count(), INIT_TIME_SLOTS_COUNT + 3)
            self.assertEqual(reference_lookup["time_slots"].count(), 5)
            self.assertNotEqual(TimeSlot.objects.get(alt_name="1-2", start_time="8:30"), None)
            self.assertNotEqual(
                reference_lookup["time_slots"].get(alt_name="1-2", start_time="8:30"), None
            )
            self.assertNotEqual(
                TimeSlot.objects.get(alt_name="", start_time="11:55", end_time__isnull=True), None
            )
            self.assertNotEqual(
                reference_lookup["time_slots"].get(
                    alt_name="", start_time="11:55", end_time__isnull=True
                ),
                None,
            )
            self.assertNotEqual(
                TimeSlot.objects.get(alt_name="5-6", start_time="13:40", end_time="14:01"), None
            )
            self.assertNotEqual(
                reference_lookup["time_slots"].get(
                    alt_name="5-6", start_time="13:40", end_time="14:01"
                ),
                None,
            )
            self.assertNotEqual(
                TimeSlot.objects.get(alt_name="", start_time="15:09", end_time="15:10"), None
            )
            self.assertNotEqual(
                reference_lookup["time_slots"].get(
                    alt_name="", start_time="15:09", end_time="15:10"
                ),
                None,
            )
            self.assertNotEqual(reference_lookup["time_slots"].get(alt_name="11-12"), None)
        except TimeSlot.DoesNotExist:
            self.fail()

        # Duplicates test
        for subject in Subject.objects.all():
            self.assertEqual(Subject.objects.filter(name=subject.name).count(), 1)
        for kind in EventKind.objects.all():
            self.assertEqual(EventKind.objects.filter(name=kind.name).count(), 1)
        for participant in EventParticipant.objects.all():
            self.assertEqual(EventParticipant.objects.filter(name=participant.name).count(), 1)
        for place in EventPlace.objects.all():
            self.assertEqual(
                EventPlace.objects.filter(building=place.building, room=place.room).count(), 1
            )
        for time_slot in TimeSlot.objects.all():
            self.assertEqual(
                TimeSlot.objects.filter(
                    alt_name=time_slot.alt_name,
                    start_time=time_slot.start_time,
                    end_time=time_slot.end_time,
                ).count(),
                1,
            )

    def test_import_events_for_only_active_schedule(self):
        IMPORT_DATA = """
            {
                "title": "Учебные занятия 4 курса ФЭВТ бакалавриат на 2 семестр 2024-2025 учебного года",
                "table": {
                    "grid": [
                        {
                            "subject": "ВКР",
                            "kind": "лекция",
                            "participants": {
                                "teachers": [
                                    "Гилка В.В.",
                                    "Кузнецова А.С."
                                ],
                                "student_groups": [
                                    "ИВТ-460"
                                ]
                            },
                            "places": [
                                "В 902а",
                                "В 902б"
                            ],
                            "hours": [
                                "11-12",
                                "8.30",
                                "10.10"
                            ],
                            "week_day_index": 0,
                            "week": "first_week",
                            "holds_on_date": [
                                "09.11.2024"
                            ]
                        },
                        {
                            "subject": "МИКРОПРОЦЕССОРЫ",
                            "kind": "лабораторная работа",
                            "participants": {
                                "teachers": [
                                    "Синкевич Д.",
                                    "Дмитриев А.С."
                                ],
                                "student_groups": [
                                    "ПрИн-466",
                                    "ПрИн-467"
                                ]
                            },
                            "places": [
                                "В 903",
                                "В 908"
                            ],
                            "hours": [
                                "11.50 - 13:20"
                            ],
                            "week_day_index": 1,
                            "week": "second_week",
                            "holds_on_date": []
                        }
                    ],
                    "datetime": {
                        "weeks": {
                            "first_week": [
                                {
                                    "week_day_index": 0,
                                    "calendar": [
                                        {
                                            "month_index": 0,
                                            "month_days": [
                                                "1", 
                                                "15"
                                            ]
                                        },
                                        {
                                            "month_index": 1,
                                            "month_days": [
                                                "20", 
                                                "28"
                                            ]
                                        }
                                    ]
                                }
                            ],
                            "second_week": [
                                {
                                    "week_day_index": 0,
                                    "calendar": [
                                        {
                                            "month_index": 0,
                                            "month_days": [
                                                "8", 
                                                "22"
                                            ]
                                        }
                                    ]
                                },
                                {
                                    "week_day_index": 1,
                                    "calendar": [
                                        {
                                            "month_index": 0,
                                            "month_days": [
                                                "9", 
                                                "23"
                                            ]
                                        }
                                    ]
                                }
                            ]
                        },
                        "week_days": [
                            "ПОНЕДЕЛЬНИК",
                            "ВТОРНИК",
                            "СРЕДА",
                            "ЧЕТВЕРГ",
                            "ПЯТНИЦА",
                            "СУББОТА"
                        ],
                        "months": [
                            "февраль",
                            "март",
                            "апрель",
                            "май",
                            "июнь",
                            "сентябрь"
                        ]
                    }
                }
            }
        """

        INIT_SCHEDULE_COUNT = Schedule.objects.all().count()

        ReferenceImporter.import_schedule(self.SCHEDULE_REFERENCE_DATA, True)

        try:
            self.assertEqual(Schedule.objects.all().count(), INIT_SCHEDULE_COUNT + 3)
            self.assertEqual(
                Schedule.objects.filter(status=Schedule.Status.ACTIVE).count(), INIT_SCHEDULE_COUNT
            )
            self.assertEqual(
                Schedule.objects.filter(status=Schedule.Status.ARCHIVE).count(), INIT_SCHEDULE_COUNT
            )
        except Schedule.DoesNotExist:
            self.fail()

        EventImporter.import_events(IMPORT_DATA)

        try:
            self.assertEqual(
                AbstractEvent.objects.filter(schedule__status=Schedule.Status.ACTIVE).count(),
                AbstractEvent.objects.all().count(),
            )
            self.assertEqual(
                AbstractEvent.objects.filter(schedule__status=Schedule.Status.ARCHIVE).count(), 0
            )
        except AbstractEvent.DoesNotExist:
            self.fail()

    def test_import_almost_similar_events(self):
        """Тест проверяет возникшую ранее ошибку,
        когда проверка на существование (защита от дублирования) событий
        некорректно сравнивала "участников" и "места" лишь по одному вхождению
        """

        SCHEDULE_TEST_REFERENCE_DATA = """
                [
                    {
                        "course": "2",
                        "schedule_template_metadata_faculty_shortname": "ФЭВТ",
                        "semester": "1",
                        "years": "2026-2027",
                        "start_date": "01.09.2026",
                        "end_date": "01.02.2027",
                        "scope": "магистратура",
                        "department_shortname": "ФЭВТ",
                        "original_title": "Учебные занятия 2 курса магистратура ФЭВТ на I семестр 2026-2027 учебного года"
                    }
                ]
            """

        ReferenceImporter.import_schedule(SCHEDULE_TEST_REFERENCE_DATA, True)

        schedule = Schedule.objects.get(
            schedule_template__metadata__faculty="ФЭВТ",
            schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.MASTER,
            metadata__years="2026-2027",
            metadata__course=2,
            metadata__semester=1,
        )
        schedule.starting_day_number = AbstractDay.objects.get(day_number=1)
        schedule.save()

        with open("apps/common/tests/data/test_import_2.json", "r", encoding="utf8") as data_file:
            EventImporter.import_events(data_file.read())

        try:
            self.assertNotEqual(
                Event.objects.filter(
                    subject_override__name="ФИЛОСОФИЯ И МЕТОДОЛОГИЯ НАУКИ",
                    participants_override__name__in=["ПОАС-2.1", "ПОАС-2.2"],
                    date=datetime.strptime("11.09.2026", "%d.%m.%Y").date(),
                ).count(),
                0,
            )
        except Event.DoesNotExist:
            self.fail()

    # test_import_event_for_not_existing_time_slot


class TestReferenceImporter(TestCase):
    def test_place_import_reference(self):
        PLACE_REFERENCE_DATA = """
            {
                "places": [
                    "002",
                    "КЦ УНЦ",
                    "В-1402-3",
                    "Б-205а",
                    "ГУК101"
                ]
            }
        """

        ReferenceImporter.import_place_reference(PLACE_REFERENCE_DATA)

        try:
            self.assertNotEqual(
                EventPlace.objects.get(**PlaceFilter.by_building_and_room("002")), None
            )
            self.assertNotEqual(
                EventPlace.objects.get(**PlaceFilter.by_building_and_room("КЦ УНЦ")), None
            )
            self.assertNotEqual(
                EventPlace.objects.get(**PlaceFilter.by_building_and_room("В-1402-3")), None
            )
            self.assertNotEqual(
                EventPlace.objects.get(**PlaceFilter.by_building_and_room("Б-205а")), None
            )
            self.assertNotEqual(
                EventPlace.objects.get(**PlaceFilter.by_building_and_room("ГУК101")), None
            )
        except EventPlace.DoesNotExist:
            self.fail()

    def test_import_same_place_reference(self):
        PLACE_REFERENCE_DATA = """
            {
                "places": [
                    "В-902а",
                    "В 902а",
                    "В,902а"
                ]
            }
        """

        ReferenceImporter.import_place_reference(PLACE_REFERENCE_DATA)

        try:
            self.assertEqual(EventPlace.objects.all().count(), 1)
            self.assertNotEqual(EventPlace.objects.get(building="В", room="902а"), None)
        except EventPlace.DoesNotExist:
            self.fail()

    def test_import_duplicate_place_reference(self):
        PLACE_REFERENCE_DATA = """
            {
                "places": [
                    "002",
                    "002",
                    "КЦ УНЦ",
                    "В-1402-3",
                    "Б-205а",
                    "ГУК101"
                ]
            }
        """

        ReferenceImporter.import_place_reference(PLACE_REFERENCE_DATA)
        ReferenceImporter.import_place_reference(PLACE_REFERENCE_DATA)

        try:
            self.assertEqual(EventPlace.objects.all().count(), 5)
        except EventPlace.DoesNotExist:
            self.fail()

    def test_faculty_import_reference(self):
        FACULTY_REFERENCE_DATA = """
            [
                {
                    "faculty_id" : "0",
                    "faculty_fullname" : "Информационно-библиотечный центр",
                    "faculty_code" : "0000",
                    "faculty_shortname" : "ИБЦ"
                },
                {
                    "faculty_id" : "1",
                    "faculty_fullname" : "Факультет автоматизированных систем, транспорта и вооружений",
                    "faculty_code" : "0001",
                    "faculty_shortname" : "ФАСТиВ"
                },
                {
                    "faculty_id" : "2",
                    "faculty_fullname" : "Факультет автомобильного транспорта",
                    "faculty_code" : "0002",
                    "faculty_shortname" : "ФАТ"
                }
            ]
        """

        Organization.objects.create(name="ВолгГТУ")

        ReferenceImporter.import_faculty_reference(FACULTY_REFERENCE_DATA)

        try:
            self.assertEqual(Department.objects.all().count(), 3)
            self.assertEqual(Department.objects.filter(parent_department__isnull=True).count(), 3)
            self.assertNotEqual(Department.objects.get(shortname="ФАСТиВ"), None)
            self.assertNotEqual(Department.objects.get(code="2"), None)
        except Department.DoesNotExist:
            self.fail()

    def test_faculty_import_duplicate_reference(self):
        FACULTY_REFERENCE_DATA = """
            [
                {
                    "faculty_id" : "106",
                    "faculty_fullname" : "Факультет электроники и вычислительной техники",
                    "faculty_code" : "000000157",
                    "faculty_shortname" : "ФЭВТ"
                },
                {
                    "faculty_id" : "106",
                    "faculty_fullname" : "Факультет электроники и вычислительной техники",
                    "faculty_code" : "000000157",
                    "faculty_shortname" : "ФЭВТ"
                }
            ]
        """

        Organization.objects.create(name="ВолгГТУ")

        ReferenceImporter.import_faculty_reference(FACULTY_REFERENCE_DATA)
        ReferenceImporter.import_faculty_reference(FACULTY_REFERENCE_DATA)

        try:
            self.assertEqual(Department.objects.all().count(), 1)
        except Department.DoesNotExist:
            self.fail()

    def test_department_import_reference_with_missing_parent(self):
        FACULTY_REFERENCE_DATA = """
            [
                {
                    "faculty_id" : "111",
                    "faculty_fullname" : "Факультет электроники и вычислительной техники",
                    "faculty_code" : "000000111",
                    "faculty_shortname" : "ФЭВТ"
                },
                {
                    "faculty_id" : "222",
                    "faculty_fullname" : "Химико-технологический факультет",
                    "faculty_code" : "000000222",
                    "faculty_shortname" : "ХТФ"
                }
            ]
        """
        DEPARTMENT_REFERENCE_DATA = """
            [
                {
                    "department_id" : "0",
                    "department_code" : "000000000",
                    "department_fullname" : "Кафедра Автоматизация производственных процессов",
                    "department_shortname" : "АПП",
                    "faculty_id" : "111",
                    "faculty_shortname" : "ФЭВТ"
                },
                {
                    "department_id" : "1",
                    "department_code" : "000000001",
                    "department_fullname" : "Кафедра Автоматические установки",
                    "department_shortname" : "АУ",
                    "faculty_id" : "333",
                    "faculty_shortname" : "ТАКОГО ФАКУЛЬТЕТА НЕТ"
                }
            ]
        """

        Organization.objects.create(name="ВолгГТУ")

        ReferenceImporter.import_faculty_reference(FACULTY_REFERENCE_DATA)
        ReferenceImporter.import_department_reference(DEPARTMENT_REFERENCE_DATA)

        try:
            self.assertEqual(
                Department.objects.filter(parent_department__isnull=True).count(), 3
            )  # 2 faculty + 1 department
            self.assertEqual(Department.objects.filter(parent_department__isnull=False).count(), 1)
            self.assertNotEqual(Department.objects.get(shortname="ФЭВТ"), None)
            self.assertNotEqual(Department.objects.get(parent_department__code="111"), None)
            self.assertEqual(
                Department.objects.get(code="000000001").name, "Кафедра Автоматические установки"
            )
        except Department.DoesNotExist:
            self.fail()

    def test_department_import_reference(self):
        FACULTY_REFERENCE_DATA = """
            [
                {
                    "faculty_id" : "106",
                    "faculty_fullname" : "Факультет электроники и вычислительной техники",
                    "faculty_code" : "000000157",
                    "faculty_shortname" : "ФЭВТ"
                }
            ]
        """
        DEPARTMENT_REFERENCE_DATA = """
            [
                {
                    "department_id" : "106",
                    "department_code" : "000000165",
                    "department_fullname" : "Кафедра Программное обеспечение автоматизированных систем",
                    "department_shortname" : "ПОАС",
                    "faculty_id" : "106",
                    "faculty_shortname" : "ФЭВТ"
                },
                {
                    "department_id" : "106",
                    "department_code" : "000000165",
                    "department_fullname" : "Кафедра Программное обеспечение автоматизированных систем",
                    "department_shortname" : "ПОАС",
                    "faculty_id" : "106",
                    "faculty_shortname" : "ФЭВТ"
                }
            ]
        """

        Organization.objects.create(name="ВолгГТУ")

        ReferenceImporter.import_faculty_reference(FACULTY_REFERENCE_DATA)
        ReferenceImporter.import_department_reference(DEPARTMENT_REFERENCE_DATA)
        ReferenceImporter.import_department_reference(DEPARTMENT_REFERENCE_DATA)

        try:
            self.assertEqual(Department.objects.filter(parent_department__isnull=False).count(), 1)
            self.assertEqual(Department.objects.filter(parent_department__isnull=True).count(), 1)
        except Department.DoesNotExist:
            self.fail()

    def test_subject_import_reference(self):
        SUBJECT_REFERENCE_DATA = """
        [
            {
                "discipline_code" : "000006700",
                "discipline_name" : "Динамика и устойчивость самоходного артиллерийского орудия",
                "discipline_shortname" : "ДИУСАО",
                "is_elective" : "Нет",
                "discipline_department_code" : "000000130",
                "discipline_department_id" : "2",
                "discipline_department_shortname" : "АУ"
            },
            {
                "discipline_code" : "000002373",
                "discipline_name" : "Основы проектирования WEB-приложений",
                "discipline_shortname" : "ОПW",
                "is_elective" : "Нет",
                "discipline_department_code" : "000000215",
                "discipline_department_id" : "210",
                "discipline_department_shortname" : "ВИТ"
            },
            {
                "discipline_code" : "000006579",
                "discipline_name" : "Экзамен по ПМ.05 'Организация деятельности подчиненного персонала'",
                "discipline_shortname" : "ЭПП'ДПП",
                "is_elective" : "Нет",
                "discipline_department_code" : "000000327",
                "discipline_department_id" : "329",
                "discipline_department_shortname" : "ТМ (КТИ)"
            }
        ]
        """

        ReferenceImporter.import_subject_reference(SUBJECT_REFERENCE_DATA)

        try:
            self.assertEqual(Subject.objects.all().count(), 3)
            self.assertNotEqual(
                Subject.objects.get(name="Основы проектирования WEB-приложений"), None
            )
            self.assertNotEqual(
                Subject.objects.get(
                    name="Экзамен по ПМ.05 'Организация деятельности подчиненного персонала'"
                ),
                None,
            )
        except Subject.DoesNotExist:
            self.fail()

    def test_subject_import_duplicate_reference(self):
        SUBJECT_REFERENCE_DATA = """
        [
            {
                "discipline_code" : "0",
                "discipline_name" : "НАЗВАНИЕ ПРЕДМЕТА",
                "discipline_shortname" : "ЙЦУКЕН",
                "is_elective" : "Нет",
                "discipline_department_code" : "1",
                "discipline_department_id" : "2",
                "discipline_department_shortname" : "ФЫВАПР"
            },
            {
                "discipline_code" : "0",
                "discipline_name" : "НАЗВАНИЕ ПРЕДМЕТА",
                "discipline_shortname" : "ЙЦУКЕН",
                "is_elective" : "Нет",
                "discipline_department_code" : "1",
                "discipline_department_id" : "2",
                "discipline_department_shortname" : "ФЫВАПР"
            }
        ]
        """

        ReferenceImporter.import_subject_reference(SUBJECT_REFERENCE_DATA)
        ReferenceImporter.import_subject_reference(SUBJECT_REFERENCE_DATA)

        try:
            self.assertEqual(Subject.objects.all().count(), 1)
        except Subject.DoesNotExist:
            self.fail()

    def test_teacher_import_reference(self):
        FACULTY_REFERENCE_DATA = """
            [
                {
                    "faculty_id" : "111",
                    "faculty_fullname" : "Факультет электроники и вычислительной техники",
                    "faculty_code" : "000000111",
                    "faculty_shortname" : "ФЭВТ"
                },
                {
                    "faculty_id" : "222",
                    "faculty_fullname" : "Химико-технологический факультет",
                    "faculty_code" : "000000222",
                    "faculty_shortname" : "ХТФ"
                }
            ]
        """
        TEACHER_REFERENCE_DATA = """
        [
            {
                "staff_department_code" : "111",
                "staff_department" : "Факультет электроники и вычислительной техники",
                "staff_code" : "000008945",
                "staff_surname" : "Рамасуббу",
                "staff_name" : "Сундер",
                "staff_patronymic" : ""
            },
            {
                "staff_department_code" : "222",
                "staff_department" : "Химико-технологический факультет",
                "staff_code" : "000008785",
                "staff_surname" : "Завьялов",
                "staff_name" : "Дмитрий",
                "staff_patronymic" : "Викторович"
            }
        ]
        """

        Organization.objects.create(name="ВолгГТУ")

        ReferenceImporter.import_faculty_reference(FACULTY_REFERENCE_DATA)
        ReferenceImporter.import_teacher_reference(TEACHER_REFERENCE_DATA)

        try:
            self.assertEqual(EventParticipant.objects.all().count(), 2)
            self.assertNotEqual(EventParticipant.objects.get(name="Рамасуббу С."), None)
            self.assertEqual(
                EventParticipant.objects.get(
                    role=EventParticipant.Role.TEACHER, department__code="222"
                ).name,
                "Завьялов Д.В.",
            )
        except EventParticipant.DoesNotExist:
            self.fail()

    def test_teacher_import_duplicate_reference(self):
        FACULTY_REFERENCE_DATA = """
            [
                {
                    "faculty_id" : "111",
                    "faculty_fullname" : "Факультет электроники и вычислительной техники",
                    "faculty_code" : "000000111",
                    "faculty_shortname" : "ФЭВТ"
                },
                {
                    "faculty_id" : "222",
                    "faculty_fullname" : "Химико-технологический факультет",
                    "faculty_code" : "000000222",
                    "faculty_shortname" : "ХТФ"
                }
            ]
        """
        TEACHER_REFERENCE_DATA = """
        [
            {
                "staff_department_code" : "222",
                "staff_department" : "Химико-технологический факультет",
                "staff_code" : "000008785",
                "staff_surname" : "Завьялов",
                "staff_name" : "Дмитрий",
                "staff_patronymic" : "Викторович"
            },
            {
                "staff_department_code" : "222",
                "staff_department" : "Химико-технологический факультет",
                "staff_code" : "000008785",
                "staff_surname" : "Завьялов",
                "staff_name" : "Дмитрий",
                "staff_patronymic" : "Викторович"
            },
            {
                "staff_department_code" : "222",
                "staff_department" : "Химико-технологический факультет",
                "staff_code" : "000008785",
                "staff_surname" : "Завьялов",
                "staff_name" : "Денис",
                "staff_patronymic" : "Владимирович"
            }
        ]
        """

        Organization.objects.create(name="ВолгГТУ")

        ReferenceImporter.import_faculty_reference(FACULTY_REFERENCE_DATA)
        ReferenceImporter.import_teacher_reference(TEACHER_REFERENCE_DATA)

        try:
            self.assertEqual(EventParticipant.objects.all().count(), 3)
        except EventParticipant.DoesNotExist:
            self.fail()

    def test_student_import_reference(self):
        FACULTY_REFERENCE_DATA = """
            [
                {
                    "faculty_id" : "111",
                    "faculty_fullname" : "Факультет электроники и вычислительной техники",
                    "faculty_code" : "000000111",
                    "faculty_shortname" : "ФЭВТ"
                }
            ]
        """
        DEPARTMENT_REFERENCE_DATA = """
            [
                {
                    "department_id" : "1",
                    "department_code" : "000000001",
                    "department_fullname" : "Кафедра Автоматизация производственных процессов",
                    "department_shortname" : "АПП",
                    "faculty_id" : "111",
                    "faculty_shortname" : "ФЭВТ"
                },
                {
                    "department_id" : "2",
                    "department_code" : "000000002",
                    "department_fullname" : "Кафедра Автоматические установки",
                    "department_shortname" : "АУ",
                    "faculty_id" : "111",
                    "faculty_shortname" : "ФЭВТ"
                }
            ]
        """
        STUDENT_REFERENCE_DATA = """
        [
            {
                "group_code" : "000003049",
                "group_name" : "АДП-222",
                "faculty_id" : "000000001",
                "speciality" : "Управление в технических системах",
                "profile" : "Автоматизированные системы управления в цифровом производстве",
                "qualification" : "Бакалавр",
                "graduating_department_name" : ""
            },
            {
                "group_code" : "000000700",
                "group_name" : "АДП-322",
                "faculty_id" : "000000002",
                "speciality" : "Управление в технических системах",
                "profile" : "Аддитивное производство",
                "qualification" : "Бакалавр",
                "graduating_department_name" : ""
            }
        ]
        """

        Organization.objects.create(name="ВолгГТУ")

        ReferenceImporter.import_faculty_reference(FACULTY_REFERENCE_DATA)
        ReferenceImporter.import_department_reference(DEPARTMENT_REFERENCE_DATA)
        ReferenceImporter.import_student_reference(STUDENT_REFERENCE_DATA)

        try:
            self.assertEqual(EventParticipant.objects.all().count(), 2)
            self.assertNotEqual(EventParticipant.objects.get(name="АДП-222"), None)
            self.assertEqual(
                EventParticipant.objects.get(
                    role=EventParticipant.Role.STUDENT,
                    is_group=True,
                    department__name="Кафедра Автоматические установки",
                ).name,
                "АДП-322",
            )
        except EventParticipant.DoesNotExist:
            self.fail()

    def test_student_import_duplicate_reference(self):
        FACULTY_REFERENCE_DATA = """
            [
                {
                    "faculty_id" : "111",
                    "faculty_fullname" : "Факультет электроники и вычислительной техники",
                    "faculty_code" : "000000111",
                    "faculty_shortname" : "ФЭВТ"
                }
            ]
        """
        DEPARTMENT_REFERENCE_DATA = """
            [
                {
                    "department_id" : "1",
                    "department_code" : "000000001",
                    "department_fullname" : "Кафедра Автоматизация производственных процессов",
                    "department_shortname" : "АПП",
                    "faculty_id" : "111",
                    "faculty_shortname" : "ФЭВТ"
                },
                {
                    "department_id" : "2",
                    "department_code" : "000000002",
                    "department_fullname" : "Кафедра Автоматические установки",
                    "department_shortname" : "АУ",
                    "faculty_id" : "111",
                    "faculty_shortname" : "ФЭВТ"
                }
            ]
        """
        STUDENT_REFERENCE_DATA = """
        [
            {
                "group_code" : "000000558",
                "group_name" : "ПрИн-166",
                "faculty_id" : "000000001",
                "speciality" : "Программная инженерия",
                "profile" : "Программная инженерия. Факультет ФЭВТ",
                "qualification" : "бакалавр техники и технологии",
                "graduating_department_name" : ""
            },
            {
                "group_code" : "000000558",
                "group_name" : "ПрИн-166",
                "faculty_id" : "000000001",
                "speciality" : "Программная инженерия",
                "profile" : "Программная инженерия. Факультет ФЭВТ",
                "qualification" : "бакалавр техники и технологии",
                "graduating_department_name" : ""
            }
        ]
        """

        Organization.objects.create(name="ВолгГТУ")

        ReferenceImporter.import_faculty_reference(FACULTY_REFERENCE_DATA)
        ReferenceImporter.import_department_reference(DEPARTMENT_REFERENCE_DATA)
        ReferenceImporter.import_student_reference(STUDENT_REFERENCE_DATA)
        ReferenceImporter.import_student_reference(STUDENT_REFERENCE_DATA)

        try:
            self.assertEqual(EventParticipant.objects.all().count(), 1)
        except EventParticipant.DoesNotExist:
            self.fail()

    def test_schedule_import_saving_archive(self):
        FACULTY_REFERENCE_DATA = """
            [
                {
                    "faculty_id" : "111",
                    "faculty_fullname" : "Факультет электроники и вычислительной техники",
                    "faculty_code" : "000000111",
                    "faculty_shortname" : "ФЭВТ"
                },
                {
                    "faculty_id" : "222",
                    "faculty_fullname" : "Химико-технологический факультет",
                    "faculty_code" : "000000222",
                    "faculty_shortname" : "ХТФ"
                }
            ]
        """
        SCHEDULE_REFERENCE_DATA = """
            [
                {
                    "course": "4",
                    "schedule_template_metadata_faculty_shortname": "ФЭВТ",
                    "semester": "1",
                    "years": "2024-2025",
                    "start_date": "01.09.2025",
                    "end_date": "01.02.2026",
                    "scope": "бакалавриат",
                    "department_shortname": "ФЭВТ"
                },
                {
                    "course": "4",
                    "schedule_template_metadata_faculty_shortname": "ХТФ",
                    "semester": "1",
                    "years": "2024-2025",
                    "start_date": "01.09.2025",
                    "end_date": "01.02.2026",
                    "scope": "  магистратура ",
                    "department_shortname": "ХТФ"
                },
                {
                    "course": "3",
                    "schedule_template_metadata_faculty_shortname": "ФЭВТ",
                    "semester": "1",
                    "years": "2024-2025",
                    "start_date": "01.09.2025",
                    "end_date": "01.02.2026",
                    "scope": " Магистратура",
                    "department_shortname": "ФЭВТ"
                }
            ]
        """

        Organization.objects.create(name="ВолгГТУ")
        if not create_common_abstract_days():
            self.fail()

        ReferenceImporter.import_faculty_reference(FACULTY_REFERENCE_DATA)

        # first import
        ReferenceImporter.import_schedule(SCHEDULE_REFERENCE_DATA, True)

        try:
            self.assertEqual(Schedule.objects.all().count(), 3)
            self.assertEqual(Schedule.objects.filter(status=Schedule.Status.ACTIVE).count(), 3)
            self.assertEqual(Schedule.objects.filter(status=Schedule.Status.ARCHIVE).count(), 0)
            self.assertNotEqual(
                Schedule.objects.get(
                    status=Schedule.Status.ACTIVE,
                    schedule_template__metadata__faculty="ФЭВТ",
                    metadata__course=4,
                ),
                None,
            )
            self.assertNotEqual(
                Schedule.objects.get(
                    status=Schedule.Status.ACTIVE,
                    schedule_template__metadata__faculty="ФЭВТ",
                    metadata__course=3,
                ),
                None,
            )
        except Schedule.DoesNotExist:
            self.fail()

        # 4 course 1 semester 2024-2025
        # 3 course 1 semester 2024-2025
        try:
            self.assertEqual(ScheduleMetadata.objects.all().count(), 2)
        except ScheduleMetadata.DoesNotExist:
            self.fail()

        # Факультет электроники и вычислительной техники (Бакалавриат)
        # Факультет электроники и вычислительной техники (Магистратура)
        # Химико-технологический факультет
        try:
            self.assertEqual(ScheduleTemplate.objects.all().count(), 3)
        except ScheduleTemplate.DoesNotExist:
            self.fail()

        # ФЭВТ, Бакалавриат
        # ФЭВТ, Магистратура
        # ХТФ, Магистратура
        try:
            self.assertEqual(ScheduleTemplateMetadata.objects.all().count(), 3)
        except ScheduleTemplateMetadata.DoesNotExist:
            self.fail()

        # second import
        # now we have ARCHIVE Schedules
        ReferenceImporter.import_schedule(SCHEDULE_REFERENCE_DATA, True)

        try:
            self.assertEqual(Schedule.objects.all().count(), 6)
            self.assertEqual(Schedule.objects.filter(status=Schedule.Status.ACTIVE).count(), 3)
            self.assertEqual(Schedule.objects.filter(status=Schedule.Status.ARCHIVE).count(), 3)
            self.assertEqual(
                Schedule.objects.filter(
                    status=Schedule.Status.ACTIVE,
                    schedule_template__metadata__faculty="ФЭВТ",
                    metadata__course=4,
                ).count(),
                1,
            )
            self.assertEqual(
                Schedule.objects.filter(
                    status=Schedule.Status.ACTIVE,
                    schedule_template__metadata__faculty="ХТФ",
                    metadata__course=4,
                ).count(),
                1,
            )
            self.assertEqual(
                Schedule.objects.filter(
                    status=Schedule.Status.ARCHIVE,
                    schedule_template__metadata__faculty="ХТФ",
                    metadata__course=4,
                ).count(),
                1,
            )
        except Schedule.DoesNotExist:
            self.fail()

        # nothing must change
        # 4 course 1 semester 2024-2025
        # 3 course 1 semester 2024-2025
        try:
            self.assertEqual(ScheduleMetadata.objects.all().count(), 2)
        except ScheduleMetadata.DoesNotExist:
            self.fail()

        # Факультет электроники и вычислительной техники (Бакалавриат)
        # Факультет электроники и вычислительной техники (Магистратура)
        # Химико-технологический факультет
        try:
            self.assertEqual(ScheduleTemplate.objects.all().count(), 3)
        except ScheduleTemplate.DoesNotExist:
            self.fail()

        # ФЭВТ, Бакалавриат
        # ФЭВТ, Магистратура
        # ХТФ, Магистратура
        try:
            self.assertEqual(ScheduleTemplateMetadata.objects.all().count(), 3)
        except ScheduleTemplateMetadata.DoesNotExist:
            self.fail()

        # third import
        ReferenceImporter.import_schedule(SCHEDULE_REFERENCE_DATA, True)

        try:
            self.assertEqual(Schedule.objects.all().count(), 9)
            self.assertEqual(Schedule.objects.filter(status=Schedule.Status.ACTIVE).count(), 3)
            self.assertEqual(Schedule.objects.filter(status=Schedule.Status.ARCHIVE).count(), 6)
            self.assertEqual(
                Schedule.objects.filter(
                    status=Schedule.Status.ACTIVE,
                    schedule_template__metadata__faculty="ФЭВТ",
                    metadata__course=4,
                ).count(),
                1,
            )
            self.assertEqual(
                Schedule.objects.filter(
                    status=Schedule.Status.ACTIVE,
                    schedule_template__metadata__faculty="ХТФ",
                    metadata__course=4,
                ).count(),
                1,
            )
            self.assertEqual(
                Schedule.objects.filter(
                    status=Schedule.Status.ARCHIVE,
                    schedule_template__metadata__faculty="ХТФ",
                    metadata__course=4,
                ).count(),
                2,
            )
        except Schedule.DoesNotExist:
            self.fail()

        # nothing must change
        # 4 course 1 semester 2024-2025
        # 3 course 1 semester 2024-2025
        try:
            self.assertEqual(ScheduleMetadata.objects.all().count(), 2)
        except ScheduleMetadata.DoesNotExist:
            self.fail()

        # Факультет электроники и вычислительной техники (Бакалавриат)
        # Факультет электроники и вычислительной техники (Магистратура)
        # Химико-технологический факультет
        try:
            self.assertEqual(ScheduleTemplate.objects.all().count(), 3)
        except ScheduleTemplate.DoesNotExist:
            self.fail()

        # ФЭВТ, Бакалавриат
        # ФЭВТ, Магистратура
        # ХТФ, Магистратура
        try:
            self.assertEqual(ScheduleTemplateMetadata.objects.all().count(), 3)
        except ScheduleTemplateMetadata.DoesNotExist:
            self.fail()

    def test_schedule_import_deleting_archive(self):
        FACULTY_REFERENCE_DATA = """
            [
                {
                    "faculty_id" : "111",
                    "faculty_fullname" : "Факультет электроники и вычислительной техники",
                    "faculty_code" : "000000111",
                    "faculty_shortname" : "ФЭВТ"
                },
                {
                    "faculty_id" : "222",
                    "faculty_fullname" : "Химико-технологический факультет",
                    "faculty_code" : "000000222",
                    "faculty_shortname" : "ХТФ"
                }
            ]
        """
        SCHEDULE_REFERENCE_DATA = """
            [
                {
                    "course": "4",
                    "schedule_template_metadata_faculty_shortname": "ФЭВТ",
                    "semester": "1",
                    "years": "2024-2025",
                    "start_date": "01.09.2025",
                    "end_date": "01.02.2026",
                    "scope": "бакалавриат",
                    "department_shortname": "ФЭВТ"
                },
                {
                    "course": "4",
                    "schedule_template_metadata_faculty_shortname": "ХТФ",
                    "semester": "1",
                    "years": "2024-2025",
                    "start_date": "01.09.2025",
                    "end_date": "01.02.2026",
                    "scope": "  магистры ",
                    "department_shortname": "ХТФ"
                },
                {
                    "course": "3",
                    "schedule_template_metadata_faculty_shortname": "ФЭВТ",
                    "semester": "1",
                    "years": "2024-2025",
                    "start_date": "01.09.2025",
                    "end_date": "01.02.2026",
                    "scope": " Магистратура",
                    "department_shortname": "ФЭВТ"
                }
            ]
        """

        Organization.objects.create(name="ВолгГТУ")
        if not create_common_abstract_days():
            self.fail()

        ReferenceImporter.import_faculty_reference(FACULTY_REFERENCE_DATA)

        # first import
        ReferenceImporter.import_schedule(SCHEDULE_REFERENCE_DATA, False)

        try:
            self.assertEqual(Schedule.objects.all().count(), 3)
            self.assertEqual(Schedule.objects.filter(status=Schedule.Status.ACTIVE).count(), 3)
            self.assertEqual(Schedule.objects.filter(status=Schedule.Status.ARCHIVE).count(), 0)
            self.assertNotEqual(
                Schedule.objects.get(
                    status=Schedule.Status.ACTIVE,
                    schedule_template__metadata__faculty="ФЭВТ",
                    metadata__course=4,
                ),
                None,
            )
            self.assertNotEqual(
                Schedule.objects.get(
                    status=Schedule.Status.ACTIVE,
                    schedule_template__metadata__faculty="ФЭВТ",
                    metadata__course=3,
                ),
                None,
            )
        except Schedule.DoesNotExist:
            self.fail()

        # 4 course 1 semester 2024-2025
        # 3 course 1 semester 2024-2025
        try:
            self.assertEqual(ScheduleMetadata.objects.all().count(), 2)
        except ScheduleMetadata.DoesNotExist:
            self.fail()

        # Факультет электроники и вычислительной техники (Бакалавриат)
        # Факультет электроники и вычислительной техники (Магистратура)
        # Химико-технологический факультет
        try:
            self.assertEqual(ScheduleTemplate.objects.all().count(), 3)
        except ScheduleTemplate.DoesNotExist:
            self.fail()

        # ФЭВТ, Бакалавриат
        # ФЭВТ, Магистратура
        # ХТФ, Магистратура
        try:
            self.assertEqual(ScheduleTemplateMetadata.objects.all().count(), 3)
        except ScheduleTemplateMetadata.DoesNotExist:
            self.fail()

        # second import
        # now we have ARCHIVE Schedules
        ReferenceImporter.import_schedule(SCHEDULE_REFERENCE_DATA, False)

        try:
            self.assertEqual(Schedule.objects.all().count(), 6)
            self.assertEqual(Schedule.objects.filter(status=Schedule.Status.ACTIVE).count(), 3)
            self.assertEqual(Schedule.objects.filter(status=Schedule.Status.ARCHIVE).count(), 3)
            self.assertEqual(
                Schedule.objects.filter(
                    status=Schedule.Status.ACTIVE,
                    schedule_template__metadata__faculty="ФЭВТ",
                    metadata__course=4,
                ).count(),
                1,
            )
            self.assertEqual(
                Schedule.objects.filter(
                    status=Schedule.Status.ACTIVE,
                    schedule_template__metadata__faculty="ХТФ",
                    metadata__course=4,
                ).count(),
                1,
            )
            self.assertEqual(
                Schedule.objects.filter(
                    status=Schedule.Status.ARCHIVE,
                    schedule_template__metadata__faculty="ХТФ",
                    metadata__course=4,
                ).count(),
                1,
            )
        except Schedule.DoesNotExist:
            self.fail()

        # nothing must change
        # 4 course 1 semester 2024-2025
        # 3 course 1 semester 2024-2025
        try:
            self.assertEqual(ScheduleMetadata.objects.all().count(), 2)
        except ScheduleMetadata.DoesNotExist:
            self.fail()

        # Факультет электроники и вычислительной техники (Бакалавриат)
        # Факультет электроники и вычислительной техники (Магистратура)
        # Химико-технологический факультет
        try:
            self.assertEqual(ScheduleTemplate.objects.all().count(), 3)
        except ScheduleTemplate.DoesNotExist:
            self.fail()

        # ФЭВТ, Бакалавриат
        # ФЭВТ, Магистратура
        # ХТФ, Магистратура
        try:
            self.assertEqual(ScheduleTemplateMetadata.objects.all().count(), 3)
        except ScheduleTemplateMetadata.DoesNotExist:
            self.fail()

        # third import
        ReferenceImporter.import_schedule(SCHEDULE_REFERENCE_DATA, False)

        try:
            self.assertEqual(Schedule.objects.all().count(), 6)
            self.assertEqual(Schedule.objects.filter(status=Schedule.Status.ACTIVE).count(), 3)
            self.assertEqual(Schedule.objects.filter(status=Schedule.Status.ARCHIVE).count(), 3)
            self.assertEqual(
                Schedule.objects.filter(
                    status=Schedule.Status.ACTIVE,
                    schedule_template__metadata__faculty="ФЭВТ",
                    metadata__course=4,
                ).count(),
                1,
            )
            self.assertEqual(
                Schedule.objects.filter(
                    status=Schedule.Status.ACTIVE,
                    schedule_template__metadata__faculty="ХТФ",
                    metadata__course=4,
                ).count(),
                1,
            )
            self.assertEqual(
                Schedule.objects.filter(
                    status=Schedule.Status.ARCHIVE,
                    schedule_template__metadata__faculty="ХТФ",
                    metadata__course=4,
                ).count(),
                1,
            )
        except Schedule.DoesNotExist:
            self.fail()

        # nothing must change
        # 4 course 1 semester 2024-2025
        # 3 course 1 semester 2024-2025
        try:
            self.assertEqual(ScheduleMetadata.objects.all().count(), 2)
        except ScheduleMetadata.DoesNotExist:
            self.fail()

        # Факультет электроники и вычислительной техники (Бакалавриат)
        # Факультет электроники и вычислительной техники (Магистратура)
        # Химико-технологический факультет
        try:
            self.assertEqual(ScheduleTemplate.objects.all().count(), 3)
        except ScheduleTemplate.DoesNotExist:
            self.fail()

        # ФЭВТ, Бакалавриат
        # ФЭВТ, Магистратура
        # ХТФ, Магистратура
        try:
            self.assertEqual(ScheduleTemplateMetadata.objects.all().count(), 3)
        except ScheduleTemplateMetadata.DoesNotExist:
            self.fail()

    # TODO: schedule_import test with event deleting

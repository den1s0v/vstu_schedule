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
from apps.common.services.timetable.utilities.model_helpers import (
    create_common_abstract_days,
    create_common_time_slots,
    is_abstract_event_already_exists,
)
from apps.common.services.timetable.write.factories import create_abstract_event

"""python manage.py test apps.common.tests.test_readapi
"""


class TestReadAPI(TestCase):
    def setUp(self):
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
                }
            ]
        """

        create_common_abstract_days()
        create_common_time_slots()
        Organization.objects.create(name="ВолгГТУ")
        ReferenceImporter.import_faculty_reference(FACULTY_REFERENCE_DATA)
        ReferenceImporter.import_schedule(SCHEDULE_REFERENCE_DATA, True)

    def test_is_abstract_event_already_exists(self):
        DEPARTMENT = Department.objects.get(shortname="ФЭВТ")
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
                name="Кузнецова А.С.",
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
            EventParticipant.objects.create(
                name="ПрИн-467",
                role=EventParticipant.Role.STUDENT,
                is_group=True,
                department=DEPARTMENT,
            ),
        ]
        PLACES = [
            EventPlace.objects.create(building="В", room="902"),
            EventPlace.objects.create(building="В", room="903"),
        ]
        ABSTRACT_DAY = AbstractDay.objects.get(day_number=0)
        TIME_SLOT = TimeSlot.objects.get(alt_name="1-2")
        DATE_ = datetime.strptime("1.02.2025", "%d.%m.%Y").date()
        SCHEDULE = Schedule.objects.get(
            schedule_template__metadata__faculty="ФЭВТ",
            schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
            metadata__course=4,
            metadata__semester=2,
        )

        create_abstract_event(
            KIND, SUBJECT, PARTICIPANTS, PLACES, ABSTRACT_DAY, TIME_SLOT, None, SCHEDULE
        )
        create_abstract_event(
            KIND, SUBJECT, PARTICIPANTS, PLACES, ABSTRACT_DAY, TIME_SLOT, DATE_, SCHEDULE
        )

        self.assertEqual(
            is_abstract_event_already_exists(
                KIND, SUBJECT, PARTICIPANTS, PLACES, ABSTRACT_DAY, TIME_SLOT, DATE_, SCHEDULE
            ),
            True,
        )
        self.assertEqual(
            is_abstract_event_already_exists(
                KIND, SUBJECT, PARTICIPANTS, PLACES, ABSTRACT_DAY, TIME_SLOT, None, SCHEDULE
            ),
            True,
        )

        OTHER_PARTICIPANT = EventParticipant.objects.create(
            name="ПрИн-467",
            role=EventParticipant.Role.STUDENT,
            is_group=True,
            department=DEPARTMENT,
        )

        self.assertEqual(
            is_abstract_event_already_exists(
                KIND, SUBJECT, [OTHER_PARTICIPANT], PLACES, ABSTRACT_DAY, TIME_SLOT, None, SCHEDULE
            ),
            False,
        )

    def test_is_abstract_event_already_exists_with_dupl_participant(self):
        IMPORT_DATA = """
            {
            "title": "Учебные занятия 4 курса Бакалавриат ФЭВТ на 2 семестр 2024-2025 учебного года",
            "table": {
                "grid": [
                {
                    "subject": "ФИЛОСОФИЯ И МЕТОДОЛОГИЯ НАУКИ",
                    "kind": "лекция",
                    "participants": {
                    "teachers": [
                        "проф. Леонтьева Е.Ю.",
                        "проф. Леонтьева Е.Ю."
                    ],
                    "student_groups": [
                        "ПОАС-2.1",
                        "ПОАС-2.2"
                    ]
                    },
                        "places": [
                        "В 502"
                    ],
                    "hours": [
                        "1-2",
                        "3-4"
                    ],
                    "week_day_index": 4,
                    "week": "second_week",
                    "holds_on_date": [
                        "11.09.2024",
                        "09.10.2024",
                        "25.09.2024",
                        "23.10.2024"
                    ]
                },
                {
                    "subject": "ФИЛОСОФИЯ И МЕТОДОЛОГИЯ НАУКИ",
                    "kind": "лекция",
                    "participants": {
                    "teachers": [
                        "проф. Леонтьева Е.Ю.",
                        "проф. Леонтьева Е.Ю."
                    ],
                    "student_groups": [
                        "ПОАС-2.1",
                        "ПОАС-2.2"
                    ]
                    },
                        "places": [
                        "В 502"
                    ],
                    "hours": [
                        "1-2",
                        "3-4"
                    ],
                    "week_day_index": 4,
                    "week": "second_week",
                    "holds_on_date": [
                        "11.09.2024",
                        "09.10.2024",
                        "25.09.2024",
                        "23.10.2024"
                    ]
                },
                {
                    "subject": "ФИЛОСОФИЯ И МЕТОДОЛОГИЯ НАУКИ",
                    "kind": "лекция",
                    "participants": {
                    "teachers": [
                        "проф. Леонтьева Е.Ю.",
                        "проф. Леонтьева Е.Ю."
                    ],
                    "student_groups": [
                        "ПОАС-2.1",
                        "ПОАС-2.2"
                    ]
                    },
                        "places": [
                        "В 502"
                    ],
                    "hours": [
                        "1-2",
                        "3-4"
                    ],
                    "week_day_index": 4,
                    "week": "second_week",
                    "holds_on_date": [
                        "11.09.2024",
                        "09.10.2024",
                        "25.09.2024",
                        "23.10.2024"
                    ]
                }
            ],
            "datetime": {
            "weeks": {
                "second_week": [
                    {
                        "week_day_index": 4,
                        "calendar": [
                            {
                                "month_index": 0,
                                "month_days": [
                                "11",
                                "25"
                                ]
                            },
                            {
                                "month_index": 1,
                                "month_days": [
                                "9",
                                "23"
                                ]
                            },
                            {
                                "month_index": 2,
                                "month_days": [
                                "6",
                                "20"
                                ]
                            },
                            {
                                "month_index": 3,
                                "month_days": [
                                "4",
                                "18"
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
                "сентябрь",
                "октябрь",
                "ноябрь",
                "декабрь"
            ]
            }
        }
        }
        """

        self.assertEqual(AbstractEvent.objects.all().count(), 0)

        schedule = Schedule.objects.get(
            schedule_template__metadata__faculty="ФЭВТ",
            schedule_template__metadata__scope=ScheduleTemplateMetadata.Scope.BACHELOR,
            metadata__years="2024-2025",
            metadata__course=4,
            metadata__semester=2,
        )

        EventImporter.import_events(IMPORT_DATA)

        self.assertEqual(
            is_abstract_event_already_exists(
                EventKind.objects.get(name="Лекция"),
                Subject.objects.get(name="ФИЛОСОФИЯ И МЕТОДОЛОГИЯ НАУКИ"),
                [
                    EventParticipant.objects.get(name="проф. Леонтьева Е.Ю."),
                    EventParticipant.objects.get(name="проф. Леонтьева Е.Ю."),
                    EventParticipant.objects.get(name="ПОАС-2.1"),
                    EventParticipant.objects.get(name="ПОАС-2.2"),
                ],
                [
                    EventPlace.objects.get(building="В", room="502"),
                ],
                AbstractDay.objects.get(day_number=11),
                TimeSlot.objects.get(alt_name="1-2"),
                datetime.strptime("11.09.2024", "%d.%m.%Y").date(),
                schedule,
            ),
            True,
        )

        self.assertEqual(
            AbstractEvent.objects.filter(
                subject__name="ФИЛОСОФИЯ И МЕТОДОЛОГИЯ НАУКИ",
                participants__name="ПОАС-2.1",
                time_slot__alt_name="1-2",
                holds_on_date=datetime.strptime("11.09.2024", "%d.%m.%Y").date(),
            ).count(),
            1,
        )

        self.assertEqual(
            AbstractEvent.objects.filter(
                subject__name="ФИЛОСОФИЯ И МЕТОДОЛОГИЯ НАУКИ",
                participants__name="ПОАС-2.1",
                holds_on_date=datetime.strptime("11.09.2024", "%d.%m.%Y").date(),
            ).count(),
            2,
        )

        self.assertEqual(
            Event.objects.filter(
                subject_override__name="ФИЛОСОФИЯ И МЕТОДОЛОГИЯ НАУКИ",
                participants_override__name="ПОАС-2.1",
                date=datetime.strptime("11.09.2024", "%d.%m.%Y").date(),
            ).count(),
            2,
        )

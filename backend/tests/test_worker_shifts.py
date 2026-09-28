"""Unit tests for worker shifts calculation (2/2, 5/2, night shifts, and exceptions)."""

import unittest
from datetime import date, time

from app.core.workday import MOSCOW
from app.modules.users.enums import ScheduleType
from app.modules.users.shifts import get_worker_shift, is_worker_working_on_date


class WorkerShiftsCalculationTests(unittest.TestCase):
    def test_five_two_schedule(self):
        # Mon (2026-09-28) to Sun (2026-10-04)
        monday = date(2026, 9, 28)
        friday = date(2026, 10, 2)
        saturday = date(2026, 10, 3)
        sunday = date(2026, 10, 4)

        self.assertTrue(is_worker_working_on_date(monday, ScheduleType.FIVE_TWO))
        self.assertTrue(is_worker_working_on_date(friday, ScheduleType.FIVE_TWO))
        self.assertFalse(is_worker_working_on_date(saturday, ScheduleType.FIVE_TWO))
        self.assertFalse(is_worker_working_on_date(sunday, ScheduleType.FIVE_TWO))

        shift_mon = get_worker_shift(
            monday,
            workshift_start=time(9, 0),
            workshift_end=time(18, 0),
            schedule_type=ScheduleType.FIVE_TWO,
        )
        self.assertIsNotNone(shift_mon)
        self.assertEqual(shift_mon.start.hour, 9)
        self.assertEqual(shift_mon.start.tzinfo, MOSCOW)
        self.assertEqual(shift_mon.end.hour, 18)
        self.assertEqual(shift_mon.start.date(), monday)
        self.assertEqual(shift_mon.end.date(), monday)

        shift_sat = get_worker_shift(
            saturday,
            workshift_start=time(9, 0),
            workshift_end=time(18, 0),
            schedule_type=ScheduleType.FIVE_TWO,
        )
        self.assertIsNone(shift_sat)

    def test_two_two_schedule(self):
        cycle_start = date(2026, 9, 1)
        # Cycle:
        # Sep 1: day 0 (work)
        # Sep 2: day 1 (work)
        # Sep 3: day 2 (off)
        # Sep 4: day 3 (off)
        # Sep 5: day 0 (work)
        self.assertTrue(
            is_worker_working_on_date(date(2026, 9, 1), ScheduleType.TWO_TWO, cycle_start)
        )
        self.assertTrue(
            is_worker_working_on_date(date(2026, 9, 2), ScheduleType.TWO_TWO, cycle_start)
        )
        self.assertFalse(
            is_worker_working_on_date(date(2026, 9, 3), ScheduleType.TWO_TWO, cycle_start)
        )
        self.assertFalse(
            is_worker_working_on_date(date(2026, 9, 4), ScheduleType.TWO_TWO, cycle_start)
        )
        self.assertTrue(
            is_worker_working_on_date(date(2026, 9, 5), ScheduleType.TWO_TWO, cycle_start)
        )

        # Check negative delta (dates before cycle_start)
        # Aug 31: -1 days -> -1 % 4 = 3 (off)
        # Aug 30: -2 days -> -2 % 4 = 2 (off)
        # Aug 29: -3 days -> -3 % 4 = 1 (work)
        # Aug 28: -4 days -> -4 % 4 = 0 (work)
        self.assertFalse(
            is_worker_working_on_date(date(2026, 8, 31), ScheduleType.TWO_TWO, cycle_start)
        )
        self.assertFalse(
            is_worker_working_on_date(date(2026, 8, 30), ScheduleType.TWO_TWO, cycle_start)
        )
        self.assertTrue(
            is_worker_working_on_date(date(2026, 8, 29), ScheduleType.TWO_TWO, cycle_start)
        )
        self.assertTrue(
            is_worker_working_on_date(date(2026, 8, 28), ScheduleType.TWO_TWO, cycle_start)
        )

        # Shift interval for 10:00 to 22:00
        shift = get_worker_shift(
            date(2026, 9, 1),
            workshift_start=time(10, 0),
            workshift_end=time(22, 0),
            schedule_type=ScheduleType.TWO_TWO,
            cycle_start_date=cycle_start,
        )
        self.assertIsNotNone(shift)
        self.assertEqual(shift.start.hour, 10)
        self.assertEqual(shift.end.hour, 22)
        self.assertEqual(shift.end.date(), date(2026, 9, 1))

    def test_night_shift_crosses_midnight(self):
        target = date(2026, 9, 28)  # Monday
        shift = get_worker_shift(
            target,
            workshift_start=time(22, 0),
            workshift_end=time(6, 0),
            schedule_type=ScheduleType.FIVE_TWO,
        )
        self.assertIsNotNone(shift)
        self.assertEqual(shift.start.hour, 22)
        self.assertEqual(shift.start.date(), target)
        self.assertEqual(shift.end.hour, 6)
        self.assertEqual(shift.end.date(), date(2026, 9, 29))

    def test_shift_exception_override(self):
        saturday = date(2026, 10, 3)
        # Saturday is off in 5/2, but exception says working with custom hours 11:00-15:00
        shift_override = get_worker_shift(
            saturday,
            workshift_start=time(9, 0),
            workshift_end=18,
            schedule_type=ScheduleType.FIVE_TWO,
            exception_is_working=True,
            exception_start=time(11, 0),
            exception_end=time(15, 0),
        )
        self.assertIsNotNone(shift_override)
        self.assertEqual(shift_override.start.hour, 11)
        self.assertEqual(shift_override.end.hour, 15)

        # Monday is working in 5/2, but exception says off
        monday = date(2026, 9, 28)
        shift_off = get_worker_shift(
            monday,
            workshift_start=time(9, 0),
            workshift_end=time(18, 0),
            schedule_type=ScheduleType.FIVE_TWO,
            exception_is_working=False,
        )
        self.assertIsNone(shift_off)


if __name__ == "__main__":
    unittest.main()

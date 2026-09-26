"""The worker-day timeline shared by the schedule and the workload analytics (no DB)."""

import unittest
from datetime import date, datetime, time, timedelta

from app.core.workday import MOSCOW, Period, period_bounds
from app.modules.schedule.timeline import (
    attribution_window,
    build_worker_day,
    planning_shift,
    route_visits,
)

DAY = date(2030, 3, 11)


def at(hour: int, minute: int = 0, *, days: int = 0) -> datetime:
    return datetime.combine(DAY + timedelta(days=days), time(hour, minute), MOSCOW)


def stop(ticket_id, arrival, start=None, end=None, waiting=0, sequence=None):
    return {
        "ticket_id": ticket_id,
        "sequence": sequence,
        "arrival_at": arrival.isoformat(),
        "service_start_at": start.isoformat() if start else None,
        "service_end_at": end.isoformat() if end else None,
        "waiting_minutes": waiting,
    }


def ticket(ticket_id, start, end):
    return {"id": ticket_id, "planned_start_at": start, "planned_end_at": end}


class ShiftModelTests(unittest.TestCase):
    def test_night_shift_belongs_to_the_day_it_starts(self):
        # Same rule as planning.eligibility.prepare: end <= start rolls to the next day.
        self.assertEqual(planning_shift(DAY, time(22), time(6)), (at(22), at(6, days=1)))
        self.assertEqual(planning_shift(DAY, time(9), time(18)), (at(9), at(18)))

    def test_every_moment_belongs_to_exactly_one_worker_day(self):
        day_window = attribution_window(DAY, time(9), time(18))
        self.assertEqual(day_window, (at(1, 30), at(1, 30, days=1)))
        night_today = attribution_window(DAY, time(22), time(6))
        night_yesterday = attribution_window(DAY - timedelta(days=1), time(22), time(6))
        self.assertEqual(night_yesterday[1], night_today[0])
        # 02:00 today is last night's shift, not tonight's.
        self.assertTrue(night_yesterday[0] <= at(2) < night_yesterday[1])

    def test_periods_are_half_open_moscow_intervals(self):
        noon = at(12)
        self.assertEqual(period_bounds(Period.TODAY, noon), (at(0), at(0, days=1)))
        week_start, week_end = period_bounds(Period.WEEK, noon)
        self.assertEqual((week_start, week_end - week_start), (at(0), timedelta(days=7)))
        month_start, month_end = period_bounds(Period.MONTH, noon)
        self.assertEqual(month_start, datetime(2030, 3, 1, tzinfo=MOSCOW))
        self.assertEqual(month_end, datetime(2030, 4, 1, tzinfo=MOSCOW))


class RouteTimelineTests(unittest.TestCase):
    def route(self):
        return [
            stop(None, at(9), sequence=1),
            stop(1, at(9, 20), at(9, 30), at(10, 30), waiting=10, sequence=2),
            stop(2, at(10, 50), at(10, 50), at(11, 50), sequence=3),
            stop(None, at(12, 10), sequence=4),
        ]

    def test_travel_waiting_and_service_are_kept_apart(self):
        visits, travel = route_visits(self.route())
        self.assertEqual([visit.ticket_id for visit in visits], [1, 2])
        self.assertEqual(travel, 60)
        self.assertEqual([visit.waiting_minutes for visit in visits], [10, 0])

    def test_day_totals_and_free_time(self):
        day = build_worker_day(
            DAY,
            shift_start=time(9),
            shift_end=time(18),
            route_stops=self.route(),
            tickets=[ticket(1, at(9, 30), at(10, 30)), ticket(2, at(10, 50), at(11, 50))],
        )
        self.assertEqual(
            (day.service_minutes, day.travel_minutes, day.waiting_minutes), (120, 60, 10)
        )
        self.assertEqual((day.shift_minutes, day.free_minutes), (540, 350))
        self.assertEqual(day.conflicts, [])

    def test_route_that_no_longer_matches_the_tickets_is_reported(self):
        day = build_worker_day(
            DAY,
            shift_start=time(9),
            shift_end=time(18),
            route_stops=self.route(),
            # Ticket 1 moved to someone else, 2 was shifted, 3 was added by hand.
            tickets=[ticket(2, at(13), at(14)), ticket(3, at(15), at(16))],
        )
        codes = {conflict.code: conflict.ticket_ids for conflict in day.conflicts}
        self.assertEqual(codes["route_outdated"], [1])
        self.assertEqual(codes["not_in_route"], [3])
        self.assertEqual(codes["route_time_mismatch"], [2])
        self.assertEqual(
            {visit.ticket_id: visit.source for visit in day.visits}, {2: "route", 3: "ticket"}
        )


class ConflictTests(unittest.TestCase):
    def build(self, tickets, **kwargs):
        return build_worker_day(
            DAY,
            shift_start=kwargs.pop("shift_start", time(9)),
            shift_end=kwargs.pop("shift_end", time(18)),
            route_stops=None,
            tickets=tickets,
            **kwargs,
        )

    def codes(self, day):
        return {conflict.code: conflict.ticket_ids for conflict in day.conflicts}

    def test_overlap_and_overtime_after_the_shift(self):
        day = self.build(
            [
                ticket(1, at(10), at(11)),
                ticket(2, at(10, 30), at(11, 30)),
                ticket(3, at(17), at(19)),
            ]
        )
        self.assertEqual(self.codes(day)["visits_overlap"], [1, 2])
        self.assertEqual(self.codes(day)["outside_shift"], [3])
        self.assertEqual(day.overtime_minutes, 60)

    def test_night_shift_visit_after_midnight_is_inside_the_shift(self):
        day = self.build(
            [ticket(1, at(23), at(23, 45)), ticket(2, at(2, days=1), at(3, days=1))],
            shift_start=time(22),
            shift_end=time(6),
        )
        self.assertEqual(day.conflicts, [])
        self.assertEqual((day.shift_minutes, day.service_minutes), (480, 105))

    def test_dated_absence_removes_capacity_and_flags_visits(self):
        day = self.build(
            [ticket(1, at(10), at(11)), ticket(2, at(16), at(17))],
            available=False,
            unavailable_at=at(13),
            unavailable_until=at(18),
        )
        self.assertEqual(self.codes(day)["during_absence"], [2])
        self.assertEqual((day.shift_minutes, day.free_minutes), (0, 0))

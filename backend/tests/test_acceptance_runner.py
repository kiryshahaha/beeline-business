"""Negative checks for the independent shift guard in the Plan 5 acceptance runner."""

import unittest

from run_acceptance_plan5 import assert_visits_within_shifts


class AcceptanceShiftGuardTests(unittest.TestCase):
    def day(self):
        return {
            "route_date": "2030-01-15",
            "roster": [{"worker_id": 9, "workshift_start": "09:00", "workshift_end": "17:00"}],
            "visits": [
                {
                    "ticket_id": 37,
                    "worker_id": 9,
                    "arrival_at": "2030-01-15T09:00:00+03:00",
                    "service_start_at": "2030-01-15T16:30:00+03:00",
                    "service_end_at": "2030-01-15T17:00:00+03:00",
                }
            ],
        }

    def test_exact_shift_boundaries_are_allowed(self):
        assert_visits_within_shifts(self.day())

    def test_arrival_before_shift_and_completion_after_shift_are_rejected(self):
        for field, value in (
            ("arrival_at", "2030-01-15T08:59:00+03:00"),
            ("service_end_at", "2030-01-15T17:01:00+03:00"),
            ("service_start_at", "2030-01-15T17:01:00+03:00"),
        ):
            with self.subTest(field=field):
                day = self.day()
                day["visits"][0][field] = value
                with self.assertRaisesRegex(AssertionError, "left its worker shift"):
                    assert_visits_within_shifts(day)

    def test_visit_outside_roster_is_rejected(self):
        day = self.day()
        day["visits"][0]["worker_id"] = 10
        with self.assertRaisesRegex(AssertionError, "outside the roster"):
            assert_visits_within_shifts(day)

    def test_overnight_shift_accepts_next_day_completion(self):
        day = self.day()
        day["roster"][0].update(workshift_start="22:00", workshift_end="06:00")
        day["visits"][0].update(
            arrival_at="2030-01-15T22:00:00+03:00",
            service_start_at="2030-01-16T05:30:00+03:00",
            service_end_at="2030-01-16T06:00:00+03:00",
        )
        assert_visits_within_shifts(day)

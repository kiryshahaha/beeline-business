"""Tests for T4-03: regular ticket slot search and insertion."""

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.modules.planning.slot_finder import find_regular_ticket_slot

MOSCOW = ZoneInfo("Europe/Moscow")


class SlotFinderTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 30, 9, 0, tzinfo=MOSCOW)
        self.shift_start = datetime(2026, 9, 30, 8, 0, tzinfo=MOSCOW)
        self.shift_end = datetime(2026, 9, 30, 20, 0, tzinfo=MOSCOW)

        self.worker_1 = {
            "user_id": 10,
            "skills": [1, 2],
            "transport_type": "car",
            "available_appliances": {101: 5},
            "shift_start_at": self.shift_start,
            "shift_end_at": self.shift_end,
        }
        self.worker_2 = {
            "user_id": 11,
            "skills": [1],
            "transport_type": "car",
            "available_appliances": {101: 5},
            "shift_start_at": self.shift_start,
            "shift_end_at": self.shift_end,
        }

        # Mock constant 15 min travel between any distinct locations
        self.travel_fn = lambda f, t, mode: 0 if f == t else 15

    def test_successful_insertion_between_stops(self):
        baseline = {
            "visits": [
                {
                    "ticket_id": 1,
                    "worker_id": 10,
                    "sequence": 1,
                    "location_id": 1001,
                    "service_start_at": "2026-09-30T09:00:00+03:00",
                    "service_end_at": "2026-09-30T09:30:00+03:00",
                },
                {
                    "ticket_id": 2,
                    "worker_id": 10,
                    "sequence": 2,
                    "location_id": 1002,
                    "visit_window_start": "2026-09-30T11:30:00+03:00",
                    "visit_window_end": "2026-09-30T13:00:00+03:00",
                    "service_start_at": "2026-09-30T11:30:00+03:00",
                    "service_end_at": "2026-09-30T12:00:00+03:00",
                },
            ]
        }
        ticket = {
            "id": 99,
            "location_id": 2001,
            "estimated_duration_minutes": 30,
            "visit_window_start": "2026-09-30T09:45:00+03:00",
            "visit_window_end": "2026-09-30T11:00:00+03:00",
            "required_skills": [1],
        }

        res = find_regular_ticket_slot(
            ticket=ticket,
            candidate_workers=[self.worker_1],
            baseline_state=baseline,
            lifecycle_by_ticket={1: "completed", 2: "assigned"},
            travel_time_fn=self.travel_fn,
            office_location_id=100,
            now=self.now,
        )

        self.assertEqual(res.status, "slot_found")
        self.assertIsNotNone(res.selected)
        self.assertEqual(res.selected.worker_id, 10)
        self.assertEqual(res.selected.insertion_sequence, 2)
        # Check visits count in proposed_state
        visits = res.selected.proposed_state["visits"]
        self.assertEqual(len(visits), 3)
        self.assertEqual([v["ticket_id"] for v in visits], [1, 99, 2])
        self.assertEqual([v["sequence"] for v in visits], [1, 2, 3])

    def test_missing_skill_rejects_worker(self):
        ticket = {
            "id": 99,
            "location_id": 2001,
            "estimated_duration_minutes": 30,
            "visit_window_start": "2026-09-30T10:00:00+03:00",
            "visit_window_end": "2026-09-30T12:00:00+03:00",
            "required_skills": [2],  # worker_2 only has [1]
        }
        res = find_regular_ticket_slot(
            ticket=ticket,
            candidate_workers=[self.worker_2],
            baseline_state={"visits": []},
            lifecycle_by_ticket={},
            travel_time_fn=self.travel_fn,
            office_location_id=100,
            now=self.now,
        )
        self.assertEqual(res.status, "not_insertable")
        self.assertIn(11, res.candidate_reasons)
        self.assertEqual(res.candidate_reasons[11]["code"], "missing_skill")

    def test_insufficient_appliances_rejects_worker(self):
        ticket = {
            "id": 99,
            "location_id": 2001,
            "estimated_duration_minutes": 30,
            "visit_window_start": "2026-09-30T10:00:00+03:00",
            "visit_window_end": "2026-09-30T12:00:00+03:00",
            "required_appliances": {101: 10},  # worker_1 has 5
        }
        res = find_regular_ticket_slot(
            ticket=ticket,
            candidate_workers=[self.worker_1],
            baseline_state={"visits": []},
            lifecycle_by_ticket={},
            travel_time_fn=self.travel_fn,
            office_location_id=100,
            now=self.now,
        )
        self.assertEqual(res.status, "not_insertable")
        self.assertEqual(res.candidate_reasons[10]["code"], "insufficient_appliances")

    def test_window_overflow_rejects_slot(self):
        # Ticket window ended at 08:30, but now is 09:00
        ticket = {
            "id": 99,
            "location_id": 2001,
            "estimated_duration_minutes": 30,
            "visit_window_start": "2026-09-30T08:00:00+03:00",
            "visit_window_end": "2026-09-30T08:30:00+03:00",
        }
        res = find_regular_ticket_slot(
            ticket=ticket,
            candidate_workers=[self.worker_1],
            baseline_state={"visits": []},
            lifecycle_by_ticket={},
            travel_time_fn=self.travel_fn,
            office_location_id=100,
            now=self.now,
        )
        self.assertEqual(res.status, "not_insertable")
        self.assertEqual(res.candidate_reasons[10]["code"], "no_feasible_slot")

    def test_safe_point_prevents_inserting_before_in_progress_stop(self):
        baseline = {
            "visits": [
                {
                    "ticket_id": 1,
                    "worker_id": 10,
                    "sequence": 1,
                    "location_id": 1001,
                    "service_start_at": "2026-09-30T09:00:00+03:00",
                    "service_end_at": "2026-09-30T09:45:00+03:00",
                },
                {
                    "ticket_id": 2,
                    "worker_id": 10,
                    "sequence": 2,
                    "location_id": 1002,
                    "visit_window_start": "2026-09-30T14:00:00+03:00",
                    "visit_window_end": "2026-09-30T15:00:00+03:00",
                    "service_start_at": "2026-09-30T14:00:00+03:00",
                    "service_end_at": "2026-09-30T14:30:00+03:00",
                },
            ]
        }
        # Ticket 1 is in_progress! New ticket window is early (09:10-09:30).
        # Cannot be inserted before ticket 1 because ticket 1 is frozen in_progress!
        ticket = {
            "id": 99,
            "location_id": 2001,
            "estimated_duration_minutes": 20,
            "visit_window_start": "2026-09-30T09:00:00+03:00",
            "visit_window_end": "2026-09-30T09:30:00+03:00",
        }
        res = find_regular_ticket_slot(
            ticket=ticket,
            candidate_workers=[self.worker_1],
            baseline_state=baseline,
            lifecycle_by_ticket={1: "in_progress", 2: "assigned"},
            travel_time_fn=self.travel_fn,
            office_location_id=100,
            now=self.now,
        )
        self.assertEqual(res.status, "not_insertable")


if __name__ == "__main__":
    unittest.main()

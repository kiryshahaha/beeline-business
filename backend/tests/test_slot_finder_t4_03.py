"""Tests for T4-03: regular ticket slot search and insertion."""

import unittest
from datetime import datetime, timedelta
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

    def test_service_must_finish_inside_customer_window(self):
        ticket = {
            "id": 99,
            "location_id": 100,
            "estimated_duration_minutes": 30,
            "visit_window_start": "2026-09-30T11:00:00+03:00",
            "visit_window_end": "2026-09-30T11:15:00+03:00",
        }
        result = find_regular_ticket_slot(
            ticket=ticket,
            candidate_workers=[self.worker_1],
            baseline_state={"visits": []},
            lifecycle_by_ticket={},
            travel_time_fn=self.travel_fn,
            office_location_id=100,
            now=self.now,
        )
        self.assertEqual(result.status, "not_insertable")
        self.assertEqual(result.candidate_reasons[10]["code"], "no_feasible_slot")

    def test_slot_can_start_at_shift_start_and_finish_at_shift_end(self):
        self.now = self.shift_start
        start_result = find_regular_ticket_slot(
            ticket={
                "id": 97,
                "location_id": 100,
                "estimated_duration_minutes": 30,
                "visit_window_start": "2026-09-30T08:00:00+03:00",
                "visit_window_end": "2026-09-30T08:30:00+03:00",
            },
            candidate_workers=[self.worker_1],
            baseline_state={"visits": []},
            lifecycle_by_ticket={},
            travel_time_fn=self.travel_fn,
            office_location_id=100,
            now=self.now,
        )
        self.assertEqual(start_result.status, "slot_found")
        self.assertEqual(start_result.selected.service_start_at, self.shift_start)

        self.now = self.shift_end - timedelta(minutes=30)
        end_result = find_regular_ticket_slot(
            ticket={
                "id": 98,
                "location_id": 100,
                "estimated_duration_minutes": 30,
                "visit_window_start": "2026-09-30T19:30:00+03:00",
                "visit_window_end": "2026-09-30T20:00:00+03:00",
            },
            candidate_workers=[self.worker_1],
            baseline_state={"visits": []},
            lifecycle_by_ticket={},
            travel_time_fn=self.travel_fn,
            office_location_id=100,
            now=self.now,
        )
        self.assertEqual(end_result.status, "slot_found")
        self.assertEqual(end_result.selected.service_end_at, self.shift_end)

    def test_multiple_feasible_slots_choose_lowest_added_travel(self):
        baseline = {
            "visits": [
                {
                    "ticket_id": 1,
                    "worker_id": 10,
                    "sequence": 1,
                    "location_id": 101,
                    "visit_window_start": "2026-09-30T09:00:00+03:00",
                    "visit_window_end": "2026-09-30T12:00:00+03:00",
                    "service_start_at": "2026-09-30T09:00:00+03:00",
                    "service_end_at": "2026-09-30T09:30:00+03:00",
                },
                {
                    "ticket_id": 2,
                    "worker_id": 10,
                    "sequence": 2,
                    "location_id": 102,
                    "visit_window_start": "2026-09-30T11:00:00+03:00",
                    "visit_window_end": "2026-09-30T13:00:00+03:00",
                    "service_start_at": "2026-09-30T11:00:00+03:00",
                    "service_end_at": "2026-09-30T11:30:00+03:00",
                },
            ]
        }
        travel = {
            (100, 200): 20,
            (200, 101): 20,
            (101, 200): 2,
            (200, 102): 2,
            (101, 102): 15,
            (102, 200): 20,
            (200, 100): 20,
        }
        result = find_regular_ticket_slot(
            ticket={
                "id": 99,
                "location_id": 200,
                "estimated_duration_minutes": 30,
                "visit_window_start": "2026-09-30T09:45:00+03:00",
                "visit_window_end": "2026-09-30T10:30:00+03:00",
            },
            candidate_workers=[self.worker_1],
            baseline_state=baseline,
            lifecycle_by_ticket={1: "assigned", 2: "assigned"},
            travel_time_fn=lambda source, target, mode: (
                0 if source == target else travel.get((source, target), 1)
            ),
            office_location_id=100,
            now=self.now,
        )

        self.assertEqual(result.status, "slot_found")
        self.assertEqual(result.selected.insertion_sequence, 2)
        self.assertEqual(result.selected.replaced_travel_minutes, 15)
        self.assertEqual(result.selected.added_travel_minutes, -11)

    def test_first_slot_replaces_existing_office_leg(self):
        self.now = self.shift_start
        baseline = {
            "visits": [
                {
                    "ticket_id": 1,
                    "worker_id": 10,
                    "sequence": 1,
                    "location_id": 101,
                    "service_start_at": "2026-09-30T10:00:00+03:00",
                    "service_end_at": "2026-09-30T10:30:00+03:00",
                }
            ]
        }
        travel = {(100, 101): 20, (100, 102): 5, (102, 101): 5}
        result = find_regular_ticket_slot(
            ticket={
                "id": 99,
                "location_id": 102,
                "estimated_duration_minutes": 30,
                "visit_window_start": "2026-09-30T08:00:00+03:00",
                "visit_window_end": "2026-09-30T09:00:00+03:00",
            },
            candidate_workers=[self.worker_1],
            baseline_state=baseline,
            lifecycle_by_ticket={1: "assigned"},
            travel_time_fn=lambda source, target, mode: (
                0 if source == target else travel.get((source, target), 15)
            ),
            office_location_id=100,
            now=self.now,
        )
        self.assertEqual(result.status, "slot_found")
        self.assertEqual(result.selected.insertion_sequence, 1)
        self.assertEqual(result.selected.replaced_travel_minutes, 20)
        self.assertEqual(result.selected.added_travel_minutes, -10)

    def test_existing_worker_precedes_idle_worker_in_objective(self):
        baseline = {
            "visits": [
                {
                    "ticket_id": 1,
                    "worker_id": 10,
                    "sequence": 1,
                    "location_id": 101,
                    "visit_window_start": "2026-09-30T09:00:00+03:00",
                    "visit_window_end": "2026-09-30T10:00:00+03:00",
                    "service_start_at": "2026-09-30T09:00:00+03:00",
                    "service_end_at": "2026-09-30T09:30:00+03:00",
                }
            ]
        }
        result = find_regular_ticket_slot(
            ticket={
                "id": 99,
                "location_id": 200,
                "estimated_duration_minutes": 30,
                "visit_window_start": "2026-09-30T12:00:00+03:00",
                "visit_window_end": "2026-09-30T13:00:00+03:00",
            },
            candidate_workers=[self.worker_1, {**self.worker_2, "office_location_id": 200}],
            baseline_state=baseline,
            lifecycle_by_ticket={1: "assigned"},
            travel_time_fn=self.travel_fn,
            office_location_id=100,
            now=self.now,
            return_to_office=False,
        )
        self.assertEqual(result.status, "slot_found")
        self.assertEqual(result.selected.worker_id, 10)
        self.assertEqual(result.selected.insertion_sequence, 2)

    def test_open_end_can_finish_at_shift_end_without_return_trip(self):
        self.now = self.shift_end - timedelta(minutes=45)
        ticket = {
            "id": 99,
            "location_id": 200,
            "estimated_duration_minutes": 30,
            "visit_window_start": "2026-09-30T19:30:00+03:00",
            "visit_window_end": "2026-09-30T20:00:00+03:00",
        }
        kwargs = dict(
            ticket=ticket,
            candidate_workers=[self.worker_1],
            baseline_state={"visits": []},
            lifecycle_by_ticket={},
            travel_time_fn=self.travel_fn,
            office_location_id=100,
            now=self.now,
        )
        self.assertEqual(find_regular_ticket_slot(**kwargs).status, "not_insertable")
        open_result = find_regular_ticket_slot(**kwargs, return_to_office=False)
        self.assertEqual(open_result.status, "slot_found")
        self.assertEqual(open_result.selected.service_end_at, self.shift_end)

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

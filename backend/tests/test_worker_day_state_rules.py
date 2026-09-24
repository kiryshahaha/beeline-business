"""Deterministic reduction of worker execution facts."""

import unittest
from datetime import UTC, datetime

from app.modules.execution.day_state import reduce_worker_day_events


class WorkerDayStateRuleTests(unittest.TestCase):
    def test_completed_visit_and_started_work_keep_last_confirmed_point(self):
        state = reduce_worker_day_events(
            [
                {
                    "event_type": "complete",
                    "occurred_at": datetime(2026, 9, 17, 10, tzinfo=UTC),
                    "payload": {"location_id": 101, "worker_id": 7},
                },
                {
                    "event_type": "start",
                    "occurred_at": datetime(2026, 9, 17, 11, tzinfo=UTC),
                    "payload": {"ticket_id": 202, "worker_id": 7},
                },
            ]
        )
        self.assertEqual(state["last_location_id"], 101)
        self.assertEqual(state["current_ticket_id"], 202)

    def test_en_route_does_not_move_worker_to_an_unconfirmed_destination(self):
        state = reduce_worker_day_events(
            [
                {
                    "event_type": "start_route",
                    "occurred_at": datetime(2026, 9, 17, 12, tzinfo=UTC),
                    "payload": {
                        "location_id": 101,
                        "destination_id": 202,
                        "worker_id": 7,
                    },
                }
            ]
        )
        self.assertEqual(state["last_location_id"], 101)
        self.assertEqual(state["current_destination_id"], 202)

    def test_unavailable_is_terminal_for_the_shift(self):
        state = reduce_worker_day_events(
            [
                {
                    "event_type": "worker_unavailable",
                    "occurred_at": datetime(2026, 9, 17, 13, tzinfo=UTC),
                    "payload": {"expected_available_at": "2026-09-17T18:00:00+00:00"},
                }
            ]
        )
        self.assertFalse(state["available"])
        self.assertEqual(state["expected_available_at"].hour, 18)

    def test_delay_updates_expected_availability_without_losing_current_work(self):
        state = reduce_worker_day_events(
            [
                {
                    "event_type": "start",
                    "occurred_at": datetime(2026, 9, 17, 11, tzinfo=UTC),
                    "payload": {"ticket_id": 202, "location_id": 101},
                },
                {
                    "event_type": "progress_delay",
                    "occurred_at": datetime(2026, 9, 17, 12, tzinfo=UTC),
                    "payload": {
                        "ticket_id": 202,
                        "expected_available_at": "2026-09-17T14:00:00+00:00",
                        "reason": "Нужна дополнительная работа",
                    },
                },
            ]
        )
        self.assertEqual(state["current_ticket_id"], 202)
        self.assertEqual(state["expected_available_at"].hour, 14)
        self.assertEqual(state["reason"], "Нужна дополнительная работа")

"""Tests for T4-02: baseline state, frozen stops and immutable route invariants."""

import unittest

from app.modules.planning.day_plans import (
    classify_stops,
    get_worker_safe_point,
    validate_immutable_route_invariants,
)


class DayPlanBaselineTests(unittest.TestCase):
    def visit(self, ticket_id, worker_id, sequence, start="10:00:00", end="10:30:00"):
        return {
            "ticket_id": ticket_id,
            "worker_id": worker_id,
            "sequence": sequence,
            "arrival_at": f"2026-09-30T{start}+03:00",
            "service_start_at": f"2026-09-30T{start}+03:00",
            "service_end_at": f"2026-09-30T{end}+03:00",
        }

    def test_classify_stops(self):
        plan_state = {
            "visits": [
                self.visit(1, 10, 1),
                self.visit(2, 10, 2),
                self.visit(3, 10, 3),
                self.visit(4, 11, 1),
            ]
        }
        lifecycle = {
            1: "completed",
            2: "in_progress",
            3: "assigned",
            4: "en_route",
        }
        classes = classify_stops(plan_state, lifecycle)
        self.assertEqual([v["ticket_id"] for v in classes["completed"]], [1])
        self.assertEqual([v["ticket_id"] for v in classes["in_flight"]], [2, 4])
        self.assertEqual([v["ticket_id"] for v in classes["future"]], [3])

    def test_get_worker_safe_point_in_flight(self):
        plan_state = {
            "visits": [
                self.visit(1, 10, 1, start="09:00:00", end="09:30:00"),
                self.visit(2, 10, 2, start="10:00:00", end="10:45:00"),
                self.visit(3, 10, 3, start="11:30:00", end="12:00:00"),
            ]
        }
        lifecycle = {1: "completed", 2: "in_progress", 3: "assigned"}
        safe_point = get_worker_safe_point(10, plan_state, lifecycle)
        self.assertTrue(safe_point["is_frozen"])
        self.assertEqual(safe_point["frozen_ticket_id"], 2)
        self.assertEqual(safe_point["available_at"], "2026-09-30T10:45:00+03:00")
        self.assertEqual(safe_point["frozen_sequence"], 2)

    def test_get_worker_safe_point_unstarted(self):
        plan_state = {
            "visits": [
                self.visit(1, 10, 1, start="09:00:00", end="09:30:00"),
                self.visit(2, 10, 2, start="10:00:00", end="10:45:00"),
            ]
        }
        lifecycle = {1: "assigned", 2: "assigned"}
        safe_point = get_worker_safe_point(10, plan_state, lifecycle, default_location_id=99)
        self.assertFalse(safe_point["is_frozen"])
        self.assertIsNone(safe_point["frozen_ticket_id"])
        self.assertEqual(safe_point["safe_location_id"], 99)

    def test_valid_regular_insertion_passes_invariants(self):
        baseline = {
            "visits": [
                self.visit(1, 10, 1, start="09:00:00", end="09:30:00"),
                self.visit(2, 10, 2, start="10:30:00", end="11:00:00"),
            ]
        }
        # Ticket 99 inserted between 1 and 2
        proposed = {
            "visits": [
                self.visit(1, 10, 1, start="09:00:00", end="09:30:00"),
                self.visit(99, 10, 2, start="09:45:00", end="10:15:00"),
                self.visit(2, 10, 3, start="10:30:00", end="11:00:00"),
            ]
        }
        lifecycle = {1: "completed", 2: "assigned"}
        violations = validate_immutable_route_invariants(
            baseline, proposed, inserted_ticket_id=99, lifecycle_by_ticket=lifecycle
        )
        self.assertEqual(violations, [])

    def test_reassigning_existing_ticket_fails_invariants(self):
        baseline = {
            "visits": [
                self.visit(1, 10, 1),
                self.visit(2, 10, 2),
            ]
        }
        # Existing ticket 2 reassigned to worker 11!
        proposed = {
            "visits": [
                self.visit(1, 10, 1),
                self.visit(99, 10, 2),
                self.visit(2, 11, 1),
            ]
        }
        violations = validate_immutable_route_invariants(baseline, proposed, inserted_ticket_id=99)
        self.assertTrue(any("worker_assignment_changed" in v for v in violations))

    def test_permuting_existing_tickets_fails_invariants(self):
        baseline = {
            "visits": [
                self.visit(1, 10, 1),
                self.visit(2, 10, 2),
                self.visit(3, 10, 3),
            ]
        }
        # Ticket 3 moved before 2!
        proposed = {
            "visits": [
                self.visit(1, 10, 1),
                self.visit(3, 10, 2),
                self.visit(99, 10, 3),
                self.visit(2, 10, 4),
            ]
        }
        violations = validate_immutable_route_invariants(baseline, proposed, inserted_ticket_id=99)
        self.assertTrue(any("relative_order_violated" in v for v in violations))

    def test_frozen_in_flight_stop_cannot_be_altered(self):
        baseline = {
            "visits": [
                self.visit(1, 10, 1, start="09:00:00", end="09:30:00"),
                self.visit(2, 10, 2, start="10:00:00", end="10:30:00"),
            ]
        }
        # In-flight ticket 1 sequence was modified!
        proposed = {
            "visits": [
                self.visit(99, 10, 1, start="08:30:00", end="09:00:00"),
                self.visit(1, 10, 2, start="09:15:00", end="09:45:00"),
                self.visit(2, 10, 3, start="10:00:00", end="10:30:00"),
            ]
        }
        lifecycle = {1: "in_progress", 2: "assigned"}
        violations = validate_immutable_route_invariants(
            baseline, proposed, inserted_ticket_id=99, lifecycle_by_ticket=lifecycle
        )
        self.assertTrue(any("frozen_sequence_changed" in v for v in violations))
        self.assertTrue(any("frozen_time_changed" in v for v in violations))


if __name__ == "__main__":
    unittest.main()

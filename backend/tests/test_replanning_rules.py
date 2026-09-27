"""Rules for anchoring a remaining-day route to execution facts."""

import unittest
from datetime import UTC, datetime

from app.modules.planning.day_plans import build_replan_state
from app.modules.planning.diagnostics import outcome
from app.modules.planning.eligibility import worker_replan_anchor
from app.modules.planning.errors import PlanningError
from app.modules.planning.service import validate_replan_limits


class ReplanningAnchorTests(unittest.TestCase):
    def test_worker_without_execution_events_starts_from_known_base_at_current_time(self):
        now = datetime(2026, 9, 27, 12, tzinfo=UTC)

        anchor = worker_replan_anchor(None, None, now, default_location_id=5)

        self.assertEqual(anchor, {"location_id": 5, "available_at": now, "reason": None})

    def test_unavailable_worker_returns_at_dispatcher_eta(self):
        now = datetime(2026, 9, 27, 12, tzinfo=UTC)
        eta = datetime(2026, 9, 27, 13, 30, tzinfo=UTC)

        anchor = worker_replan_anchor(
            {
                "available": False,
                "last_location_id": 41,
                "expected_available_at": eta,
            },
            None,
            now,
            default_location_id=5,
        )

        self.assertEqual(anchor, {"location_id": 41, "available_at": eta, "reason": None})

    def test_en_route_worker_keeps_the_in_flight_destination_as_future_anchor(self):
        now = datetime(2026, 9, 27, 12, tzinfo=UTC)
        eta = datetime(2026, 9, 27, 14, tzinfo=UTC)

        anchor = worker_replan_anchor(
            {
                "current_ticket_id": 90,
                "last_location_id": 41,
                "current_destination_id": 75,
                "expected_available_at": eta,
            },
            {"planned_end_at": datetime(2026, 9, 27, 15, tzinfo=UTC)},
            now,
            default_location_id=5,
        )

        self.assertEqual(anchor, {"location_id": 75, "available_at": eta, "reason": None})

    def test_active_work_without_a_future_eta_is_not_scheduled_over(self):
        now = datetime(2026, 9, 27, 12, tzinfo=UTC)

        anchor = worker_replan_anchor(
            {"current_ticket_id": 90, "last_location_id": 41},
            {"planned_end_at": datetime(2026, 9, 27, 11, tzinfo=UTC)},
            now,
            default_location_id=5,
        )

        self.assertEqual(anchor["reason"], "active_work_eta_unknown")
        self.assertIsNone(anchor["available_at"])


class ReplanningLimitTests(unittest.TestCase):
    def test_area_wide_replan_reports_solver_limits_before_request_validation(self):
        with self.assertRaises(PlanningError) as caught:
            validate_replan_limits(101, 21, max_tickets=100, max_workers=20)

        self.assertEqual(caught.exception.code, "planning_limit_exceeded")
        self.assertEqual(caught.exception.details["requested_tickets"], 101)
        self.assertEqual(caught.exception.details["requested_workers"], 21)


class ReplanningStateTests(unittest.TestCase):
    def visit(self, ticket_id, worker_id, sequence):
        return {
            "ticket_id": ticket_id,
            "worker_id": worker_id,
            "route_id": ticket_id + 100,
            "sequence": sequence,
            "arrival_at": f"2026-09-27T{8 + sequence:02d}:00:00+00:00",
            "service_start_at": f"2026-09-27T{8 + sequence:02d}:05:00+00:00",
            "service_end_at": f"2026-09-27T{8 + sequence:02d}:35:00+00:00",
        }

    def test_replan_preserves_frozen_visits_and_removes_cancelled_or_dropped_work(self):
        previous = {
            "visits": [
                self.visit(1, 7, 1),
                self.visit(2, 7, 2),
                self.visit(3, 7, 3),
                self.visit(4, 8, 1),
            ],
            "metrics": {},
        }
        proposal = {
            "route_date": "2026-09-27",
            "plan_id": "new-plan",
            "outcome": "partial",
            "unassigned": [{"ticket_id": 6}],
            "metrics": {"assigned_tickets": 2, "unassigned_tickets": 1},
            "routes": [
                {
                    "worker_id": 7,
                    "stops": [
                        {
                            "ticket_id": 3,
                            "location_id": 31,
                            "sequence": 1,
                            "arrival_at": "new",
                            "service_start_at": "new",
                            "service_end_at": "new",
                        },
                        {
                            "ticket_id": 5,
                            "location_id": 35,
                            "sequence": 2,
                            "arrival_at": "newer",
                            "service_start_at": "newer",
                            "service_end_at": "newer",
                        },
                    ],
                }
            ],
        }

        result = build_replan_state(
            proposal,
            previous,
            {1: "completed", 2: "en_route", 3: "assigned", 4: "cancelled", 6: "waiting_assignment"},
            {7: 300},
        )

        visits = {visit["ticket_id"]: visit for visit in result["visits"]}
        self.assertEqual(set(visits), {1, 2, 3, 5})
        self.assertEqual(visits[1], previous["visits"][0])
        self.assertEqual(visits[2], previous["visits"][1])
        self.assertEqual(visits[3]["sequence"], 3)
        self.assertEqual(visits[3]["route_id"], 300)
        self.assertEqual(result["unassigned_ticket_ids"], [6])

    def test_empty_outcome_remains_for_regular_preview_with_no_routes(self):
        self.assertEqual(outcome([], [{"ticket_id": 1}]), "empty")
        self.assertEqual(outcome([], []), "empty")


if __name__ == "__main__":
    unittest.main()

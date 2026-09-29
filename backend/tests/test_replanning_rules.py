"""Rules for anchoring a remaining-day route to execution facts."""

import json
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

from app.modules.planning.day_plans import build_replan_state
from app.modules.planning.diagnostics import outcome
from app.modules.planning.eligibility import worker_replan_anchor
from app.modules.planning.errors import PlanningError
from app.modules.planning.schemas import ExperimentalWindowOverride
from app.modules.planning.service import (
    _ordinary_insert_ticket_ids,
    _pin_existing_visits_for_ordinary_insert,
    emergency_response_estimates,
    snapshot_with_experimental_windows,
    ticket_event_policy,
    validate_replan_limits,
)


class ReplanningAnchorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = (
            Path(__file__).resolve().parents[2] / "data/planning/dynamic_replanning_scenarios.json"
        )
        cls.synthetic = json.loads(path.read_text(encoding="utf-8"))

    def test_ticket_event_policy_uses_persisted_category(self):
        self.assertEqual(ticket_event_policy("emergency"), "emergency_replan")
        self.assertEqual(ticket_event_policy("repair"), "regular_insert")
        with self.assertRaises(PlanningError) as error:
            ticket_event_policy("unknown")
        self.assertEqual(error.exception.code, "ticket_category_invalid")

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

    def test_en_route_worker_is_not_routed_before_the_active_stage_completes(self):
        now = datetime(2026, 9, 27, 12, tzinfo=UTC)
        eta = datetime(2026, 9, 27, 14, tzinfo=UTC)

        anchor = worker_replan_anchor(
            {
                "current_ticket_id": 90,
                "last_location_id": 41,
                "current_destination_id": 75,
                "expected_available_at": eta,
            },
            {
                "planned_end_at": datetime(2026, 9, 27, 15, tzinfo=UTC),
                "lifecycle_state": "en_route",
            },
            now,
            default_location_id=5,
        )

        self.assertEqual(
            anchor,
            {
                "location_id": 75,
                "available_at": eta,
                "reason": "active_stage_not_completed",
            },
        )

    def test_completed_worker_starts_from_confirmed_location_and_actual_time(self):
        now = datetime(2026, 9, 27, 12, tzinfo=UTC)

        anchor = worker_replan_anchor(
            {
                "current_ticket_id": None,
                "last_location_id": 75,
                "current_destination_id": None,
            },
            None,
            now,
            default_location_id=5,
        )

        self.assertEqual(anchor, {"location_id": 75, "available_at": now, "reason": None})

    def test_synthetic_active_stage_cases_keep_worker_out_until_completion(self):
        for case in self.synthetic["active_stage_cases"]:
            with self.subTest(case=case["id"]):
                if case["lifecycle_state"] == "completed":
                    anchor = worker_replan_anchor(
                        {
                            "current_ticket_id": None,
                            "last_location_id": case["last_location_id"],
                        },
                        None,
                        datetime.fromisoformat(case["actual_completed_at"]),
                        default_location_id=1,
                    )
                    self.assertIsNone(anchor["reason"])
                    self.assertEqual(anchor["location_id"], case["expected_anchor_location_id"])
                    self.assertEqual(anchor["available_at"].isoformat(), case["expected_anchor_at"])
                else:
                    anchor = worker_replan_anchor(
                        {
                            "current_ticket_id": 10,
                            "last_location_id": 41,
                            "current_destination_id": 75,
                            "expected_available_at": datetime.fromisoformat(
                                case["expected_available_at"]
                            ),
                        },
                        {"lifecycle_state": case["lifecycle_state"]},
                        datetime.fromisoformat(case["received_at"]),
                        default_location_id=1,
                    )
                    self.assertFalse(case["expected_worker_eligible"])
                    self.assertEqual(anchor["reason"], "active_stage_not_completed")

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

    def test_experimental_windows_only_expand_a_copy_of_the_input(self):
        snapshot = {
            "tickets": [
                {
                    "id": 4,
                    "visit_window_start": "2030-01-15T10:00:00+03:00",
                    "visit_window_end": "2030-01-15T12:00:00+03:00",
                }
            ]
        }
        windows = [
            ExperimentalWindowOverride(
                ticket_id=4,
                visit_window_start="2030-01-15T09:00:00+03:00",
                visit_window_end="2030-01-15T14:00:00+03:00",
            )
        ]

        scenario = snapshot_with_experimental_windows(snapshot, windows, date(2030, 1, 15))

        self.assertEqual(snapshot["tickets"][0]["visit_window_start"], "2030-01-15T10:00:00+03:00")
        self.assertEqual(scenario["tickets"][0]["visit_window_start"], "2030-01-15T09:00:00+03:00")
        self.assertEqual(scenario["tickets"][0]["visit_window_end"], "2030-01-15T14:00:00+03:00")

    def test_experiment_rejects_window_shrink_unknown_ticket_and_other_day(self):
        snapshot = {
            "tickets": [
                {
                    "id": 4,
                    "visit_window_start": "2030-01-15T10:00:00+03:00",
                    "visit_window_end": "2030-01-15T12:00:00+03:00",
                }
            ]
        }
        cases = (
            ExperimentalWindowOverride(
                ticket_id=4,
                visit_window_start="2030-01-15T11:00:00+03:00",
                visit_window_end="2030-01-15T13:00:00+03:00",
            ),
            ExperimentalWindowOverride(
                ticket_id=9,
                visit_window_start="2030-01-15T09:00:00+03:00",
                visit_window_end="2030-01-15T14:00:00+03:00",
            ),
            ExperimentalWindowOverride(
                ticket_id=4,
                visit_window_start="2030-01-16T09:00:00+03:00",
                visit_window_end="2030-01-16T14:00:00+03:00",
            ),
        )
        expected = (
            "experimental_window_must_only_expand",
            "experimental_ticket_not_in_day",
            "experimental_window_outside_day",
        )
        for override, code in zip(cases, expected, strict=True):
            with self.subTest(code=code), self.assertRaises(PlanningError) as caught:
                snapshot_with_experimental_windows(snapshot, [override], date(2030, 1, 15))
            self.assertEqual(caught.exception.code, code)


class OrdinaryInsertRulesTests(unittest.TestCase):
    def test_area_backlog_created_before_the_published_revision_is_not_new_demand(self):
        snapshot = {
            "current_day_state": {
                "visits": [{"ticket_id": 1}],
                "unassigned_ticket_ids": [],
                "area_scope_tickets": [
                    {"id": 1, "assigned_worker_id": 10},
                    {"id": 2, "assigned_worker_id": None},
                ],
            },
            "tickets": [
                {"id": 1, "category": "repair", "lifecycle_state": "assigned"},
                {
                    "id": 2,
                    "category": "repair",
                    "lifecycle_state": "waiting_assignment",
                    "assigned_worker_id": None,
                },
            ],
        }

        self.assertIsNone(_ordinary_insert_ticket_ids(snapshot))

    def test_request_absent_from_published_area_scope_is_new_demand(self):
        snapshot = {
            "current_day_state": {
                "visits": [{"ticket_id": 1}],
                "unassigned_ticket_ids": [],
                "area_scope_tickets": [{"id": 1, "assigned_worker_id": 10}],
            },
            "tickets": [
                {"id": 1, "category": "repair", "lifecycle_state": "assigned"},
                {
                    "id": 2,
                    "category": "repair",
                    "lifecycle_state": "waiting_assignment",
                },
            ],
        }

        self.assertEqual(_ordinary_insert_ticket_ids(snapshot), {2})

    def test_new_manual_assignment_of_an_existing_request_is_new_demand(self):
        snapshot = {
            "current_day_state": {
                "visits": [{"ticket_id": 1}],
                "unassigned_ticket_ids": [],
                "area_scope_tickets": [
                    {"id": 1, "assigned_worker_id": 10},
                    {"id": 2, "assigned_worker_id": None},
                ],
            },
            "tickets": [
                {"id": 1, "category": "repair", "lifecycle_state": "assigned"},
                {
                    "id": 2,
                    "category": "repair",
                    "lifecycle_state": "assigned",
                    "assigned_worker_id": 11,
                },
            ],
        }

        self.assertEqual(_ordinary_insert_ticket_ids(snapshot), {2})

    def test_new_regular_ticket_is_pinned_around_published_visits(self):
        snapshot = {
            "current_day_state": {
                "visits": [
                    {
                        "ticket_id": 1,
                        "worker_id": 10,
                        "service_start_at": "2030-01-15T10:00:00+03:00",
                    },
                    {
                        "ticket_id": 2,
                        "worker_id": 10,
                        "service_start_at": "2030-01-15T13:00:00+03:00",
                    },
                ],
                "unassigned_ticket_ids": [],
            },
            "tickets": [
                {"id": 1, "category": "repair", "lifecycle_state": "assigned"},
                {"id": 2, "category": "repair", "lifecycle_state": "assigned"},
                {"id": 7, "category": "repair", "lifecycle_state": "waiting_assignment"},
            ],
        }
        self.assertEqual(_ordinary_insert_ticket_ids(snapshot), {7})
        prepared = {
            "epoch": datetime.fromisoformat("2030-01-15T06:00:00+00:00"),
            "workers": [{"user_id": 10}],
            "tickets": [
                {"id": 1, "assigned_worker_id": 10, "allowed": [0], "window": (60, 60)},
                {"id": 2, "assigned_worker_id": 10, "allowed": [0], "window": (240, 240)},
                {"id": 7, "assigned_worker_id": None, "allowed": [0], "window": (120, 180)},
            ],
            "unassigned": [],
        }

        preserved = _pin_existing_visits_for_ordinary_insert(prepared, snapshot, {7})

        self.assertEqual(preserved, {1, 2})
        self.assertEqual(prepared["tickets"][0]["allowed"], [0])
        self.assertEqual(prepared["tickets"][0]["window"], (60, 60))
        self.assertEqual(prepared["tickets"][1]["window"], (240, 240))
        self.assertEqual(prepared["tickets"][2]["window"], (120, 180))

    def test_new_emergency_uses_emergency_replan_branch(self):
        snapshot = {
            "current_day_state": {"visits": [{"ticket_id": 1, "worker_id": 10}]},
            "tickets": [
                {"id": 1, "category": "repair", "lifecycle_state": "assigned"},
                {"id": 7, "category": "emergency", "lifecycle_state": "waiting_assignment"},
            ],
        }

        self.assertIsNone(_ordinary_insert_ticket_ids(snapshot))

    def test_synthetic_emergency_response_cases_measure_from_received_at(self):
        path = (
            Path(__file__).resolve().parents[2] / "data/planning/dynamic_replanning_scenarios.json"
        )
        cases = json.loads(path.read_text(encoding="utf-8"))["response_cases"]
        for index, case in enumerate(cases, start=1):
            with self.subTest(case=case["id"]):
                estimate = emergency_response_estimates(
                    {
                        "tickets": [
                            {
                                "id": index,
                                "category": "emergency",
                                "received_at": case["received_at"],
                                "sla_deadline_at": case["service_deadline_at"],
                            }
                        ]
                    },
                    {
                        "routes": [
                            {
                                "stops": [
                                    {
                                        "ticket_id": index,
                                        "arrival_at": case["arrival_at"],
                                        "service_start_at": case["service_start_at"],
                                        "service_end_at": case["service_end_at"],
                                    }
                                ]
                            }
                        ],
                        "unassigned": [],
                    },
                )[0]
                self.assertEqual(
                    estimate["reaction_to_arrival_minutes"], case["expected_arrival_minutes"]
                )
                self.assertEqual(
                    estimate["reaction_to_service_start_minutes"],
                    case["expected_service_start_minutes"],
                )
                self.assertEqual(
                    estimate["within_60_minutes_to_arrival"], case["expected_within_60"]
                )
                self.assertEqual(
                    estimate["within_120_minutes_to_arrival"], case["expected_within_120"]
                )
                self.assertEqual(estimate["service_deadline_met"], case["expected_deadline_met"])

    def test_emergency_response_estimate_uses_service_start_and_ticket_deadline(self):
        estimate = emergency_response_estimates(
            {
                "tickets": [
                    {
                        "id": 61,
                        "category": "emergency",
                        "received_at": "2030-01-15T09:00:00+03:00",
                        "response_deadline_at": "2030-01-15T10:00:00+03:00",
                    }
                ]
            },
            {
                "routes": [
                    {
                        "stops": [
                            {
                                "ticket_id": 61,
                                "arrival_at": "2030-01-15T09:30:00+03:00",
                                "service_start_at": "2030-01-15T10:01:00+03:00",
                                "service_end_at": "2030-01-15T10:31:00+03:00",
                            }
                        ]
                    }
                ],
                "unassigned": [],
            },
        )[0]

        self.assertEqual(estimate["reaction_to_service_start_minutes"], 61)
        self.assertFalse(estimate["response_deadline_met"])
        self.assertEqual(estimate["response_lateness_minutes"], 1)
        self.assertFalse(estimate["within_60_minutes_to_service_start"])
        self.assertTrue(estimate["within_120_minutes_to_service_start"])

    def test_emergency_response_does_not_hide_a_pre_receipt_arrival(self):
        estimate = emergency_response_estimates(
            {
                "tickets": [
                    {
                        "id": 62,
                        "category": "emergency",
                        "received_at": "2030-01-15T10:00:00+03:00",
                        "response_deadline_at": "2030-01-15T11:00:00+03:00",
                    }
                ]
            },
            {
                "routes": [
                    {
                        "stops": [
                            {
                                "ticket_id": 62,
                                "arrival_at": "2030-01-15T09:50:00+03:00",
                                "service_start_at": "2030-01-15T10:05:00+03:00",
                                "service_end_at": "2030-01-15T10:35:00+03:00",
                            }
                        ]
                    }
                ],
                "unassigned": [],
            },
        )[0]

        self.assertEqual(estimate["reaction_to_arrival_minutes"], -10)
        self.assertEqual(estimate["reaction_to_service_start_minutes"], 5)
        self.assertTrue(estimate["response_timeline_valid"])
        self.assertTrue(estimate["response_deadline_met"])
        self.assertFalse(estimate["within_60_minutes_to_arrival"])
        self.assertTrue(estimate["within_60_minutes_to_service_start"])

    def test_unassigned_emergency_reports_response_target_as_unmet(self):
        estimate = emergency_response_estimates(
            {
                "tickets": [
                    {
                        "id": 63,
                        "category": "emergency",
                        "received_at": "2030-01-15T10:00:00+03:00",
                        "response_deadline_at": "2030-01-15T11:00:00+03:00",
                    }
                ]
            },
            {"routes": [], "unassigned": [{"ticket_id": 63, "reason": {"code": "no_slot"}}]},
        )[0]

        self.assertEqual(estimate["status"], "unassigned")
        self.assertEqual(estimate["response_sla_status"], "unassigned")
        self.assertFalse(estimate["response_deadline_met"])
        self.assertEqual(estimate["response_target_minutes"], 60)


if __name__ == "__main__":
    unittest.main()

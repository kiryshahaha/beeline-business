"""T4-05 event contracts and local insertion decisions."""

import json
import unittest
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from app.modules.planning.errors import PlanningError
from app.modules.planning.schemas import TicketEventPreviewRequest
from app.modules.planning.service import build_ticket_event_result, ticket_event_policy
from app.modules.planning.slot_finder import find_regular_ticket_slot


class TicketEventRequestTests(unittest.TestCase):
    def test_policy_is_not_a_client_selectable_request_field(self):
        request = TicketEventPreviewRequest(base_day_revision=4)
        self.assertEqual(request.base_day_revision, 4)
        with self.assertRaises(ValidationError):
            TicketEventPreviewRequest(base_day_revision=4, mode="emergency")

    def test_policy_matches_server_category_in_dynamic_fixture(self):
        fixture_path = Path(__file__).parents[2] / "data/planning/dynamic_replanning_scenarios.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        for case in fixture["event_policy_cases"]:
            with self.subTest(case=case["id"]):
                expected = (
                    "emergency_replan"
                    if case["server_category"] == "emergency"
                    else "regular_insert"
                )
                self.assertFalse(case["client_mode_field_allowed"])
                self.assertEqual(ticket_event_policy(case["server_category"]), expected)

    def test_unknown_category_is_not_routed_to_either_policy(self):
        with self.assertRaises(PlanningError) as error:
            ticket_event_policy("unknown")
        self.assertEqual(error.exception.code, "ticket_category_invalid")


class TicketEventSlotTests(unittest.TestCase):
    def test_insertion_after_completed_visit_uses_current_time(self):
        now = datetime.fromisoformat("2030-01-15T10:00:00+03:00")
        result = find_regular_ticket_slot(
            ticket={
                "id": 2,
                "location_id": 3,
                "estimated_duration_minutes": 30,
                "visit_window_start": "2030-01-15T10:00:00+03:00",
                "visit_window_end": "2030-01-15T17:00:00+03:00",
            },
            candidate_workers=[
                {
                    "user_id": 7,
                    "skills": set(),
                    "transport_type": "car",
                    "shift_start_at": "2030-01-15T08:00:00+03:00",
                    "shift_end_at": "2030-01-15T17:00:00+03:00",
                    "office_location_id": 1,
                }
            ],
            baseline_state={
                "visits": [
                    {
                        "ticket_id": 1,
                        "worker_id": 7,
                        "sequence": 1,
                        "location_id": 2,
                        "arrival_at": "2030-01-15T08:30:00+03:00",
                        "service_start_at": "2030-01-15T08:30:00+03:00",
                        "service_end_at": "2030-01-15T09:00:00+03:00",
                    }
                ]
            },
            lifecycle_by_ticket={1: "completed"},
            travel_time_fn=lambda _from, _to, _profile: 5,
            office_location_id=1,
            now=now,
        )

        self.assertEqual(result.status, "slot_found")
        self.assertEqual(result.selected.insertion_sequence, 2)
        self.assertGreaterEqual(result.selected.estimated_arrival_at, now)
        self.assertEqual(result.selected.travel_to_minutes, 5)
        self.assertEqual(result.selected.travel_from_minutes, 5)


class TicketEventOutcomeTests(unittest.TestCase):
    def test_emergency_response_over_two_hours_is_reported_as_sla_violation(self):
        event = {
            "source_event_id": 50,
            "event_type": "new_ticket",
            "ticket_id": 90,
            "category": "emergency",
            "request_type_hd": "авария",
            "received_at": "2030-01-15T08:00:00+03:00",
        }
        snapshot = {
            "area_scope": {"tickets": []},
            "current_day_state": {"visits": []},
        }
        public = {
            "routes": [
                {
                    "worker_id": 7,
                    "stops": [
                        {
                            "ticket_id": 90,
                            "sequence": 1,
                            "arrival_at": "2030-01-15T11:00:00+03:00",
                            "service_start_at": "2030-01-15T11:05:00+03:00",
                            "service_end_at": "2030-01-15T11:35:00+03:00",
                            "effective_service_minutes": 30,
                        }
                    ],
                }
            ],
            "replan_diff": {
                "emergency_response": [
                    {
                        "ticket_id": 90,
                        "received_at": event["received_at"],
                        "arrival_at": "2030-01-15T11:00:00+03:00",
                        "service_start_at": "2030-01-15T11:05:00+03:00",
                        "service_end_at": "2030-01-15T11:35:00+03:00",
                        "reaction_to_arrival_minutes": 180,
                        "reaction_to_service_start_minutes": 185,
                        "within_60_minutes_to_arrival": False,
                        "within_120_minutes_to_arrival": False,
                        "service_deadline_at": None,
                        "service_deadline_met": None,
                        "status": "scheduled",
                        "unassigned_reason": None,
                    }
                ]
            },
            "unassigned": [],
        }

        result = build_ticket_event_result(
            event, snapshot, {"workers": [], "excluded_workers": []}, public
        )

        self.assertEqual(result["outcome"], "sla_violation")
        self.assertTrue(result["can_apply"])
        self.assertEqual(result["sla_forecast"]["reaction_to_arrival_minutes"], 180)

    def test_missed_response_deadline_overrides_lower_reaction_risk(self):
        event = {
            "source_event_id": 50,
            "event_type": "new_ticket",
            "ticket_id": 90,
            "category": "emergency",
            "request_type_hd": "авария",
            "received_at": "2030-01-15T08:00:00+03:00",
        }
        snapshot = {"area_scope": {"tickets": []}, "current_day_state": {"visits": []}}
        public = {
            "routes": [
                {
                    "worker_id": 7,
                    "stops": [
                        {
                            "ticket_id": 90,
                            "sequence": 1,
                            "arrival_at": "2030-01-15T09:00:00+03:00",
                            "service_start_at": "2030-01-15T09:10:00+03:00",
                            "service_end_at": "2030-01-15T09:40:00+03:00",
                            "effective_service_minutes": 30,
                        }
                    ],
                }
            ],
            "replan_diff": {
                "emergency_response": [
                    {
                        "ticket_id": 90,
                        "reaction_to_service_start_minutes": 70,
                        "response_deadline_met": False,
                    }
                ]
            },
            "unassigned": [],
        }

        result = build_ticket_event_result(
            event, snapshot, {"workers": [], "excluded_workers": []}, public
        )

        self.assertEqual(result["outcome"], "sla_violation")

    def test_service_completion_deadline_does_not_override_response_forecast(self):
        event = {
            "source_event_id": 51,
            "event_type": "new_ticket",
            "ticket_id": 91,
            "category": "emergency",
            "request_type_hd": "авария",
            "received_at": "2030-01-15T08:00:00+03:00",
            "response_deadline_at": "2030-01-15T10:00:00+03:00",
        }
        snapshot = {"area_scope": {"tickets": []}, "current_day_state": {"visits": []}}
        public = {
            "routes": [
                {
                    "worker_id": 7,
                    "stops": [
                        {
                            "ticket_id": 91,
                            "sequence": 1,
                            "arrival_at": "2030-01-15T08:40:00+03:00",
                            "service_start_at": "2030-01-15T08:45:00+03:00",
                            "service_end_at": "2030-01-15T09:15:00+03:00",
                            "effective_service_minutes": 30,
                        }
                    ],
                }
            ],
            "replan_diff": {
                "emergency_response": [
                    {
                        "ticket_id": 91,
                        "reaction_to_service_start_minutes": 45,
                        "response_deadline_met": True,
                        "service_deadline_met": False,
                    }
                ]
            },
            "unassigned": [],
        }

        result = build_ticket_event_result(
            event, snapshot, {"workers": [], "excluded_workers": []}, public
        )

        self.assertEqual(result["outcome"], "emergency_replan_ready")
        self.assertTrue(result["can_apply"])

    def test_emergency_without_a_confirmed_safe_point_waits(self):
        event = {
            "source_event_id": 50,
            "event_type": "new_ticket",
            "ticket_id": 90,
            "category": "emergency",
            "request_type_hd": "авария",
            "received_at": "2030-01-15T08:00:00+03:00",
        }
        snapshot = {
            "area_scope": {"tickets": [{"id": 1, "lifecycle_state": "in_progress"}]},
            "current_day_state": {
                "visits": [
                    {
                        "ticket_id": 1,
                        "worker_id": 7,
                        "sequence": 1,
                        "service_start_at": "2030-01-15T08:00:00+03:00",
                        "service_end_at": "2030-01-15T09:00:00+03:00",
                    }
                ]
            },
        }
        prepared = {
            "workers": [],
            "excluded_workers": [{"reason": {"code": "active_stage_not_completed"}}],
        }
        public = {
            "routes": [],
            "replan_diff": {"emergency_response": []},
            "unassigned": [],
        }

        result = build_ticket_event_result(event, snapshot, prepared, public)

        self.assertEqual(result["outcome"], "waiting_safe_point")
        self.assertFalse(result["can_apply"])
        self.assertEqual(result["preserved_current_stage"][0]["ticket_id"], 1)


if __name__ == "__main__":
    unittest.main()

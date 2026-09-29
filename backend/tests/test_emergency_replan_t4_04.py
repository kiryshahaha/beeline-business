"""Tests for T4-04: emergency replan policy, SLA response forecasts, and preemption."""

import unittest
from zoneinfo import ZoneInfo

from app.modules.planning.day_plans import (
    build_emergency_replan_summary,
    build_replan_state,
    diff_states,
)

MOSCOW = ZoneInfo("Europe/Moscow")


class EmergencyReplanTests(unittest.TestCase):
    def visit(self, ticket_id, worker_id, sequence, start="10:00:00", end="10:30:00"):
        return {
            "ticket_id": ticket_id,
            "worker_id": worker_id,
            "sequence": sequence,
            "arrival_at": f"2026-09-30T{start}+03:00",
            "service_start_at": f"2026-09-30T{start}+03:00",
            "service_end_at": f"2026-09-30T{end}+03:00",
        }

    def test_preempted_regular_tickets_are_detected(self):
        before = {
            "visits": [
                self.visit(1, 10, 1),
                self.visit(2, 10, 2),  # Regular ticket 2 was assigned
            ],
            "unassigned_ticket_ids": [],
        }
        # In after, ticket 2 was preempted by emergency ticket 99!
        after = {
            "visits": [
                self.visit(1, 10, 1),
                self.visit(99, 10, 2),
            ],
            "unassigned_ticket_ids": [2],
        }
        meta = {
            99: {
                "category": "emergency",
                "received_at": "2026-09-30T09:30:00+03:00",
            }
        }
        summary = build_emergency_replan_summary(before, after, tickets_metadata=meta)
        self.assertEqual(len(summary["preempted_tickets"]), 1)
        self.assertEqual(summary["preempted_tickets"][0]["ticket_id"], 2)
        self.assertEqual(summary["preempted_tickets"][0]["previous_worker_id"], 10)
        self.assertEqual(summary["preempted_tickets"][0]["reason"], "preempted_by_emergency")

    def test_emergency_sla_forecast_calculation(self):
        # Emergency 99 received at 09:15, start at 10:00 -> 45 minutes -> on_time (<= 60 min)
        # Emergency 98 received at 08:00, start at 09:30 -> 90 minutes -> acceptable (<= 120 min)
        # Emergency 97 received at 07:00, start at 10:00 -> 180 minutes -> violated (> 120 min)
        after = {
            "visits": [
                self.visit(99, 10, 1, start="10:00:00", end="10:30:00"),
                self.visit(98, 11, 1, start="09:30:00", end="10:00:00"),
                self.visit(97, 12, 1, start="10:00:00", end="10:30:00"),
            ],
            "unassigned_ticket_ids": [],
        }
        meta = {
            99: {
                "category": "emergency",
                "received_at": "2026-09-30T09:15:00+03:00",
                "response_deadline_at": "2026-09-30T10:15:00+03:00",
            },
            98: {
                "category": "emergency",
                "received_at": "2026-09-30T08:00:00+03:00",
                "response_deadline_at": "2026-09-30T10:00:00+03:00",
            },
            97: {
                "category": "emergency",
                "received_at": "2026-09-30T07:00:00+03:00",
                "response_deadline_at": "2026-09-30T09:00:00+03:00",
            },
        }
        summary = build_emergency_replan_summary(None, after, tickets_metadata=meta)
        forecasts = {f["ticket_id"]: f for f in summary["emergency_sla_forecasts"]}

        self.assertEqual(forecasts[99]["sla_status"], "on_time")
        self.assertEqual(forecasts[99]["response_minutes"], 45)

        self.assertEqual(forecasts[98]["sla_status"], "acceptable")
        self.assertEqual(forecasts[98]["response_minutes"], 90)

        self.assertEqual(forecasts[97]["sla_status"], "violated")
        self.assertEqual(forecasts[97]["response_minutes"], 180)

    def test_response_status_uses_each_ticket_deadline_and_reports_lateness(self):
        after = {
            "visits": [
                self.visit(60, 10, 1, start="10:01:00", end="10:31:00"),
                self.visit(120, 11, 1, start="09:30:00", end="10:00:00"),
                self.visit(59, 12, 1, start="10:00:00", end="10:30:00"),
                self.visit(121, 13, 1, start="10:00:00", end="10:30:00"),
            ],
            "unassigned_ticket_ids": [],
        }
        meta = {
            60: {
                "category": "emergency",
                "received_at": "2026-09-30T09:00:00+03:00",
                "response_deadline_at": "2026-09-30T10:00:00+03:00",
            },
            120: {
                "category": "emergency",
                "received_at": "2026-09-30T08:00:00+03:00",
                "response_deadline_at": "2026-09-30T10:00:00+03:00",
            },
            59: {
                "category": "emergency",
                "received_at": "2026-09-30T09:00:00+03:00",
                "response_deadline_at": "2026-09-30T10:00:00+03:00",
            },
            121: {
                "category": "emergency",
                "received_at": "2026-09-30T08:00:00+03:00",
                "response_deadline_at": "2026-09-30T10:00:00+03:00",
            },
        }

        forecasts = {
            item["ticket_id"]: item
            for item in build_emergency_replan_summary(None, after, tickets_metadata=meta)[
                "emergency_sla_forecasts"
            ]
        }

        self.assertEqual(forecasts[60]["target_minutes"], 60)
        self.assertFalse(forecasts[60]["response_deadline_met"])
        self.assertEqual(forecasts[60]["response_lateness_minutes"], 1)
        self.assertEqual(forecasts[60]["sla_status"], "violated")
        self.assertEqual(forecasts[120]["target_minutes"], 120)
        self.assertTrue(forecasts[120]["response_deadline_met"])
        self.assertEqual(forecasts[120]["response_lateness_minutes"], 0)
        self.assertEqual(forecasts[120]["sla_status"], "acceptable")
        self.assertTrue(forecasts[59]["response_deadline_met"])
        self.assertEqual(forecasts[59]["response_minutes"], 60)
        self.assertEqual(forecasts[59]["sla_status"], "on_time")
        self.assertTrue(forecasts[121]["response_deadline_met"])
        self.assertEqual(forecasts[121]["response_minutes"], 120)
        self.assertEqual(forecasts[121]["sla_status"], "acceptable")

    def test_diff_states_includes_emergency_summary(self):
        before = {
            "visits": [self.visit(1, 10, 1), self.visit(2, 10, 2)],
            "unassigned_ticket_ids": [],
            "metrics": {},
        }
        after = {
            "visits": [self.visit(1, 10, 1), self.visit(99, 10, 2, start="10:15:00")],
            "unassigned_ticket_ids": [2],
            "metrics": {},
        }
        meta = {
            99: {
                "category": "emergency",
                "received_at": "2026-09-30T09:30:00+03:00",
            }
        }
        diff = diff_states(before, after, tickets_metadata=meta)
        self.assertIn("preempted_tickets", diff)
        self.assertIn("emergency_sla_forecasts", diff)
        self.assertEqual(len(diff["preempted_tickets"]), 1)
        self.assertEqual(diff["preempted_tickets"][0]["ticket_id"], 2)
        self.assertEqual(len(diff["emergency_sla_forecasts"]), 1)
        self.assertEqual(diff["emergency_sla_forecasts"][0]["ticket_id"], 99)

    def test_in_flight_visit_is_preserved_during_replan_state_building(self):
        previous = {
            "visits": [
                self.visit(1, 10, 1, start="09:00:00", end="09:45:00"),  # in_progress
                self.visit(2, 10, 2, start="10:00:00", end="10:30:00"),  # future
            ]
        }
        # Solver proposed new route with emergency 99 and future 2
        public = {
            "routes": [
                {
                    "worker_id": 10,
                    "stops": [
                        {
                            "ticket_id": 99,
                            "sequence": 1,
                            "arrival_at": "2026-09-30T10:00:00+03:00",
                            "service_start_at": "2026-09-30T10:00:00+03:00",
                            "service_end_at": "2026-09-30T10:30:00+03:00",
                        }
                    ],
                }
            ],
            "unassigned": [{"ticket_id": 2}],
        }
        lifecycle = {1: "in_progress", 2: "assigned", 99: "waiting_assignment"}
        replan_state = build_replan_state(public, previous, lifecycle)
        visits = replan_state["visits"]

        # Visit 1 must be preserved with original times and sequence
        v1 = next(v for v in visits if v["ticket_id"] == 1)
        self.assertEqual(v1["service_start_at"], "2026-09-30T09:00:00+03:00")
        self.assertEqual(v1["sequence"], 1)

        # Emergency visit 99 must be offset after in_progress visit (sequence 2)
        v99 = next(v for v in visits if v["ticket_id"] == 99)
        self.assertEqual(v99["sequence"], 2)


if __name__ == "__main__":
    unittest.main()

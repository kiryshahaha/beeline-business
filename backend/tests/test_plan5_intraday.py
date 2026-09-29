"""Plan 5 intraday rules: current stage, waiting emergency, notices, arrival and import."""

import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import text

from app.modules.data_exchange.formats import ExchangeError, parse_file, serialize
from app.modules.data_exchange.service import import_data
from app.modules.planning import service
from app.modules.planning.day_plans import build_replan_state
from app.modules.planning.eligibility import worker_replan_anchor
from app.modules.planning.slot_finder import find_regular_ticket_slot
from app.modules.tickets import service as tickets
from app.modules.tickets.schemas import TicketCreate
from generate_acceptance_dataset import build_dataset
from tests.support import DatabaseTestCase


def moscow(clock: str) -> datetime:
    return datetime.fromisoformat(f"2030-01-15T{clock}:00+03:00")


class CurrentStageTests(unittest.TestCase):
    day_state = {"current_ticket_id": 1, "current_destination_id": 5, "last_location_id": 4}

    def ticket(self, state, **fields):
        return {
            "lifecycle_state": state,
            "location_id": 5,
            "estimated_duration_minutes": 30,
            "planned_end_at": moscow("09:30"),
            **fields,
        }

    def test_emergency_waits_for_the_completion_event(self):
        anchor = worker_replan_anchor(
            self.day_state,
            self.ticket("in_progress", actual_started_at=moscow("09:05")),
            moscow("09:12"),
            default_location_id=1,
        )

        self.assertEqual(anchor["reason"], "active_stage_not_completed")

    def test_ordinary_insertion_starts_where_the_started_service_ends(self):
        anchor = worker_replan_anchor(
            self.day_state,
            self.ticket("in_progress", actual_started_at=moscow("09:05")),
            moscow("09:12"),
            default_location_id=1,
            estimate_active_stage=True,
        )

        self.assertIsNone(anchor["reason"])
        self.assertEqual(anchor["location_id"], 5)
        self.assertEqual(anchor["available_at"], moscow("09:35"))

    def test_travelling_engineer_has_the_whole_service_ahead(self):
        anchor = worker_replan_anchor(
            self.day_state,
            self.ticket("en_route"),
            moscow("09:12"),
            default_location_id=1,
            estimate_active_stage=True,
        )

        self.assertEqual(anchor["available_at"], moscow("09:42"))

    def test_published_end_stays_a_lower_bound(self):
        anchor = worker_replan_anchor(
            self.day_state,
            self.ticket("in_progress", actual_started_at=moscow("08:40")),
            moscow("09:00"),
            default_location_id=1,
            estimate_active_stage=True,
        )

        self.assertEqual(anchor["available_at"], moscow("09:30"))

    def test_new_stop_waits_for_the_end_of_the_current_stage(self):
        result = find_regular_ticket_slot(
            ticket={
                "id": 9,
                "location_id": 6,
                "estimated_duration_minutes": 30,
                "visit_window_start": moscow("09:12"),
                "visit_window_end": moscow("12:30"),
            },
            candidate_workers=[
                {
                    "user_id": 7,
                    "skills": set(),
                    "transport_type": "car",
                    "shift_start_at": moscow("08:00"),
                    "shift_end_at": moscow("20:00"),
                    "office_location_id": 1,
                    "available_at": moscow("09:42"),
                }
            ],
            baseline_state={
                "visits": [
                    {
                        "ticket_id": 1,
                        "worker_id": 7,
                        "sequence": 1,
                        "location_id": 5,
                        "service_start_at": "2030-01-15T09:00:00+03:00",
                        "service_end_at": "2030-01-15T09:30:00+03:00",
                    }
                ]
            },
            lifecycle_by_ticket={1: "en_route"},
            travel_time_fn=lambda source, target, _profile: 0 if source == target else 4,
            office_location_id=1,
            now=moscow("09:12"),
        )

        self.assertEqual(result.status, "slot_found")
        self.assertEqual(result.selected.insertion_sequence, 2)
        self.assertEqual(result.selected.estimated_arrival_at, moscow("09:46"))


class WaitingEmergencyTests(unittest.TestCase):
    event = {
        "source_event_id": 50,
        "event_type": "new_ticket",
        "ticket_id": 90,
        "category": "emergency",
        "request_type_hd": "Авария",
        "received_at": "2030-01-15T09:20:00+03:00",
    }
    snapshot = {"area_scope": {"tickets": []}, "current_day_state": {"visits": []}}
    public = {"routes": [], "replan_diff": {"emergency_response": []}, "unassigned": []}
    prepared = {
        # A free engineer without the skill stays; the qualified one is on his current stage.
        "workers": [{"user_id": 8}],
        "excluded_workers": [{"worker_id": 7, "reason": {"code": "active_stage_not_completed"}}],
    }

    def result(self, after_stage):
        with patch.object(service, "prepare", return_value=after_stage):
            return service.build_ticket_event_result(
                self.event, self.snapshot, self.prepared, self.public, now=moscow("09:22")
            )

    def test_emergency_waits_for_the_qualified_engineer_on_his_stage(self):
        outcome = self.result(
            {"workers": [{"user_id": 7}, {"user_id": 8}], "tickets": [{"id": 90, "allowed": [0]}]}
        )

        self.assertEqual(outcome["outcome"], "waiting_safe_point")
        self.assertFalse(outcome["can_apply"])

    def test_nobody_qualified_even_after_the_stage_is_unassigned(self):
        outcome = self.result({"workers": [{"user_id": 7}, {"user_id": 8}], "tickets": []})

        self.assertEqual(outcome["outcome"], "emergency_unassigned")


class RescheduleNoticeTests(unittest.TestCase):
    def test_notice_names_the_revision_and_its_reason(self):
        revision = SimpleNamespace(
            diff={
                "changed": [
                    {
                        "ticket_id": 5,
                        "changes": {
                            "service_start_at": {
                                "from": "2030-01-15T11:00:00+03:00",
                                "to": "2030-01-15T11:40:00+03:00",
                            }
                        },
                    }
                ]
            },
            reason="emergency_replan",
            service_area_id=3,
            route_date=date(2030, 1, 15),
            revision=4,
        )
        session = SimpleNamespace(
            get=lambda _model, _id: SimpleNamespace(id=5, assigned_worker_id=9)
        )
        with patch.object(service.ticket_repository, "add_notification_events") as add:
            service._notify_rescheduled_tickets(session, revision)

        data = add.call_args.kwargs["data"]
        self.assertEqual(add.call_args.args[1], [9])
        self.assertEqual(
            (data["service_area_id"], data["route_date"], data["day_revision"]),
            (3, "2030-01-15", 4),
        )
        self.assertEqual(data["reason_text"], "Маршрут пересчитан из-за аварийной заявки")


class ReplanStateTests(unittest.TestCase):
    def test_work_in_motion_stays_on_its_route_not_among_the_unassigned(self):
        started = {
            "ticket_id": 1,
            "worker_id": 7,
            "route_id": 3,
            "sequence": 1,
            "arrival_at": "2030-01-15T09:00:00+03:00",
            "service_start_at": "2030-01-15T09:00:00+03:00",
            "service_end_at": "2030-01-15T09:30:00+03:00",
        }
        # The solve saw the started ticket as not planned and left it unassigned.
        public = {"routes": [], "unassigned": [{"ticket_id": 1}, {"ticket_id": 2}]}

        state = build_replan_state(public, {"visits": [started]}, {1: "in_progress", 2: "assigned"})

        self.assertEqual([visit["ticket_id"] for visit in state["visits"]], [1])
        self.assertEqual(state["unassigned_ticket_ids"], [2])
        self.assertEqual(state["metrics"]["unassigned_tickets"], 1)


class DroppedTicketNoticeTests(unittest.TestCase):
    def test_engineer_learns_which_ticket_the_replan_took_off_and_why(self):
        revision = SimpleNamespace(service_area_id=3, route_date=date(2030, 1, 15), revision=5)
        with patch.object(service.ticket_repository, "add_notification_events") as add:
            service._notify_dropped_tickets(
                None, [(40, 9, "Заявка"), (41, None, "Без исполнителя")], {40: "late"}, revision
            )

        add.assert_called_once()
        self.assertEqual(add.call_args.args[1], [9])
        self.assertEqual(add.call_args.kwargs["ticket_id"], 40)
        self.assertEqual(add.call_args.kwargs["kind"].value, "ticket_unassigned")
        self.assertEqual(
            {
                key: add.call_args.kwargs["data"][key]
                for key in ("unassigned_reason", "day_revision")
            },
            {"unassigned_reason": "late", "day_revision": 5},
        )


class ImportedAssignmentTests(DatabaseTestCase):
    """An exchange package cannot bring an assignment that solve and manual paths refuse."""

    def package(self, **ticket_fields):
        tables, _ = build_dataset()
        tables["tickets"][0].update(
            lifecycle_state="assigned", assigned_worker_id=9, **ticket_fields
        )
        return parse_file(serialize(tables, "csv"), "acceptance.zip")

    def assert_refused(self, package, code):
        with patch("app.modules.data_exchange.service.hash_password", return_value="test-only"):
            with self.assertRaises(ExchangeError) as raised:
                import_data(self.session, package)
        detail = raised.exception.detail
        self.assertEqual(detail["code"], "assignment_rejected")
        self.assertEqual(
            [(item["ticket_id"], item["reason"]["code"]) for item in detail["violations"]],
            [(1, code)],
        )
        self.session.rollback()
        self.assertEqual(self.session.execute(text("SELECT count(*) FROM tickets")).scalar(), 0)

    def test_required_transport_is_checked_on_import(self):
        # Ticket 1 is assigned to worker 9, who drives a car.
        self.assert_refused(
            self.package(required_transport_type="walking"), "required_transport_mismatch"
        )

    def test_shift_is_checked_on_import(self):
        # Worker 9 works 09:00–21:00; the visit starts after the shift.
        self.assert_refused(
            self.package(
                visit_window_start=moscow("21:30"),
                visit_window_end=moscow("22:30"),
                planned_start_at=moscow("21:30"),
                planned_end_at=moscow("22:00"),
            ),
            "outside_shift_horizon",
        )


class RepeatedArrivalTests(DatabaseTestCase):
    """A repeated arrival with the client's key is one ticket and one NEW_TICKET event."""

    def setUp(self):
        super().setUp()
        tables, _ = build_dataset()
        with patch("app.modules.data_exchange.service.hash_password", return_value="test-only"):
            receipt = import_data(self.session, parse_file(serialize(tables, "csv"), "a.zip"))
        location = receipt["id_map"]["locations"]["1"]
        self.data = TicketCreate(
            location_id=location,
            title="Нет связи",
            work_type_id=receipt["id_map"]["work_types"]["1"],
            request_type_hd="Ремонт",
            received_at=moscow("09:00"),
            visit_window_start=moscow("10:00"),
            visit_window_end=moscow("12:00"),
            estimated_duration_minutes=30,
        )

    def create(self, data, key="ticket-create:client:k1"):
        return tickets.create_ticket(self.session, data, idempotency_key=key, replay=True)

    def count(self, sql):
        return self.session.execute(text(sql)).scalar_one()

    def test_repeat_returns_the_created_ticket(self):
        first = self.create(self.data)
        second = self.create(self.data)

        self.assertEqual(first.id, second.id)
        self.assertEqual(self.count("SELECT count(*) FROM tickets WHERE title='Нет связи'"), 1)
        self.assertEqual(
            self.count(
                f"SELECT count(*) FROM work_events WHERE ticket_id={first.id} "
                "AND event_type='new_ticket'"
            ),
            1,
        )

    def test_same_key_with_another_body_is_a_conflict(self):
        self.create(self.data)

        with self.assertRaises(tickets.TicketIdempotencyConflictError):
            self.create(self.data.model_copy(update={"title": "Другая заявка"}))
        self.session.rollback()
        self.assertEqual(self.count("SELECT count(*) FROM tickets WHERE title='Другая заявка'"), 0)


if __name__ == "__main__":
    unittest.main()

"""Pure schema checks for the execution lifecycle foundation."""

import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from app.modules.appliances.execution_models import EquipmentMovement
from app.modules.brigades.models import Brigade
from app.modules.execution.enums import TicketLifecycleState, WorkEventType
from app.modules.execution.models import Division, WorkEvent
from app.modules.execution.schemas import (
    ExecutionCommand,
    RedirectCommand,
    WindowChangeCommand,
    WorkerUnavailableCommand,
)
from app.modules.tickets.enums import TicketStatus
from app.modules.tickets.models import Ticket


class ExecutionSchemaTests(unittest.TestCase):
    def test_ticket_lifecycle_state_has_the_dispatch_lifecycle(self):
        self.assertEqual(
            [state.value for state in TicketLifecycleState],
            [
                "waiting_assignment",
                "assigned",
                "dispatched",
                "en_route",
                "in_progress",
                "completed",
                "cancelled",
            ],
        )

    def test_legacy_ticket_status_values_remain_available(self):
        self.assertEqual(
            [status.value for status in TicketStatus],
            ["planned", "in_progress", "completed", "wont_fix"],
        )

    def test_work_event_types_cover_ticket_and_day_changes(self):
        self.assertEqual(
            [event.value for event in WorkEventType],
            [
                "new_ticket",
                "assign",
                "dispatch",
                "start_route",
                "start",
                "complete",
                "cancel_ticket",
                "reopen",
                "progress_delay",
                "worker_unavailable",
                "window_change",
                "redirect",
            ],
        )

    def test_ticket_snapshot_has_revision_and_execution_facts(self):
        for column in (
            "lifecycle_state",
            "revision",
            "execution_cycle",
            "actual_started_at",
            "actual_completed_at",
            "cancel_reason",
            "last_event_id",
        ):
            self.assertIn(column, Ticket.__table__.c)

    def test_division_is_unique_per_district_and_brigade_references_it(self):
        self.assertIn("district_id", Division.__table__.c)
        self.assertIn("division_id", Brigade.__table__.c)
        self.assertTrue(
            any(
                index.unique and "district_id" in index.columns
                for index in Division.__table__.indexes
            )
        )

    def test_work_event_has_revision_and_idempotency_columns(self):
        for column in (
            "event_type",
            "occurred_at",
            "recorded_at",
            "before_revision",
            "after_revision",
            "idempotency_key",
        ):
            self.assertIn(column, WorkEvent.__table__.c)

    def test_equipment_movement_is_scoped_to_execution_cycle(self):
        for column in (
            "ticket_id",
            "execution_cycle",
            "appliance_id",
            "event_id",
            "movement",
            "quantity",
        ):
            self.assertIn(column, EquipmentMovement.__table__.c)
        self.assertTrue(
            any(
                index.unique and "execution_cycle" in index.columns and "movement" in index.columns
                for index in EquipmentMovement.__table__.indexes
            )
        )

    def test_execution_commands_require_timezone_and_reject_unknown_fields(self):
        with self.assertRaises(ValidationError):
            ExecutionCommand(expected_revision=1, occurred_at=datetime(2030, 1, 15, 10))
        with self.assertRaises(ValidationError):
            ExecutionCommand.model_validate({"expected_revision": 1, "unexpected": "field"})

    def test_window_change_and_redirect_require_operator_reason(self):
        base = {
            "expected_revision": 1,
            "occurred_at": datetime(2030, 1, 15, 10, tzinfo=UTC),
        }
        with self.assertRaises(ValidationError):
            WindowChangeCommand(
                **base,
                new_window_start=datetime(2030, 1, 15, 12, tzinfo=UTC),
                new_window_end=datetime(2030, 1, 15, 11, tzinfo=UTC),
            )
        with self.assertRaises(ValidationError):
            RedirectCommand(
                worker_id=1,
                current_ticket_id=1,
                new_destination_id=2,
                expected_day_revision=1,
                reason=" ",
            )

    def test_worker_unavailable_command_keeps_district_and_route_date_typed(self):
        command = WorkerUnavailableCommand(
            expected_revision=1,
            district_id=2,
            route_date="2030-01-15",
        )
        self.assertEqual(command.route_date.isoformat(), "2030-01-15")

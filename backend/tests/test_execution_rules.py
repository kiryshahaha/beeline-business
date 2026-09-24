"""Pure lifecycle rules for observer execution commands."""

import unittest

from app.modules.execution.enums import TicketLifecycleState, WorkEventType
from app.modules.execution.service import (
    IllegalTransition,
    legacy_status_for_state,
    next_state_for_event,
)
from app.modules.tickets.enums import TicketStatus


class ExecutionRuleTests(unittest.TestCase):
    def test_forward_lifecycle_events(self):
        state = TicketLifecycleState.WAITING_ASSIGNMENT
        for event, expected in (
            (WorkEventType.ASSIGN, TicketLifecycleState.ASSIGNED),
            (WorkEventType.DISPATCH, TicketLifecycleState.DISPATCHED),
            (WorkEventType.START_ROUTE, TicketLifecycleState.EN_ROUTE),
            (WorkEventType.START, TicketLifecycleState.IN_PROGRESS),
            (WorkEventType.COMPLETE, TicketLifecycleState.COMPLETED),
        ):
            state = next_state_for_event(state, event)
            self.assertEqual(state, expected)

    def test_cancellation_and_reopen_rules_are_explicit(self):
        self.assertEqual(
            next_state_for_event(TicketLifecycleState.EN_ROUTE, WorkEventType.CANCEL),
            TicketLifecycleState.CANCELLED,
        )
        with self.assertRaises(IllegalTransition):
            next_state_for_event(TicketLifecycleState.IN_PROGRESS, WorkEventType.CANCEL)
        with self.assertRaises(IllegalTransition):
            next_state_for_event(TicketLifecycleState.COMPLETED, WorkEventType.COMPLETE)

    def test_delay_keeps_active_state_and_cannot_reopen_terminal_work(self):
        self.assertEqual(
            next_state_for_event(TicketLifecycleState.IN_PROGRESS, WorkEventType.PROGRESS_DELAY),
            TicketLifecycleState.IN_PROGRESS,
        )
        for state in (TicketLifecycleState.COMPLETED, TicketLifecycleState.CANCELLED):
            with self.subTest(state=state), self.assertRaises(IllegalTransition):
                next_state_for_event(state, WorkEventType.PROGRESS_DELAY)

    def test_legacy_status_is_derived_from_canonical_state(self):
        self.assertEqual(
            legacy_status_for_state(TicketLifecycleState.ASSIGNED), TicketStatus.PLANNED
        )
        self.assertEqual(
            legacy_status_for_state(TicketLifecycleState.CANCELLED), TicketStatus.WONT_FIX
        )

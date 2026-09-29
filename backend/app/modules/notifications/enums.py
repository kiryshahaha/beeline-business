"""Supported durable notification kinds."""

from enum import StrEnum


class NotificationKind(StrEnum):
    TICKET_ASSIGNED = "ticket_assigned"
    TICKET_STATUS_CHANGED = "ticket_status_changed"
    TICKET_UNASSIGNED = "ticket_unassigned"
    TICKET_RESCHEDULED = "ticket_rescheduled"
    TICKET_WINDOW_CHANGED = "ticket_window_changed"
    TICKET_COMPLETION_CONFIRMED = "ticket_completion_confirmed"
    TICKET_COMPLETION_REJECTED = "ticket_completion_rejected"
    TICKET_COMPLETION_REQUESTED = "ticket_completion_requested"
    TICKET_DELAY_REPORTED = "ticket_delay_reported"
    TICKET_PROBLEM_REPORTED = "ticket_problem_reported"

"""Canonical lifecycle and immutable execution event names."""

from enum import StrEnum


class TicketLifecycleState(StrEnum):
    WAITING_ASSIGNMENT = "waiting_assignment"
    ASSIGNED = "assigned"
    DISPATCHED = "dispatched"
    EN_ROUTE = "en_route"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkEventType(StrEnum):
    NEW_TICKET = "new_ticket"
    ASSIGN = "assign"
    DISPATCH = "dispatch"
    START_ROUTE = "start_route"
    START = "start"
    COMPLETE = "complete"
    CANCEL_TICKET = "cancel_ticket"
    CANCEL = CANCEL_TICKET
    REOPEN = "reopen"
    PROGRESS_DELAY = "progress_delay"
    WORKER_UNAVAILABLE = "worker_unavailable"
    WINDOW_CHANGE = "window_change"
    REDIRECT = "redirect"

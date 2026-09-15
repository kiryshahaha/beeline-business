"""Supported durable notification kinds."""

from enum import StrEnum


class NotificationKind(StrEnum):
    TICKET_ASSIGNED = "ticket_assigned"
    TICKET_STATUS_CHANGED = "ticket_status_changed"

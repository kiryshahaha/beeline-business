"""The four ticket statuses agreed for the first version."""

from enum import StrEnum


class TicketStatus(StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    WONT_FIX = "wont_fix"


class TicketCategory(StrEnum):
    EMERGENCY = "emergency"
    CONNECTION = "connection"
    REPAIR = "repair"
    ADDITIONAL = "additional"

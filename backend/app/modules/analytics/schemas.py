"""Schemas for analytics query parameters and responses."""

from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.modules.tickets.enums import TicketStatus
from app.modules.users.enums import UserRole


class AnalyticsPeriod(StrEnum):
    TODAY = "today"
    WEEK = "week"
    MONTH = "month"


class TicketsSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open: int
    assigned: int
    in_progress: int
    completed: int


class BrigadeWorkloadItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brigade_name: str
    active_tickets: int
    completed_today: int


class ActivityKind(StrEnum):
    TICKET_CREATED = "ticket_created"
    TICKET_ASSIGNED = "ticket_assigned"
    TICKET_STATUS_CHANGED = "ticket_status_changed"
    COMMENT_ADDED = "comment_added"
    COMMENT_EDITED = "comment_edited"


class ActivityPerson(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    full_name: str
    role: UserRole


class ActivityTicket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    title: str
    status: TicketStatus = Field(
        description="Текущий статус заявки, а не статус на момент события."
    )


class ActivityDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previous_status: TicketStatus | None = None
    status: TicketStatus | None = Field(default=None, description="Статус, назначенный событием.")
    worker: ActivityPerson | None = Field(default=None, description="Назначенный исполнитель.")
    comment_id: int | None = None
    comment_excerpt: str | None = Field(
        default=None, description="Начало комментария; длинный текст обрезается многоточием."
    )


class ActivityItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ActivityKind
    occurred_at: AwareDatetime
    ticket: ActivityTicket
    actor: ActivityPerson | None = Field(
        default=None, description="Кто выполнил действие; null, если система его не записала."
    )
    details: ActivityDetails

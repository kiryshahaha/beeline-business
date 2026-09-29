"""Chat request/response contracts.

The backend passes its own API objects in `context` without reshaping them: `day` is the
`GET /me/day` response, `ticket` is `TicketRead` with `comments`, `appliances` and
`changes` attached. Context models ignore fields the assistant does not use.
"""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Role = Literal["worker", "foreman", "observer"]
TicketState = Literal[
    "waiting_assignment",
    "assigned",
    "dispatched",
    "en_route",
    "in_progress",
    "completed",
    "cancelled",
]
MessageText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]


class ContextModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: MessageText


class LocationContext(ContextModel):
    address: str | None = None
    street: str | None = None
    entrance_number: str | None = None
    floor: int | None = None
    apartment: str | None = None


class FieldChange(ContextModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    previous: Any = Field(default=None, alias="from")
    current: Any = Field(default=None, alias="to")


class ActorContext(ContextModel):
    name: str | None = None
    role: str | None = None


class TicketChange(ContextModel):
    at: datetime
    kind: str
    source: str | None = None
    actor: ActorContext | None = None
    fields: dict[str, FieldChange] = Field(default_factory=dict)
    reason_code: str | None = None
    reason_text: str | None = None
    related_ticket_id: int | None = None


class CommentAuthor(ContextModel):
    name: str | None = None
    surname: str | None = None
    role: str | None = None


class CommentContext(ContextModel):
    author: CommentAuthor | None = None
    text: str
    created_at: datetime | None = None


class ApplianceContext(ContextModel):
    appliance_name: str
    quantity: int = 1
    unit: str | None = None


class CompletionReview(ContextModel):
    state: Literal["pending", "confirmed", "rejected"]
    requested_at: datetime | None = None
    decision_comment: str | None = None


class TicketContext(ContextModel):
    """`TicketRead`; day fields come from `/me/day`, detail fields from the open card."""

    id: int
    title: str
    description: str | None = None
    category: str | None = None
    work_type: str | None = None
    priority: int | None = None
    state: TicketState | None = None
    visit_window_start: datetime | None = None
    visit_window_end: datetime | None = None
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None
    estimated_duration_minutes: int | None = None
    sla_deadline_at: datetime | None = None
    cancel_reason: str | None = None
    location: LocationContext | None = None

    sequence: int | None = None
    planned_arrival_at: datetime | None = None
    required_appliances: list[ApplianceContext] = Field(default_factory=list)
    comments_count: int | None = None
    completion_review: CompletionReview | None = None
    last_change: TicketChange | None = None

    comments: list[CommentContext] = Field(default_factory=list, max_length=20)
    appliances: list[ApplianceContext] = Field(default_factory=list)
    changes: list[TicketChange] = Field(default_factory=list, max_length=50)


class ShiftContext(ContextModel):
    is_working_day: bool = True
    start: datetime | None = None
    end: datetime | None = None


class DayStateContext(ContextModel):
    available: bool = True
    unavailable_until: datetime | None = None
    reason: str | None = None
    current_ticket_id: int | None = None
    en_route_started_at: datetime | None = None
    expected_available_at: datetime | None = None


class NamedContext(ContextModel):
    name: str
    address: str | None = None


class WorkerContext(ContextModel):
    id: int | None = None
    name: str | None = None
    surname: str | None = None
    skills: list[str] = Field(default_factory=list)
    brigade: NamedContext | None = None
    service_area: NamedContext | None = None
    office: NamedContext | None = None


class DaySummary(ContextModel):
    total: int = 0
    completed: int = 0
    awaiting_confirmation: int = 0
    in_progress: int = 0
    remaining: int = 0
    cancelled: int = 0


class RemovedTicket(ContextModel):
    ticket_id: int
    title: str
    at: datetime | None = None
    reason_code: str | None = None
    reason_text: str | None = None


class DayContext(ContextModel):
    """`GET /api/v1/me/day`."""

    date: date
    worker: WorkerContext | None = None
    shift: ShiftContext | None = None
    day_state: DayStateContext | None = None
    summary: DaySummary | None = None
    current_ticket_id: int | None = None
    next_ticket_id: int | None = None
    tickets: list[TicketContext] = Field(default_factory=list, max_length=60)
    removed_tickets: list[RemovedTicket] = Field(default_factory=list)


class ChatContext(ContextModel):
    day: DayContext | None = None
    tomorrow_shift: ShiftContext | None = None
    ticket: TicketContext | None = Field(
        default=None, description="Заявка, открытая у пользователя в момент вопроса."
    )


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role
    message: MessageText
    history: list[ChatMessage] = Field(default_factory=list, max_length=10)
    context: ChatContext | None = None


class Source(BaseModel):
    title: str
    section: str


class ChatResponse(BaseModel):
    answer: str
    source_type: Literal["facts", "knowledge", "model"] = Field(
        description="facts — из данных системы, knowledge — модель по базе знаний, "
        "model — модель по контексту без справки."
    )
    sources: list[Source]
    model: str | None = Field(default=None, description="null, если ответ собран из данных.")
    intent: str | None = Field(default=None, description="Распознанный вопрос о данных.")

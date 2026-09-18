"""Chat request/response contracts. The backend fills `context` from its own data."""

from datetime import datetime, time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Role = Literal["worker", "foreman", "observer"]
TicketStatus = Literal["planned", "in_progress", "completed", "wont_fix"]
MessageText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: MessageText


class CommentContext(BaseModel):
    author: str = Field(description="Имя автора или «Система» для комментариев планировщика.")
    text: str
    created_at: datetime | None = None


class TicketContext(BaseModel):
    id: int
    title: str
    work_type: str
    status: TicketStatus
    description: str | None = None
    address: str | None = None
    visit_window_start: datetime | None = None
    visit_window_end: datetime | None = None
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None
    estimated_duration_minutes: int | None = None
    assignees: list[str] = Field(default_factory=list)
    comments: list[CommentContext] = Field(default_factory=list, max_length=20)


class UserContext(BaseModel):
    name: str | None = None
    workshift_start: time | None = None
    workshift_end: time | None = None
    skills: list[str] = Field(default_factory=list)
    brigade: str | None = None


class ChatContext(BaseModel):
    user: UserContext | None = None
    ticket: TicketContext | None = Field(
        default=None, description="Заявка, открытая у пользователя в момент вопроса."
    )
    tickets: list[TicketContext] = Field(
        default_factory=list,
        max_length=30,
        description="Заявки на день: свои для исполнителя, бригады для начальника.",
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
    sources: list[Source]
    model: str

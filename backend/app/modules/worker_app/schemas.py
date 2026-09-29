from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints


class AssistantMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class AssistantChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    history: list[AssistantMessage] = Field(default_factory=list, max_length=10)
    ticket_id: int | None = Field(default=None, ge=1)


class TicketProblemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "client_absent", "no_access", "client_refused", "no_equipment", "need_help", "other"
    ]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    expected_available_at: AwareDatetime | None = None
    expected_revision: int = Field(ge=1)


class CompletionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=2000)

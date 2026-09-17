"""Request and response contracts for ticket comments."""

from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints, field_validator

from app.modules.users.enums import UserRole


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[
        str,
        StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=4000),
    ]

    @field_validator("text")
    @classmethod
    def reject_null_character(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Комментарий не может содержать нулевой символ")
        return value


class CommentUpdate(CommentCreate):
    """Replace comment text using the same validation as creation."""


class CommentAuthorRead(BaseModel):
    id: int
    name: str
    surname: str
    lastname: str | None
    username: str
    role: UserRole


class CommentRead(BaseModel):
    id: int
    ticket_id: int
    author: CommentAuthorRead
    text: str
    created_at: AwareDatetime
    updated_at: AwareDatetime

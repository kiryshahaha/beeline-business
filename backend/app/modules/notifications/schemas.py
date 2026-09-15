"""HTTP and WebSocket contracts for user notifications."""

from typing import Annotated, Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints, field_validator

from app.modules.notifications.enums import NotificationKind

FirebaseToken = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=4096),
]


class PushSubscriptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: FirebaseToken

    @field_validator("token")
    @classmethod
    def reject_null_character(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Firebase-токен не может содержать нулевой символ")
        return value


class PushSubscriptionDelete(PushSubscriptionCreate):
    pass


class PushSubscriptionRead(BaseModel):
    id: int
    user_id: int
    token: str
    created_at: AwareDatetime
    updated_at: AwareDatetime


class NotificationRead(BaseModel):
    id: int
    recipient_id: int
    ticket_id: int
    kind: NotificationKind
    data: dict[str, Any]
    created_at: AwareDatetime

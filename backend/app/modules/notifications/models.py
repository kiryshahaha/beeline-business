"""Database models for browser subscriptions and durable events."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin
from app.modules.notifications.enums import NotificationKind


class PushSubscription(IntegerIdMixin, Base):
    __tablename__ = "push_subscriptions"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("token = btrim(token) AND token <> ''", name="token_not_blank"),
        CheckConstraint("char_length(token) <= 4096", name="token_length"),
    )


class NotificationEvent(IntegerIdMixin, Base):
    __tablename__ = "notification_events"

    recipient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    kind: Mapped[NotificationKind] = mapped_column(
        SqlEnum(
            NotificationKind,
            values_callable=lambda kinds: [kind.value for kind in kinds],
            native_enum=False,
            create_constraint=False,
            length=40,
            name="notification_kind",
        )
    )
    data: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    websocket_delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Nobody was connected when the event was offered to live sockets; the recipient
    # gets it from history on reconnect. Exactly one of the two WebSocket marks is set.
    websocket_missed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    push_delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("kind IN ('ticket_assigned', 'ticket_status_changed')", name="kind_valid"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint(
            "websocket_delivered_at IS NULL OR websocket_missed_at IS NULL",
            name="websocket_outcome_single",
        ),
        Index("ix_notification_events_pending_push", push_delivered_at, next_attempt_at, "id"),
    )

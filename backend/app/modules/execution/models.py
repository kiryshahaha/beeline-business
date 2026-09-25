"""Persistent execution facts and service-area ownership."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin
from app.modules.execution.enums import WorkEventType


class Division(IntegerIdMixin, Base):
    __tablename__ = "divisions"

    service_area_id: Mapped[int] = mapped_column(
        ForeignKey("service_areas.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("uq_divisions_service_area_id", "service_area_id", unique=True),)


class WorkEvent(IntegerIdMixin, Base):
    __tablename__ = "work_events"

    event_type: Mapped[WorkEventType] = mapped_column(
        Enum(
            WorkEventType,
            values_callable=lambda event_types: [event_type.value for event_type in event_types],
            native_enum=False,
            create_constraint=True,
            name="work_event_type",
        ),
        nullable=False,
    )
    ticket_id: Mapped[int | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True, index=True
    )
    worker_id: Mapped[int | None] = mapped_column(
        ForeignKey("workers.user_id", ondelete="RESTRICT"), nullable=True, index=True
    )
    service_area_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_areas.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    route_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    before_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    after_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("uq_work_events_idempotency_key", "idempotency_key", unique=True),
        Index(
            "ix_work_events_worker_day",
            "worker_id",
            "service_area_id",
            "route_date",
            "occurred_at",
        ),
    )

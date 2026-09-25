"""Current materialized state for one worker's service-area day."""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin


class WorkerDayState(IntegerIdMixin, Base):
    __tablename__ = "worker_day_states"

    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.user_id", ondelete="CASCADE"), nullable=False
    )
    service_area_id: Mapped[int] = mapped_column(
        ForeignKey("service_areas.id", ondelete="RESTRICT"), nullable=False
    )
    route_date: Mapped[date] = mapped_column(Date, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    available: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    unavailable_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unavailable_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT")
    )
    current_ticket_id: Mapped[int | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="RESTRICT")
    )
    current_destination_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT")
    )
    en_route_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index(
            "uq_worker_day_states_worker_service_area_date",
            "worker_id",
            "service_area_id",
            "route_date",
            unique=True,
        ),
        CheckConstraint("revision > 0", name="revision_positive"),
    )

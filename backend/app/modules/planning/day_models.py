"""Published revisions of a district's route day."""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin


class DayPlanRevision(IntegerIdMixin, Base):
    __tablename__ = "day_plan_revisions"

    district_id: Mapped[int] = mapped_column(
        ForeignKey("districts.id", ondelete="RESTRICT"), nullable=False
    )
    route_date: Mapped[date] = mapped_column(Date, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("work_events.id", ondelete="RESTRICT"))
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    diff: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index(
            "uq_day_plan_revisions_current",
            "district_id",
            "route_date",
            unique=True,
            postgresql_where=(is_current.is_(True)),
        ),
        Index("ix_day_plan_revisions_day", "district_id", "route_date", "revision"),
    )

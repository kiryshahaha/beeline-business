"""Published revisions of a service area's route day.

Identity is `(service_area_id, route_date)`: one area-day has exactly one current
revision. The preview UUID stays a separate concept, and `routes.route_number`
counts a worker's routes within a day.
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin

REVISION_REASONS = ("plan_applied", "worker_redirected", "manual_edit", "event_replan")


class DayPlanRevision(IntegerIdMixin, Base):
    __tablename__ = "day_plan_revisions"

    service_area_id: Mapped[int] = mapped_column(
        ForeignKey("service_areas.id", ondelete="RESTRICT"), nullable=False
    )
    route_date: Mapped[date] = mapped_column(Date, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_revision: Mapped[int | None] = mapped_column(Integer)
    plan_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("planning_plans.id", ondelete="RESTRICT")
    )
    event_id: Mapped[int | None] = mapped_column(ForeignKey("work_events.id", ondelete="RESTRICT"))
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(
        String(40), nullable=False, default="plan_applied", server_default="plan_applied"
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    diff: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # What the day looked like at this revision; never rewritten by a later one.
    plan_state: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "reason IN ('plan_applied', 'worker_redirected', 'manual_edit', 'event_replan')",
            name="day_plan_revision_reason_known",
        ),
        CheckConstraint(
            "(superseded_at IS NULL) = (superseded_by_revision IS NULL) "
            "AND NOT (is_current AND superseded_at IS NOT NULL)",
            name="day_plan_revision_superseded_consistent",
        ),
        Index(
            "uq_day_plan_revisions_current",
            "service_area_id",
            "route_date",
            unique=True,
            postgresql_where=(is_current.is_(True)),
        ),
        Index(
            "uq_day_plan_revisions_number",
            "service_area_id",
            "route_date",
            "revision",
            unique=True,
        ),
        Index("ix_day_plan_revisions_day", "service_area_id", "route_date", "revision"),
    )

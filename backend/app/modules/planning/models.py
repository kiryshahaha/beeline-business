"""Durable proposals and links to immutable applied route snapshots."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PlanningPlan(Base):
    __tablename__ = "planning_plans"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    route_date: Mapped[date] = mapped_column(Date)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(10), default="ready")
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    result_snapshot: Mapped[dict] = mapped_column(JSONB)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_fingerprint: Mapped[str | None] = mapped_column(String(64))
    apply_result: Mapped[dict | None] = mapped_column(JSONB)
    __table_args__ = (
        CheckConstraint("state IN ('ready','applied','stale','expired')", name="state_valid"),
        CheckConstraint(
            "(state = 'applied') = (applied_at IS NOT NULL) AND "
            "(applied_at IS NULL) = (apply_result IS NULL) AND "
            "(applied_at IS NULL) = (applied_fingerprint IS NULL)",
            name="applied_consistent",
        ),
        Index("ix_planning_plans_date_created", "route_date", "created_at"),
    )


class PlanningPlanRoute(Base):
    __tablename__ = "planning_plan_routes"

    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("planning_plans.id", ondelete="RESTRICT"), primary_key=True
    )
    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.user_id", ondelete="RESTRICT"), primary_key=True
    )
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id", ondelete="RESTRICT"), unique=True)

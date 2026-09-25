"""Work types and their time norms; tickets do not reference this table yet."""

from datetime import datetime

from sqlalchemy import CheckConstraint, Computed, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin


class WorkType(IntegerIdMixin, Base):
    __tablename__ = "work_types"

    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(50))
    category: Mapped[str] = mapped_column(String(50), default="repair", server_default="repair")
    default_priority: Mapped[int] = mapped_column(default=3, server_default="3")
    travel_minutes: Mapped[int]
    work_minutes: Mapped[int]
    documents_minutes: Mapped[int]
    # The base norm is always the sum of its parts, so PostgreSQL computes it.
    norm_minutes: Mapped[int] = mapped_column(
        Computed("travel_minutes + work_minutes + documents_minutes", persisted=True)
    )

    __table_args__ = (
        CheckConstraint("name = btrim(name) AND name <> ''", name="name_not_blank"),
        CheckConstraint("code = btrim(code) AND code <> ''", name="code_not_blank"),
        CheckConstraint(
            "category IN ('emergency', 'connection', 'repair', 'additional')",
            name="category_valid",
        ),
        CheckConstraint("default_priority >= 1", name="default_priority_positive"),
        CheckConstraint("travel_minutes >= 0", name="travel_minutes_nonnegative"),
        CheckConstraint("work_minutes >= 0", name="work_minutes_nonnegative"),
        CheckConstraint("documents_minutes >= 0", name="documents_minutes_nonnegative"),
        CheckConstraint("norm_minutes > 0", name="norm_minutes_positive"),
        Index("uq_work_types_name", func.lower(name), unique=True),
        Index("uq_work_types_code", func.lower(code), unique=True),
    )


class WorkTypePlanningRule(Base):
    __tablename__ = "work_type_planning_rules"

    work_type_id: Mapped[int] = mapped_column(
        ForeignKey("work_types.id", ondelete="CASCADE"), primary_key=True
    )
    service_duration_source: Mapped[str] = mapped_column(String(20))
    configured_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        CheckConstraint(
            "service_duration_source IN ('ticket_estimate', 'work_norm')", name="duration_source"
        ),
    )


class WorkTypeRequiredSkill(Base):
    __tablename__ = "work_type_required_skills"

    work_type_id: Mapped[int] = mapped_column(
        ForeignKey("work_type_planning_rules.work_type_id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[int] = mapped_column(
        ForeignKey("worker_skills.id", ondelete="RESTRICT"), primary_key=True
    )


class WorkTypeRequiredAppliance(Base):
    __tablename__ = "work_type_required_appliances"

    work_type_id: Mapped[int] = mapped_column(
        ForeignKey("work_type_planning_rules.work_type_id", ondelete="CASCADE"), primary_key=True
    )
    appliance_id: Mapped[int] = mapped_column(
        ForeignKey("appliances.id", ondelete="RESTRICT"), primary_key=True
    )
    quantity: Mapped[int]
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)

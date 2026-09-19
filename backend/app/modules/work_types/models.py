"""Work types and their time norms; tickets do not reference this table yet."""

from sqlalchemy import CheckConstraint, Computed, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin


class WorkType(IntegerIdMixin, Base):
    __tablename__ = "work_types"

    name: Mapped[str] = mapped_column(String(100))
    travel_minutes: Mapped[int]
    work_minutes: Mapped[int]
    documents_minutes: Mapped[int]
    # The base norm is always the sum of its parts, so PostgreSQL computes it.
    norm_minutes: Mapped[int] = mapped_column(
        Computed("travel_minutes + work_minutes + documents_minutes", persisted=True)
    )

    __table_args__ = (
        CheckConstraint("name = btrim(name) AND name <> ''", name="name_not_blank"),
        CheckConstraint("travel_minutes >= 0", name="travel_minutes_nonnegative"),
        CheckConstraint("work_minutes >= 0", name="work_minutes_nonnegative"),
        CheckConstraint("documents_minutes >= 0", name="documents_minutes_nonnegative"),
        CheckConstraint("norm_minutes > 0", name="norm_minutes_positive"),
        Index("uq_work_types_name", func.lower(name), unique=True),
    )

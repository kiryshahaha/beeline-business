"""SQLAlchemy models for offices."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin


class Office(IntegerIdMixin, Base):
    __tablename__ = "offices"

    name: Mapped[str] = mapped_column(String(150))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id", ondelete="RESTRICT"))

    __table_args__ = (
        CheckConstraint("name = btrim(name) AND name <> ''", name="name_not_blank"),
        Index("uq_offices_name", func.lower(name), unique=True),
    )

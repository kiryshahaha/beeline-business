"""An entrance belongs to exactly one building."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin


class Entrance(IntegerIdMixin, Base):
    __tablename__ = "entrances"

    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="RESTRICT"))
    number: Mapped[str] = mapped_column(String(30))

    __table_args__ = (
        CheckConstraint("number = btrim(number) AND number <> ''", name="number_not_blank"),
        Index("uq_entrances_building_number", building_id, func.lower(number), unique=True),
        # Referenced by Location's composite FK to prevent selecting another building's entrance.
        UniqueConstraint("id", "building_id", name="uq_entrances_id_building"),
    )

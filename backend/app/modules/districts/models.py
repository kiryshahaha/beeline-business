"""A district belongs to one city and can contain buildings on different streets."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin


class District(IntegerIdMixin, Base):
    __tablename__ = "districts"

    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(150))

    __table_args__ = (
        CheckConstraint("name = btrim(name) AND name <> ''", name="name_not_blank"),
        UniqueConstraint("id", "city_id", name="uq_districts_id_city"),
        Index("uq_districts_city_name", city_id, func.lower(name), unique=True),
    )

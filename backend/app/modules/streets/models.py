"""Streets belong to a city; names include the street type, e.g. 'улица Ленина'."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin


class Street(IntegerIdMixin, Base):
    __tablename__ = "streets"

    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(200))

    __table_args__ = (
        CheckConstraint("name = btrim(name) AND name <> ''", name="name_not_blank"),
        UniqueConstraint("id", "city_id", name="uq_streets_id_city"),
        Index("uq_streets_city_name", city_id, func.lower(name), unique=True),
    )

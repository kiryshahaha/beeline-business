"""City directory. Region support is intentionally deferred by agreement."""

from sqlalchemy import CheckConstraint, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin


class City(IntegerIdMixin, Base):
    __tablename__ = "cities"

    name: Mapped[str] = mapped_column(String(150))

    __table_args__ = (
        CheckConstraint("name = btrim(name) AND name <> ''", name="name_not_blank"),
        Index("uq_cities_name", func.lower(name), unique=True),
    )

"""A building is shared by its entrances and service locations."""

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin


class Building(IntegerIdMixin, Base):
    __tablename__ = "buildings"

    # Shared city_id makes both composite foreign keys enforce the same city.
    city_id: Mapped[int] = mapped_column()
    street_id: Mapped[int] = mapped_column()
    district_id: Mapped[int] = mapped_column()
    number: Mapped[str] = mapped_column(String(30))
    block: Mapped[str | None] = mapped_column(String(30))

    __table_args__ = (
        ForeignKeyConstraint(
            ["street_id", "city_id"],
            ["streets.id", "streets.city_id"],
            name="fk_buildings_street_city",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["district_id", "city_id"],
            ["districts.id", "districts.city_id"],
            name="fk_buildings_district_city",
            ondelete="RESTRICT",
        ),
        Index("ix_buildings_district_id", "district_id"),
        CheckConstraint("number = btrim(number) AND number <> ''", name="number_not_blank"),
        CheckConstraint(
            "block IS NULL OR (block = btrim(block) AND block <> '')", name="block_not_blank"
        ),
        Index(
            "uq_buildings_street_number_block",
            street_id,
            func.lower(number),
            func.lower(block),
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

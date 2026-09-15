"""A reusable service destination, including a specific apartment or room."""

from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin


class Location(IntegerIdMixin, Base):
    __tablename__ = "locations"

    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="RESTRICT"))
    entrance_id: Mapped[int | None] = mapped_column(index=True)
    floor: Mapped[int | None]
    apartment: Mapped[str | None] = mapped_column(String(30))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))

    __table_args__ = (
        ForeignKeyConstraint(
            ["entrance_id", "building_id"],
            ["entrances.id", "entrances.building_id"],
            name="fk_locations_entrance_building",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "apartment IS NULL OR (apartment = btrim(apartment) AND apartment <> '')",
            name="apartment_not_blank",
        ),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="coordinates_pair"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
        # NULL means an unspecified entrance/apartment; it must not bypass deduplication.
        Index(
            "uq_locations_destination",
            building_id,
            entrance_id,
            func.lower(apartment),
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

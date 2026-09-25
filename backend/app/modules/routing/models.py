"""Immutable route snapshots. Numbers are scoped to worker and service date."""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin


class Route(IntegerIdMixin, Base):
    __tablename__ = "routes"

    # RESTRICT: an engineer with route history is archived, not deleted (T14).
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.user_id", ondelete="RESTRICT"))
    route_date: Mapped[date] = mapped_column(Date)
    route_number: Mapped[int]
    geojson: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("route_number > 0", name="number_positive"),
        CheckConstraint(
            "jsonb_typeof(geojson) = 'object' AND geojson ? 'type' AND geojson ? 'features' "
            "AND geojson->>'type' IS NOT NULL "
            "AND geojson->>'type' = 'FeatureCollection' "
            "AND jsonb_typeof(geojson->'features') = 'array'",
            name="geojson_collection",
        ),
        Index(
            "uq_routes_worker_date_number", "worker_id", "route_date", "route_number", unique=True
        ),
        Index("ix_routes_date", "route_date"),
    )

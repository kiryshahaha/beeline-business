"""Service areas isolate independent operational territories and planning scenarios."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin


class ServiceArea(IntegerIdMixin, Base):
    __tablename__ = "service_areas"

    code: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("code = btrim(code) AND code <> ''", name="service_area_code_not_blank"),
        CheckConstraint("name = btrim(name) AND name <> ''", name="service_area_name_not_blank"),
        Index("uq_service_areas_code", func.lower(code), unique=True),
    )

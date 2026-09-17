"""SQLAlchemy models for appliances, office stocks, and ticket appliance allocations."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin
from app.modules.appliances.enums import ApplianceType


class Appliance(IntegerIdMixin, Base):
    __tablename__ = "appliances"

    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[ApplianceType] = mapped_column(
        Enum(
            ApplianceType,
            values_callable=lambda types: [t.value for t in types],
            native_enum=False,
            create_constraint=True,
            name="appliance_type",
        )
    )
    unit: Mapped[str] = mapped_column(String(20), default="шт", server_default="шт")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("name = btrim(name) AND name <> ''", name="name_not_blank"),
        Index("uq_appliances_name", func.lower(name), unique=True),
    )


class ApplianceStock(Base):
    __tablename__ = "appliance_stocks"

    office_id: Mapped[int] = mapped_column(
        ForeignKey("offices.id", ondelete="RESTRICT"), primary_key=True
    )
    appliance_id: Mapped[int] = mapped_column(
        ForeignKey("appliances.id", ondelete="RESTRICT"), primary_key=True
    )
    stock: Mapped[int] = mapped_column(default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("stock >= 0", name="stock_nonnegative"),
    )


class TicketAppliance(Base):
    __tablename__ = "ticket_appliances"

    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True
    )
    appliance_id: Mapped[int] = mapped_column(
        ForeignKey("appliances.id", ondelete="RESTRICT"), primary_key=True
    )
    office_id: Mapped[int] = mapped_column(
        ForeignKey("offices.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        Index("ix_ticket_appliances_office_appliance", "office_id", "appliance_id"),
    )

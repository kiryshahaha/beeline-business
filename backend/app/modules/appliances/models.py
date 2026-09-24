"""SQLAlchemy models for appliances, office stocks, allocations and units on hand."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
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

    __table_args__ = (CheckConstraint("stock >= 0", name="stock_nonnegative"),)


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        Index("ix_ticket_appliances_office_appliance", "office_id", "appliance_id"),
    )


class OfficeKitReserve(Base):
    """Declared units every engineer of the office carries beyond assigned tickets."""

    __tablename__ = "office_kit_reserves"

    office_id: Mapped[int] = mapped_column(
        ForeignKey("offices.id", ondelete="RESTRICT"), primary_key=True
    )
    appliance_id: Mapped[int] = mapped_column(
        ForeignKey("appliances.id", ondelete="RESTRICT"), primary_key=True
    )
    quantity: Mapped[int]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)


class WorkerAppliance(Base):
    """Units physically on hand; a row exists only while the quantity is positive."""

    __tablename__ = "worker_appliances"

    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.user_id", ondelete="RESTRICT"), primary_key=True
    )
    appliance_id: Mapped[int] = mapped_column(
        ForeignKey("appliances.id", ondelete="RESTRICT"), primary_key=True
    )
    quantity: Mapped[int]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)


class ApplianceOperation(IntegerIdMixin, Base):
    """One idempotent inventory operation; its movements are the ledger lines."""

    __tablename__ = "appliance_operations"

    operation_key: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(10))
    worker_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    ticket_id: Mapped[int | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="SET NULL"), index=True
    )
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reason: Mapped[str | None] = mapped_column(Text)
    request: Mapped[dict | None] = mapped_column(JSONB)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("kind IN ('issue','return','consume','restore')", name="kind_valid"),
    )


class ApplianceMovement(IntegerIdMixin, Base):
    """Units moved between an office, an engineer and the client (both ends null = client)."""

    __tablename__ = "appliance_movements"

    operation_id: Mapped[int] = mapped_column(
        ForeignKey("appliance_operations.id", ondelete="CASCADE"), index=True
    )
    appliance_id: Mapped[int] = mapped_column(ForeignKey("appliances.id", ondelete="RESTRICT"))
    quantity: Mapped[int]
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id", ondelete="SET NULL"))
    from_office_id: Mapped[int | None] = mapped_column(
        ForeignKey("offices.id", ondelete="RESTRICT")
    )
    from_worker_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    to_office_id: Mapped[int | None] = mapped_column(ForeignKey("offices.id", ondelete="RESTRICT"))
    to_worker_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "num_nonnulls(from_office_id, from_worker_id) <= 1"
            " AND num_nonnulls(to_office_id, to_worker_id) <= 1"
            " AND num_nonnulls(from_office_id, from_worker_id, to_office_id, to_worker_id) >= 1",
            name="ends_valid",
        ),
    )


class TicketApplianceState(Base):
    """Where allocated units are; no row means they are still reserved in the office."""

    __tablename__ = "ticket_appliance_states"

    ticket_id: Mapped[int] = mapped_column(primary_key=True)
    appliance_id: Mapped[int] = mapped_column(primary_key=True)
    holder_worker_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    # Explicit name: the generated one exceeds PostgreSQL's 63-character limit.
    consumed_operation_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "appliance_operations.id",
            ondelete="RESTRICT",
            name="fk_ticket_appliance_states_consumed_operation",
        )
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["ticket_id", "appliance_id"],
            ["ticket_appliances.ticket_id", "ticket_appliances.appliance_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "holder_worker_id IS NOT NULL OR consumed_operation_id IS NOT NULL",
            name="state_present",
        ),
    )

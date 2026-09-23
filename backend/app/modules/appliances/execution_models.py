"""Immutable equipment movements produced by execution facts."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin


class EquipmentMovement(IntegerIdMixin, Base):
    __tablename__ = "equipment_movements"

    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="RESTRICT"), nullable=False
    )
    execution_cycle: Mapped[int] = mapped_column(Integer, nullable=False)
    appliance_id: Mapped[int] = mapped_column(
        ForeignKey("appliances.id", ondelete="RESTRICT"), nullable=False
    )
    office_id: Mapped[int] = mapped_column(
        ForeignKey("offices.id", ondelete="RESTRICT"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(
        ForeignKey("work_events.id", ondelete="RESTRICT"), nullable=False
    )
    movement: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index(
            "uq_equipment_movements_ticket_cycle_appliance_movement",
            "ticket_id",
            "execution_cycle",
            "appliance_id",
            "movement",
            unique=True,
        ),
        CheckConstraint("execution_cycle > 0", name="execution_cycle_positive"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("movement IN ('consume')", name="movement_valid"),
    )

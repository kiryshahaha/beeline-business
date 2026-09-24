"""The central work request, independent of future planning and engineer modules."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin
from app.modules.execution.enums import TicketLifecycleState
from app.modules.tickets.enums import TicketStatus


class Ticket(IntegerIdMixin, Base):
    __tablename__ = "tickets"

    location_id: Mapped[int] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    work_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[TicketStatus] = mapped_column(
        Enum(
            TicketStatus,
            values_callable=lambda statuses: [status.value for status in statuses],
            native_enum=False,
            create_constraint=True,
            name="ticket_status",
        ),
        default=TicketStatus.PLANNED,
        server_default=TicketStatus.PLANNED.value,
    )
    lifecycle_state: Mapped[TicketLifecycleState] = mapped_column(
        Enum(
            TicketLifecycleState,
            values_callable=lambda states: [state.value for state in states],
            native_enum=False,
            create_constraint=True,
            name="ticket_lifecycle_state",
        ),
        default=TicketLifecycleState.WAITING_ASSIGNMENT,
        server_default=TicketLifecycleState.WAITING_ASSIGNMENT.value,
        nullable=False,
    )
    visit_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    visit_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    planned_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_duration_minutes: Mapped[int]
    actual_duration_minutes: Mapped[int | None]
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    execution_cycle: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    actual_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    last_event_id: Mapped[int | None] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("title = btrim(title) AND title <> ''", name="title_not_blank"),
        CheckConstraint(
            "work_type = btrim(work_type) AND work_type <> ''", name="work_type_not_blank"
        ),
        CheckConstraint("visit_window_end > visit_window_start", name="visit_window_order"),
        CheckConstraint(
            "(planned_start_at IS NULL) = (planned_end_at IS NULL)", name="planned_time_pair"
        ),
        CheckConstraint("planned_end_at > planned_start_at", name="planned_time_order"),
        CheckConstraint("estimated_duration_minutes > 0", name="estimated_duration_positive"),
        CheckConstraint("actual_duration_minutes >= 0", name="actual_duration_nonnegative"),
        CheckConstraint("revision > 0", name="revision_positive"),
        CheckConstraint("execution_cycle > 0", name="execution_cycle_positive"),
        Index("ix_tickets_status_planned_start", status, planned_start_at),
        Index("ix_tickets_lifecycle_state", lifecycle_state),
        Index("ix_tickets_visit_window_start", visit_window_start),
    )


class TicketAssignment(Base):
    __tablename__ = "ticket_assignments"

    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True
    )
    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.user_id", ondelete="CASCADE"), primary_key=True, index=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

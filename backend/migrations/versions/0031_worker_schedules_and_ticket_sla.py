"""Add calendar schedules (2/2, 5/2), shift exceptions, and response deadline.

Revision ID: 0031
Revises: 0030
"""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Worker schedules
    op.add_column(
        "workers",
        sa.Column("schedule_type", sa.String(20), nullable=False, server_default="5/2"),
    )
    op.create_check_constraint(
        "worker_schedule_type",
        "workers",
        "schedule_type IN ('2/2', '5/2')",
    )
    op.add_column(
        "workers",
        sa.Column("cycle_start_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "workers",
        sa.Column("workdays_mask", sa.JSON(), nullable=True),
    )

    # 2. Worker shift exceptions
    op.create_table(
        "worker_shift_exceptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("exception_date", sa.Date(), nullable=False),
        sa.Column("is_working", sa.Boolean(), nullable=False),
        sa.Column("workshift_start", sa.Time(), nullable=True),
        sa.Column("workshift_end", sa.Time(), nullable=True),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["workers.user_id"],
            name="fk_worker_shift_exceptions_worker_id_workers",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "is_working = false OR (workshift_start IS NOT NULL AND workshift_end IS NOT NULL "
            "AND workshift_start <> workshift_end)",
            name="worker_shift_exception_hours_valid",
        ),
    )
    op.create_index(
        "ix_worker_shift_exceptions_worker_id",
        "worker_shift_exceptions",
        ["worker_id"],
    )
    op.create_index(
        "uq_worker_shift_exception_date",
        "worker_shift_exceptions",
        ["worker_id", "exception_date"],
        unique=True,
    )

    # 3. Ticket response deadline and intake source
    op.add_column(
        "tickets",
        sa.Column("response_deadline_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column("intake_source", sa.String(50), nullable=True),
    )
    op.create_check_constraint(
        "response_deadline_after_received",
        "tickets",
        "response_deadline_at IS NULL OR response_deadline_at > received_at",
    )

    # Backfill emergency tickets response deadline to received_at + 2 hours
    op.execute(
        """
        UPDATE tickets
        SET response_deadline_at = received_at + INTERVAL '2 hours'
        WHERE category = 'emergency' AND response_deadline_at IS NULL
        """
    )


def downgrade() -> None:
    # 3. Tickets
    op.drop_constraint("response_deadline_after_received", "tickets", type_="check")
    op.drop_column("tickets", "intake_source")
    op.drop_column("tickets", "response_deadline_at")

    # 2. Worker shift exceptions
    op.drop_index("uq_worker_shift_exception_date", table_name="worker_shift_exceptions")
    op.drop_index("ix_worker_shift_exceptions_worker_id", table_name="worker_shift_exceptions")
    op.drop_table("worker_shift_exceptions")

    # 1. Worker schedules
    op.drop_column("workers", "workdays_mask")
    op.drop_column("workers", "cycle_start_date")
    op.drop_constraint("worker_schedule_type", "workers", type_="check")
    op.drop_column("workers", "schedule_type")

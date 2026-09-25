"""T07 Single Assignment

Revision ID: 6a36204671b2
Revises: 0020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6a36204671b2"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add columns to tickets
    op.add_column("tickets", sa.Column("assigned_worker_id", sa.Integer(), nullable=True))
    op.add_column(
        "tickets", sa.Column("is_pinned", sa.Boolean(), server_default="false", nullable=False)
    )

    # Create foreign key and index
    op.create_foreign_key(
        "fk_tickets_assigned_worker_id_workers",
        "tickets",
        "workers",
        ["assigned_worker_id"],
        ["user_id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_tickets_assigned_worker_id"), "tickets", ["assigned_worker_id"], unique=False
    )

    # Migrate data from ticket_assignments to tickets
    connection = op.get_bind()
    print("Migrating assignments...")

    # We want to pick the latest assignment for each ticket
    # First we pick the ticket_id and the worker_id with the max assigned_at
    update_sql = sa.text("""
        UPDATE tickets
        SET assigned_worker_id = latest_assignment.worker_id
        FROM (
            SELECT DISTINCT ON (ticket_id) ticket_id, worker_id
            FROM ticket_assignments
            ORDER BY ticket_id, assigned_at DESC
        ) AS latest_assignment
        WHERE tickets.id = latest_assignment.ticket_id
    """)
    connection.execute(update_sql)

    # Now log conflicts
    conflicts_sql = sa.text("""
        SELECT ticket_id, count(worker_id)
        FROM ticket_assignments
        GROUP BY ticket_id
        HAVING count(worker_id) > 1
    """)
    conflicts = connection.execute(conflicts_sql).fetchall()
    if conflicts:
        print(
            f"WARNING: Found {len(conflicts)} tickets with multiple assignments. "
            "Only the latest assignee was kept. Others were unassigned."
        )

    # Drop ticket_assignments table
    op.drop_index("ix_ticket_assignments_worker_id", table_name="ticket_assignments")
    op.drop_table("ticket_assignments")


def downgrade() -> None:
    # Recreate ticket_assignments table
    op.create_table(
        "ticket_assignments",
        sa.Column("ticket_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("worker_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name="ticket_assignments_ticket_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["workers.user_id"],
            name="ticket_assignments_worker_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ticket_id", "worker_id", name="ticket_assignments_pkey"),
    )
    op.create_index(
        "ix_ticket_assignments_worker_id", "ticket_assignments", ["worker_id"], unique=False
    )

    # Migrate data back
    connection = op.get_bind()
    connection.execute(
        sa.text("""
        INSERT INTO ticket_assignments (ticket_id, worker_id)
        SELECT id, assigned_worker_id
        FROM tickets
        WHERE assigned_worker_id IS NOT NULL
    """)
    )

    # Drop columns
    op.drop_constraint("fk_tickets_assigned_worker_id_workers", "tickets", type_="foreignkey")
    op.drop_index(op.f("ix_tickets_assigned_worker_id"), table_name="tickets")
    op.drop_column("tickets", "is_pinned")
    op.drop_column("tickets", "assigned_worker_id")

"""Archive users instead of deleting their history; routes and assignments are never cascaded.

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

# Deleting an engineer used to delete their route snapshots and ticket assignments.
HISTORY_KEYS = (
    ("routes", "fk_routes_worker_id_workers"),
    ("ticket_assignments", "fk_ticket_assignments_worker_id_workers"),
)


def _recreate(ondelete: str) -> None:
    for table, name in HISTORY_KEYS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, "workers", ["worker_id"], ["user_id"], ondelete=ondelete)


def upgrade() -> None:
    op.add_column("users", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    _recreate("RESTRICT")


def downgrade() -> None:
    _recreate("CASCADE")
    op.drop_column("users", "archived_at")

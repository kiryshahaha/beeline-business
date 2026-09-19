"""Add compatible transport type to existing workers.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workers",
        sa.Column("transport_type", sa.String(16), nullable=False, server_default="walking"),
    )
    op.create_check_constraint(
        "worker_transport_type",
        "workers",
        "transport_type IN ('car', 'walking', 'bicycle', 'public_transport')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_workers_worker_transport_type"), "workers", type_="check")
    op.drop_column("workers", "transport_type")

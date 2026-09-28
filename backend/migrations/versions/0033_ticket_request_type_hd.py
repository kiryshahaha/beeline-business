"""Add request_type_hd to tickets.

Revision ID: 0033
Revises: 0032
"""

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column("request_type_hd", sa.String(100), nullable=True),
    )
    op.create_index(
        "ix_tickets_request_type_hd",
        "tickets",
        ["request_type_hd"],
    )

    # Backfill request_type_hd from source_records where available
    op.execute(
        """
        UPDATE tickets AS t
        SET request_type_hd = sr.hd_type
        FROM source_records AS sr
        WHERE sr.ticket_id = t.id
          AND sr.hd_type IS NOT NULL
          AND t.request_type_hd IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_tickets_request_type_hd", table_name="tickets")
    op.drop_column("tickets", "request_type_hd")

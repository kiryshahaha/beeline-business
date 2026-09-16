"""Track the last update time for ticket comments.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE ticket_comments
            ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE ticket_comments DROP COLUMN updated_at")

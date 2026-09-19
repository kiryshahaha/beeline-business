"""Add personal calendar feed tokens

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-19 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calendar_tokens",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_calendar_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_calendar_tokens")),
    )
    op.create_index("uq_calendar_tokens_token_hash", "calendar_tokens", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_calendar_tokens_token_hash", table_name="calendar_tokens")
    op.drop_table("calendar_tokens")

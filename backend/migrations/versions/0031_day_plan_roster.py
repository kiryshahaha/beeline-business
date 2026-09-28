"""Keep the engineers admitted to a published area-day as its roster.

Revision ID: 0031
Revises: 0030

Existing revisions keep NULL: nothing recorded who was admitted to them. Replanning
such a day rebuilds the roster from the immutable planning snapshots it was applied
with, or refuses instead of taking every engineer of the area.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "day_plan_revisions",
        sa.Column("roster", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        "day_plan_revision_roster_is_list",
        "day_plan_revisions",
        "roster IS NULL OR jsonb_typeof(roster) = 'array'",
    )


def downgrade() -> None:
    op.drop_constraint("day_plan_revision_roster_is_list", "day_plan_revisions", type_="check")
    op.drop_column("day_plan_revisions", "roster")

"""Track the current and historical route revision for each district-day."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "day_plan_revisions",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("district_id", sa.Integer(), nullable=False),
        sa.Column("route_date", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("previous_revision", sa.Integer()),
        sa.Column("event_id", sa.Integer()),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "diff", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "result", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("is_current", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["district_id"],
            ["districts.id"],
            name="fk_day_plan_revisions_district_id_districts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["work_events.id"],
            name="fk_day_plan_revisions_event_id_work_events",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name="fk_day_plan_revisions_actor_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_day_plan_revisions"),
    )
    op.create_index(
        "uq_day_plan_revisions_current",
        "day_plan_revisions",
        ["district_id", "route_date"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "ix_day_plan_revisions_day",
        "day_plan_revisions",
        ["district_id", "route_date", "revision"],
    )


def downgrade() -> None:
    op.drop_index("ix_day_plan_revisions_day", table_name="day_plan_revisions")
    op.drop_index("uq_day_plan_revisions_current", table_name="day_plan_revisions")
    op.drop_table("day_plan_revisions")

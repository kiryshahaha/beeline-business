"""Persist expiring previews and idempotent application receipts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "planning_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("route_date", sa.Date(), nullable=False),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(10), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("result_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("applied_fingerprint", sa.String(64)),
        sa.Column("apply_result", postgresql.JSONB()),
        sa.CheckConstraint("state IN ('ready','applied','stale','expired')", name="state_valid"),
        sa.CheckConstraint(
            "(state = 'applied') = (applied_at IS NOT NULL) AND "
            "(applied_at IS NULL) = (apply_result IS NULL) AND "
            "(applied_at IS NULL) = (applied_fingerprint IS NULL)",
            name="applied_consistent",
        ),
    )
    op.create_index(
        "ix_planning_plans_date_created", "planning_plans", ["route_date", "created_at"]
    )
    op.create_table(
        "planning_plan_routes",
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("planning_plans.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "worker_id",
            sa.Integer(),
            sa.ForeignKey("workers.user_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "route_id",
            sa.Integer(),
            sa.ForeignKey("routes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.UniqueConstraint("route_id"),
    )


def downgrade():
    op.drop_table("planning_plan_routes")
    op.drop_index("ix_planning_plans_date_created", table_name="planning_plans")
    op.drop_table("planning_plans")

"""Explicit planning requirements for work types; no invented eligibility defaults."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "work_type_planning_rules",
        sa.Column(
            "work_type_id",
            sa.Integer(),
            sa.ForeignKey("work_types.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("service_duration_source", sa.String(20), nullable=False),
        sa.Column(
            "configured_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "service_duration_source IN ('ticket_estimate', 'work_norm')", name="duration_source"
        ),
    )
    op.create_table(
        "work_type_required_skills",
        sa.Column(
            "work_type_id",
            sa.Integer(),
            sa.ForeignKey("work_type_planning_rules.work_type_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "skill_id",
            sa.Integer(),
            sa.ForeignKey("worker_skills.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
    )
    op.create_table(
        "work_type_required_appliances",
        sa.Column(
            "work_type_id",
            sa.Integer(),
            sa.ForeignKey("work_type_planning_rules.work_type_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "appliance_id",
            sa.Integer(),
            sa.ForeignKey("appliances.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
    )


def downgrade():
    op.drop_table("work_type_required_appliances")
    op.drop_table("work_type_required_skills")
    op.drop_table("work_type_planning_rules")

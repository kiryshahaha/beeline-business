"""Add separate day revision reasons for regular and emergency ticket events.

Revision ID: 0034
Revises: 0033
"""

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


_OLD_REASONS = "'plan_applied', 'worker_redirected', 'manual_edit', 'event_replan'"
_NEW_REASONS = _OLD_REASONS + ", 'ticket_inserted', 'emergency_replan'"


def upgrade() -> None:
    op.drop_constraint("day_plan_revision_reason_known", "day_plan_revisions", type_="check")
    op.create_check_constraint(
        "day_plan_revision_reason_known",
        "day_plan_revisions",
        f"reason IN ({_NEW_REASONS})",
    )


def downgrade() -> None:
    op.drop_constraint("day_plan_revision_reason_known", "day_plan_revisions", type_="check")
    op.create_check_constraint(
        "day_plan_revision_reason_known",
        "day_plan_revisions",
        f"reason IN ({_OLD_REASONS})",
    )

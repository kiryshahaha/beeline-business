"""Add completion review records and worker app notification kinds."""

import sqlalchemy as sa
from alembic import op

revision = "0033_worker_app_api"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticket_completion_reviews",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("execution_cycle", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("actual_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("decision_idempotency_key", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("ticket_id", "execution_cycle", name="uq_completion_review_cycle"),
        sa.UniqueConstraint("decision_idempotency_key", name="uq_completion_review_idempotency"),
        sa.CheckConstraint("char_length(note) BETWEEN 1 AND 2000", name="note_length"),
        sa.CheckConstraint(
            "actual_duration_minutes IS NULL OR actual_duration_minutes >= 0",
            name="actual_duration_nonnegative",
        ),
        sa.CheckConstraint("state IN ('pending', 'confirmed', 'rejected')", name="state_valid"),
        sa.CheckConstraint(
            "(state = 'pending' AND decided_by IS NULL AND decided_at IS NULL) OR "
            "(state IN ('confirmed', 'rejected') AND decided_by IS NOT NULL "
            "AND decided_at IS NOT NULL)",
            name="decision_consistent",
        ),
        sa.CheckConstraint(
            "state <> 'rejected' OR decision_comment IS NOT NULL", name="reject_reason_required"
        ),
    )
    op.create_index(
        "ix_completion_reviews_state_requested",
        "ticket_completion_reviews",
        ["state", "requested_at"],
    )
    op.create_index(
        "ix_completion_reviews_worker",
        "ticket_completion_reviews",
        ["requested_by", "requested_at"],
    )
    op.drop_constraint(op.f("ck_work_events_work_event_type"), "work_events", type_="check")
    op.create_check_constraint(
        op.f("ck_work_events_work_event_type"),
        "work_events",
        "event_type IN ('new_ticket', 'assign', 'unassign', 'dispatch', 'start_route', "
        "'start', 'complete', 'cancel_ticket', 'reopen', 'progress_delay', "
        "'worker_unavailable', 'window_change', 'redirect', 'problem_reported')",
    )
    op.drop_constraint(
        op.f("ck_notification_events_kind_valid"), "notification_events", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_notification_events_kind_valid"),
        "notification_events",
        "kind IN ('ticket_assigned', 'ticket_status_changed', 'ticket_unassigned', "
        "'ticket_rescheduled', 'ticket_window_changed', 'ticket_completion_confirmed', "
        "'ticket_completion_rejected', 'ticket_completion_requested', "
        "'ticket_delay_reported', 'ticket_problem_reported')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_work_events_work_event_type"), "work_events", type_="check")
    op.create_check_constraint(
        op.f("ck_work_events_work_event_type"),
        "work_events",
        "event_type IN ('new_ticket', 'assign', 'unassign', 'dispatch', 'start_route', "
        "'start', 'complete', 'cancel_ticket', 'reopen', 'progress_delay', "
        "'worker_unavailable', 'window_change', 'redirect')",
    )
    op.drop_constraint(
        op.f("ck_notification_events_kind_valid"), "notification_events", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_notification_events_kind_valid"),
        "notification_events",
        "kind IN ('ticket_assigned', 'ticket_status_changed')",
    )
    op.drop_index("ix_completion_reviews_worker", table_name="ticket_completion_reviews")
    op.drop_index("ix_completion_reviews_state_requested", table_name="ticket_completion_reviews")
    op.drop_table("ticket_completion_reviews")

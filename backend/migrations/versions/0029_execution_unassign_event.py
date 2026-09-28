"""Record plan-driven release of an assignment in the lifecycle history."""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

EVENT_TYPES = (
    "new_ticket",
    "assign",
    "unassign",
    "dispatch",
    "start_route",
    "start",
    "complete",
    "cancel_ticket",
    "reopen",
    "progress_delay",
    "worker_unavailable",
    "window_change",
    "redirect",
)


def _replace_check(event_types):
    values = ", ".join(f"'{event_type}'" for event_type in event_types)
    name = op.f("ck_work_events_work_event_type")
    op.drop_constraint(name, "work_events", type_="check")
    op.create_check_constraint(
        name,
        "work_events",
        f"event_type IN ({values})",
    )


def upgrade() -> None:
    _replace_check(EVENT_TYPES)


def downgrade() -> None:
    bind = op.get_bind()
    has_unassign_events = bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM work_events WHERE event_type = 'unassign')")
    ).scalar_one()
    if has_unassign_events:
        raise RuntimeError(
            "Cannot remove unassign while lifecycle history contains unassign events"
        )
    _replace_check(tuple(event for event in EVENT_TYPES if event != "unassign"))

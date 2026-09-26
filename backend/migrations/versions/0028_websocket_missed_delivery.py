"""Record that nobody was connected, instead of calling it a WebSocket delivery.

Before this, an event was marked delivered after publishing to this process's own
sockets even when there were none. `websocket_missed_at` makes that case explicit: the
event stays in the recipient's history and reaches them through the reconnect replay.
Rows already marked delivered keep that mark — whether a socket received them was not
recorded, so it cannot be reconstructed.
"""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_events",
        sa.Column("websocket_missed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_notification_events_websocket_outcome_single"),
        "notification_events",
        "websocket_delivered_at IS NULL OR websocket_missed_at IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_notification_events_websocket_outcome_single"),
        "notification_events",
        type_="check",
    )
    op.drop_column("notification_events", "websocket_missed_at")

"""Record every change of a ticket's assignee as an independent domain event.

A trigger writes the row, so no code path — manual assignment, plan apply, taking an
engineer off the line, reopening a ticket, or a direct SQL fix — can change the assignee without
leaving history. The service layer passes the actor and the source through transaction
settings; a change made without them is still recorded, with the source `direct`.
"""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "b4b4a9a49709"
branch_labels = None
depends_on = None

SOURCES = "'manual', 'plan', 'line_status', 'direct', 'backfill'"


def upgrade() -> None:
    op.create_table(
        "ticket_assignment_events",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("previous_worker_id", sa.Integer()),
        sa.Column("new_worker_id", sa.Integer()),
        sa.Column("actor_id", sa.Integer()),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(f"source IN ({SOURCES})", name="assignment_source_known"),
        sa.CheckConstraint(
            "previous_worker_id IS DISTINCT FROM new_worker_id", name="assignment_changes"
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name="fk_ticket_assignment_events_ticket_id_tickets",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["previous_worker_id"],
            ["workers.user_id"],
            name="fk_ticket_assignment_events_previous_worker_id_workers",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["new_worker_id"],
            ["workers.user_id"],
            name="fk_ticket_assignment_events_new_worker_id_workers",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name="fk_ticket_assignment_events_actor_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ticket_assignment_events"),
    )
    op.create_index(
        "ix_ticket_assignment_events_ticket",
        "ticket_assignment_events",
        ["ticket_id", "occurred_at"],
    )
    op.create_index(
        "ix_ticket_assignment_events_previous_worker",
        "ticket_assignment_events",
        ["previous_worker_id", "occurred_at"],
    )
    op.create_index(
        "ix_ticket_assignment_events_occurred_at",
        "ticket_assignment_events",
        ["occurred_at"],
    )

    # Assignments recorded before this table existed live in the lifecycle log.
    op.execute(
        """
        INSERT INTO ticket_assignment_events (
            ticket_id, previous_worker_id, new_worker_id, actor_id, source, occurred_at
        )
        SELECT
            event.ticket_id,
            NULL,
            worker.user_id,
            event.actor_id,
            'backfill',
            event.occurred_at
        FROM work_events AS event
        JOIN workers AS worker
          ON worker.user_id = COALESCE(
              event.worker_id, (event.payload -> 'worker_ids' ->> 0)::integer
          )
        WHERE event.event_type = 'assign' AND event.ticket_id IS NOT NULL
        """
    )

    op.execute(
        """
        CREATE FUNCTION record_ticket_assignment() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            actor text := NULLIF(current_setting('app.actor_id', true), '');
            origin text := NULLIF(current_setting('app.assignment_source', true), '');
        BEGIN
            INSERT INTO ticket_assignment_events (
                ticket_id, previous_worker_id, new_worker_id, actor_id, source
            ) VALUES (
                NEW.id,
                OLD.assigned_worker_id,
                NEW.assigned_worker_id,
                actor::integer,
                COALESCE(origin, 'direct')
            );
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER tickets_record_assignment
        AFTER UPDATE OF assigned_worker_id ON tickets
        FOR EACH ROW
        WHEN (OLD.assigned_worker_id IS DISTINCT FROM NEW.assigned_worker_id)
        EXECUTE FUNCTION record_ticket_assignment()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tickets_record_assignment ON tickets")
    op.execute("DROP FUNCTION IF EXISTS record_ticket_assignment()")
    op.drop_index("ix_ticket_assignment_events_occurred_at", table_name="ticket_assignment_events")
    op.drop_index(
        "ix_ticket_assignment_events_previous_worker", table_name="ticket_assignment_events"
    )
    op.drop_index("ix_ticket_assignment_events_ticket", table_name="ticket_assignment_events")
    op.drop_table("ticket_assignment_events")

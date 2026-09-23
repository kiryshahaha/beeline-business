"""Add district divisions, canonical ticket state, and execution facts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


LIFECYCLE_STATES = (
    "waiting_assignment",
    "assigned",
    "dispatched",
    "en_route",
    "in_progress",
    "completed",
    "cancelled",
)
EVENT_TYPES = (
    "new_ticket",
    "assign",
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


def upgrade() -> None:
    op.create_table(
        "divisions",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("district_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["district_id"],
            ["districts.id"],
            name="fk_divisions_district_id_districts",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_divisions"),
    )
    op.create_index("uq_divisions_district_id", "divisions", ["district_id"], unique=True)
    op.execute("INSERT INTO divisions (district_id) SELECT id FROM districts ORDER BY id")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ensure_district_division()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            INSERT INTO divisions (district_id)
            VALUES (NEW.id)
            ON CONFLICT (district_id) DO NOTHING;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER district_division_after_insert
        AFTER INSERT ON districts
        FOR EACH ROW EXECUTE FUNCTION ensure_district_division();
        """
    )

    op.add_column("brigades", sa.Column("division_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE brigades AS br
        SET division_id = div.id
        FROM offices AS office
        JOIN locations AS location ON location.id = office.location_id
        JOIN buildings AS building ON building.id = location.building_id
        JOIN divisions AS div ON div.district_id = building.district_id
        WHERE br.office_id = office.id
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM brigades WHERE division_id IS NULL) THEN
                RAISE EXCEPTION 'Every brigade must resolve to an office district';
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_brigade_division_from_office()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            SELECT div.id
            INTO NEW.division_id
            FROM offices AS office
            JOIN locations AS location ON location.id = office.location_id
            JOIN buildings AS building ON building.id = location.building_id
            JOIN divisions AS div ON div.district_id = building.district_id
            WHERE office.id = NEW.office_id;

            IF NEW.division_id IS NULL THEN
                RAISE EXCEPTION 'Brigade office must belong to a district';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER brigade_division_from_office
        BEFORE INSERT OR UPDATE OF office_id, division_id ON brigades
        FOR EACH ROW EXECUTE FUNCTION set_brigade_division_from_office()
        """
    )
    op.alter_column("brigades", "division_id", existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key(
        "fk_brigades_division_id_divisions",
        "brigades",
        "divisions",
        ["division_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_brigades_division_id", "brigades", ["division_id"])

    lifecycle_type = sa.Enum(
        *LIFECYCLE_STATES,
        name="ticket_lifecycle_state",
        native_enum=False,
        create_constraint=True,
    )
    op.add_column(
        "tickets",
        sa.Column(
            "lifecycle_state",
            lifecycle_type,
            server_default="waiting_assignment",
            nullable=False,
        ),
    )
    op.add_column(
        "tickets",
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "tickets",
        sa.Column("execution_cycle", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("tickets", sa.Column("actual_started_at", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("actual_completed_at", sa.DateTime(timezone=True)))
    op.add_column("tickets", sa.Column("cancel_reason", sa.Text()))
    op.add_column("tickets", sa.Column("last_event_id", sa.Integer()))
    op.execute(
        """
        UPDATE tickets AS ticket
        SET lifecycle_state = CASE
            WHEN ticket.status = 'in_progress' THEN 'in_progress'
            WHEN ticket.status = 'completed' THEN 'completed'
            WHEN ticket.status = 'wont_fix' THEN 'cancelled'
            WHEN EXISTS (
                SELECT 1
                FROM ticket_assignments AS assignment
                WHERE assignment.ticket_id = ticket.id
            ) THEN 'assigned'
            ELSE 'waiting_assignment'
        END
        """
    )
    op.create_check_constraint("revision_positive", "tickets", "revision > 0")
    op.create_check_constraint("execution_cycle_positive", "tickets", "execution_cycle > 0")
    op.create_index("ix_tickets_lifecycle_state", "tickets", ["lifecycle_state"])
    op.create_index("ix_tickets_last_event_id", "tickets", ["last_event_id"])

    event_type = sa.Enum(
        *EVENT_TYPES,
        name="work_event_type",
        native_enum=False,
        create_constraint=True,
    )
    op.create_table(
        "work_events",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("event_type", event_type, nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=True),
        sa.Column("worker_id", sa.Integer(), nullable=True),
        sa.Column("district_id", sa.Integer(), nullable=True),
        sa.Column("route_date", sa.Date(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("previous_state", sa.String(length=32), nullable=True),
        sa.Column("new_state", sa.String(length=32), nullable=True),
        sa.Column("before_revision", sa.Integer(), nullable=True),
        sa.Column("after_revision", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name="fk_work_events_ticket_id_tickets",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["workers.user_id"],
            name="fk_work_events_worker_id_workers",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["district_id"],
            ["districts.id"],
            name="fk_work_events_district_id_districts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_work_events_actor_id_users", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_work_events"),
    )
    op.create_index("ix_work_events_ticket_id", "work_events", ["ticket_id"])
    op.create_index("ix_work_events_worker_id", "work_events", ["worker_id"])
    op.create_index("ix_work_events_district_id", "work_events", ["district_id"])
    op.create_index("ix_work_events_actor_id", "work_events", ["actor_id"])
    op.create_index(
        "ix_work_events_worker_day",
        "work_events",
        ["worker_id", "district_id", "route_date", "occurred_at"],
    )
    op.create_index(
        "uq_work_events_idempotency_key", "work_events", ["idempotency_key"], unique=True
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_work_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'work_events are append-only';
        END;
        $$;
        CREATE TRIGGER work_events_append_only
        BEFORE UPDATE OR DELETE ON work_events
        FOR EACH ROW EXECUTE FUNCTION prevent_work_event_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER work_events_append_only ON work_events")
    op.execute("DROP FUNCTION prevent_work_event_mutation()")
    op.drop_index("uq_work_events_idempotency_key", table_name="work_events")
    op.drop_index("ix_work_events_worker_day", table_name="work_events")
    op.drop_index("ix_work_events_actor_id", table_name="work_events")
    op.drop_index("ix_work_events_district_id", table_name="work_events")
    op.drop_index("ix_work_events_worker_id", table_name="work_events")
    op.drop_index("ix_work_events_ticket_id", table_name="work_events")
    op.drop_table("work_events")

    op.drop_index("ix_tickets_last_event_id", table_name="tickets")
    op.drop_index("ix_tickets_lifecycle_state", table_name="tickets")
    op.drop_constraint("ck_tickets_execution_cycle_positive", "tickets", type_="check")
    op.drop_constraint("ck_tickets_revision_positive", "tickets", type_="check")
    op.drop_column("tickets", "last_event_id")
    op.drop_column("tickets", "cancel_reason")
    op.drop_column("tickets", "actual_completed_at")
    op.drop_column("tickets", "actual_started_at")
    op.drop_column("tickets", "execution_cycle")
    op.drop_column("tickets", "revision")
    op.drop_column("tickets", "lifecycle_state")

    op.drop_index("ix_brigades_division_id", table_name="brigades")
    op.drop_constraint("fk_brigades_division_id_divisions", "brigades", type_="foreignkey")
    op.execute("DROP TRIGGER brigade_division_from_office ON brigades")
    op.execute("DROP FUNCTION set_brigade_division_from_office()")
    op.drop_column("brigades", "division_id")
    op.execute("DROP TRIGGER district_division_after_insert ON districts")
    op.execute("DROP FUNCTION ensure_district_division()")
    op.drop_index("uq_divisions_district_id", table_name="divisions")
    op.drop_table("divisions")

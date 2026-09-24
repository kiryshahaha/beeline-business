"""Persist worker availability and district-day snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_day_states",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("district_id", sa.Integer(), nullable=False),
        sa.Column("route_date", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("available", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("unavailable_at", sa.DateTime(timezone=True)),
        sa.Column("unavailable_until", sa.DateTime(timezone=True)),
        sa.Column("last_location_id", sa.Integer()),
        sa.Column("current_ticket_id", sa.Integer()),
        sa.Column("current_destination_id", sa.Integer()),
        sa.Column("en_route_started_at", sa.DateTime(timezone=True)),
        sa.Column("expected_available_at", sa.DateTime(timezone=True)),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["workers.user_id"],
            name="fk_worker_day_states_worker_id_workers",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["district_id"],
            ["districts.id"],
            name="fk_worker_day_states_district_id_districts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["last_location_id"],
            ["locations.id"],
            name="fk_worker_day_states_last_location_id_locations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["current_ticket_id"],
            ["tickets.id"],
            name="fk_worker_day_states_current_ticket_id_tickets",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["current_destination_id"],
            ["locations.id"],
            name="fk_worker_day_states_current_destination_id_locations",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_worker_day_states"),
        sa.CheckConstraint("revision > 0", name="revision_positive"),
    )
    op.create_index(
        "uq_worker_day_states_worker_district_date",
        "worker_day_states",
        ["worker_id", "district_id", "route_date"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_worker_day_states_worker_district_date", table_name="worker_day_states")
    op.drop_table("worker_day_states")

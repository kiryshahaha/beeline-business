"""Create ticket and address models.

Revision ID: 0001
Revises: none
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cities",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.CheckConstraint(
            "name = btrim(name) AND name <> ''", name=op.f("ck_cities_name_not_blank")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cities")),
    )
    op.create_index("uq_cities_name", "cities", [sa.literal_column("lower(name)")], unique=True)

    op.create_table(
        "streets",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.CheckConstraint(
            "name = btrim(name) AND name <> ''", name=op.f("ck_streets_name_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["city_id"], ["cities.id"], name=op.f("fk_streets_city_id_cities"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_streets")),
    )
    op.create_index(
        "uq_streets_city_name",
        "streets",
        ["city_id", sa.literal_column("lower(name)")],
        unique=True,
    )

    op.create_table(
        "buildings",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("street_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(30), nullable=False),
        sa.Column("block", sa.String(30), nullable=True),
        sa.CheckConstraint(
            "number = btrim(number) AND number <> ''", name=op.f("ck_buildings_number_not_blank")
        ),
        sa.CheckConstraint(
            "block IS NULL OR (block = btrim(block) AND block <> '')",
            name=op.f("ck_buildings_block_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["street_id"],
            ["streets.id"],
            name=op.f("fk_buildings_street_id_streets"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_buildings")),
    )
    op.create_index(
        "uq_buildings_street_number_block",
        "buildings",
        ["street_id", sa.literal_column("lower(number)"), sa.literal_column("lower(block)")],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )

    op.create_table(
        "entrances",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("building_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(30), nullable=False),
        sa.CheckConstraint(
            "number = btrim(number) AND number <> ''", name=op.f("ck_entrances_number_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["building_id"],
            ["buildings.id"],
            name=op.f("fk_entrances_building_id_buildings"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entrances")),
        sa.UniqueConstraint("id", "building_id", name="uq_entrances_id_building"),
    )
    op.create_index(
        "uq_entrances_building_number",
        "entrances",
        ["building_id", sa.literal_column("lower(number)")],
        unique=True,
    )

    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("building_id", sa.Integer(), nullable=False),
        sa.Column("entrance_id", sa.Integer(), nullable=True),
        sa.Column("floor", sa.Integer(), nullable=True),
        sa.Column("apartment", sa.String(30), nullable=True),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        sa.CheckConstraint(
            "apartment IS NULL OR (apartment = btrim(apartment) AND apartment <> '')",
            name=op.f("ck_locations_apartment_not_blank"),
        ),
        sa.CheckConstraint(
            "(latitude IS NULL) = (longitude IS NULL)", name=op.f("ck_locations_coordinates_pair")
        ),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name=op.f("ck_locations_latitude_range")),
        sa.CheckConstraint(
            "longitude BETWEEN -180 AND 180", name=op.f("ck_locations_longitude_range")
        ),
        sa.ForeignKeyConstraint(
            ["building_id"],
            ["buildings.id"],
            name=op.f("fk_locations_building_id_buildings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["entrance_id", "building_id"],
            ["entrances.id", "entrances.building_id"],
            name="fk_locations_entrance_building",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_locations")),
    )
    op.create_index(op.f("ix_locations_entrance_id"), "locations", ["entrance_id"])
    op.create_index(
        "uq_locations_destination",
        "locations",
        ["building_id", "entrance_id", sa.literal_column("lower(apartment)")],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )

    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("work_type", sa.String(100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "planned",
                "in_progress",
                "completed",
                "wont_fix",
                name="ticket_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="planned",
            nullable=False,
        ),
        sa.Column("visit_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("visit_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("planned_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("planned_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estimated_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("actual_duration_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "title = btrim(title) AND title <> ''", name=op.f("ck_tickets_title_not_blank")
        ),
        sa.CheckConstraint(
            "work_type = btrim(work_type) AND work_type <> ''",
            name=op.f("ck_tickets_work_type_not_blank"),
        ),
        sa.CheckConstraint(
            "(planned_start_at IS NULL) = (planned_end_at IS NULL)",
            name=op.f("ck_tickets_planned_time_pair"),
        ),
        sa.CheckConstraint(
            "actual_duration_minutes >= 0", name=op.f("ck_tickets_actual_duration_nonnegative")
        ),
        sa.CheckConstraint(
            "estimated_duration_minutes > 0", name=op.f("ck_tickets_estimated_duration_positive")
        ),
        sa.CheckConstraint(
            "planned_end_at > planned_start_at", name=op.f("ck_tickets_planned_time_order")
        ),
        sa.CheckConstraint(
            "visit_window_end > visit_window_start", name=op.f("ck_tickets_visit_window_order")
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
            name=op.f("fk_tickets_location_id_locations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tickets")),
    )
    op.create_index(op.f("ix_tickets_location_id"), "tickets", ["location_id"])
    op.create_index("ix_tickets_status_planned_start", "tickets", ["status", "planned_start_at"])
    op.create_index("ix_tickets_visit_window_start", "tickets", ["visit_window_start"])


def downgrade() -> None:
    # Drop child tables first so foreign keys remain valid throughout the rollback.
    op.drop_table("tickets")
    op.drop_table("locations")
    op.drop_table("entrances")
    op.drop_table("buildings")
    op.drop_table("streets")
    op.drop_table("cities")

"""Add service areas, home start, and stock office separation.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-24 22:30:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_areas",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_service_areas"),
        sa.CheckConstraint("code = btrim(code) AND code <> ''", name="service_area_code_not_blank"),
        sa.CheckConstraint("name = btrim(name) AND name <> ''", name="service_area_name_not_blank"),
    )
    op.create_index(
        "uq_service_areas_code",
        "service_areas",
        [sa.text("lower(code)")],
        unique=True,
    )

    op.execute(
        """
        INSERT INTO service_areas (code, name)
        SELECT 'district_' || id, name FROM districts ORDER BY id
        ON CONFLICT DO NOTHING;
        """
    )
    op.execute(
        """
        INSERT INTO service_areas (code, name)
        VALUES ('central', 'Центральный участок')
        ON CONFLICT DO NOTHING;
        """
    )

    # 2. Add service_area_id to tickets
    op.add_column("tickets", sa.Column("service_area_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE tickets AS t
        SET service_area_id = sa.id
        FROM locations AS loc
        JOIN buildings AS b ON b.id = loc.building_id
        JOIN service_areas AS sa ON sa.code = 'district_' || b.district_id
        WHERE loc.id = t.location_id AND t.service_area_id IS NULL;
        """
    )
    op.execute(
        """
        UPDATE tickets
        SET service_area_id = (SELECT id FROM service_areas ORDER BY id LIMIT 1)
        WHERE service_area_id IS NULL;
        """
    )
    op.create_foreign_key(
        "fk_tickets_service_area_id_service_areas",
        "tickets",
        "service_areas",
        ["service_area_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_tickets_service_area_id", "tickets", ["service_area_id"])

    # 3. Add columns to workers
    op.add_column("workers", sa.Column("service_area_id", sa.Integer(), nullable=True))
    op.add_column("workers", sa.Column("start_location_id", sa.Integer(), nullable=True))
    op.add_column("workers", sa.Column("stock_office_id", sa.Integer(), nullable=True))
    op.add_column("workers", sa.Column("end_location_id", sa.Integer(), nullable=True))

    op.execute(
        """
        UPDATE workers AS w
        SET service_area_id = sa.id
        FROM brigade_members AS bm
        JOIN brigades AS b ON b.id = bm.brigade_id
        JOIN offices AS off ON off.id = b.office_id
        JOIN locations AS loc ON loc.id = off.location_id
        JOIN buildings AS bld ON bld.id = loc.building_id
        JOIN service_areas AS sa ON sa.code = 'district_' || bld.district_id
        WHERE bm.worker_id = w.user_id AND w.service_area_id IS NULL;
        """
    )
    op.execute(
        """
        UPDATE workers
        SET service_area_id = (SELECT id FROM service_areas ORDER BY id LIMIT 1)
        WHERE service_area_id IS NULL;
        """
    )
    op.create_foreign_key(
        "fk_workers_service_area_id_service_areas",
        "workers",
        "service_areas",
        ["service_area_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_workers_start_location_id_locations",
        "workers",
        "locations",
        ["start_location_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_workers_stock_office_id_offices",
        "workers",
        "offices",
        ["stock_office_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_workers_end_location_id_locations",
        "workers",
        "locations",
        ["end_location_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_workers_service_area_id", "workers", ["service_area_id"])


def downgrade() -> None:
    op.drop_index("ix_workers_service_area_id", table_name="workers")
    op.drop_constraint("fk_workers_end_location_id_locations", "workers", type_="foreignkey")
    op.drop_constraint("fk_workers_stock_office_id_offices", "workers", type_="foreignkey")
    op.drop_constraint("fk_workers_start_location_id_locations", "workers", type_="foreignkey")
    op.drop_constraint("fk_workers_service_area_id_service_areas", "workers", type_="foreignkey")
    op.drop_column("workers", "end_location_id")
    op.drop_column("workers", "stock_office_id")
    op.drop_column("workers", "start_location_id")
    op.drop_column("workers", "service_area_id")

    op.drop_index("ix_tickets_service_area_id", table_name="tickets")
    op.drop_constraint("fk_tickets_service_area_id_service_areas", "tickets", type_="foreignkey")
    op.drop_column("tickets", "service_area_id")

    op.drop_index("uq_service_areas_code", table_name="service_areas")
    op.drop_table("service_areas")

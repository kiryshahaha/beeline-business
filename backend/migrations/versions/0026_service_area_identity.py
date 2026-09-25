"""Use service area IDs for divisions, addresses, execution, and day plans."""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Districts created after migration 0021 did not get a matching service area.
    # Materialize those mappings before moving any foreign keys.
    op.execute(
        """
        INSERT INTO service_areas (code, name)
        SELECT 'district_' || id, name
        FROM districts
        ORDER BY id
        ON CONFLICT DO NOTHING
        """
    )

    op.drop_constraint("fk_buildings_district_city", "buildings", type_="foreignkey")
    op.drop_index("ix_buildings_district_id", table_name="buildings")
    op.drop_constraint("fk_divisions_district_id_districts", "divisions", type_="foreignkey")
    op.drop_index("uq_divisions_district_id", table_name="divisions")
    op.drop_constraint("fk_work_events_district_id_districts", "work_events", type_="foreignkey")
    op.drop_index("ix_work_events_district_id", table_name="work_events")
    op.drop_constraint(
        "fk_worker_day_states_district_id_districts",
        "worker_day_states",
        type_="foreignkey",
    )
    op.drop_index("uq_worker_day_states_worker_district_date", table_name="worker_day_states")

    # The audit log forbids ordinary updates; suspend its guard only for this key migration.
    op.execute("ALTER TABLE work_events DISABLE TRIGGER work_events_append_only")
    for table in ("buildings", "divisions", "work_events", "worker_day_states"):
        op.execute(
            f"""
            UPDATE {table} AS record
            SET district_id = area.id
            FROM service_areas AS area
            WHERE area.code = 'district_' || record.district_id
            """
        )
    op.execute("ALTER TABLE work_events ENABLE TRIGGER work_events_append_only")

    op.execute("DROP TRIGGER district_division_after_insert ON districts")
    op.execute("DROP FUNCTION ensure_district_division()")

    op.alter_column("buildings", "district_id", new_column_name="service_area_id")
    op.create_foreign_key(
        "fk_buildings_service_area_id_service_areas",
        "buildings",
        "service_areas",
        ["service_area_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_buildings_service_area_id", "buildings", ["service_area_id"])

    op.alter_column("divisions", "district_id", new_column_name="service_area_id")
    op.create_foreign_key(
        "fk_divisions_service_area_id_service_areas",
        "divisions",
        "service_areas",
        ["service_area_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("uq_divisions_service_area_id", "divisions", ["service_area_id"], unique=True)

    op.alter_column("work_events", "district_id", new_column_name="service_area_id")
    op.create_foreign_key(
        "fk_work_events_service_area_id_service_areas",
        "work_events",
        "service_areas",
        ["service_area_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_work_events_service_area_id", "work_events", ["service_area_id"])

    op.alter_column("worker_day_states", "district_id", new_column_name="service_area_id")
    op.create_foreign_key(
        "fk_worker_day_states_service_area_id_service_areas",
        "worker_day_states",
        "service_areas",
        ["service_area_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_worker_day_states_worker_service_area_date",
        "worker_day_states",
        ["worker_id", "service_area_id", "route_date"],
        unique=True,
    )

    # 0025 added the canonical service area identity; the district is now redundant.
    op.drop_constraint(
        "fk_day_plan_revisions_district_id_districts",
        "day_plan_revisions",
        type_="foreignkey",
    )
    op.drop_column("day_plan_revisions", "district_id")

    op.execute(
        """
        INSERT INTO divisions (service_area_id)
        SELECT area.id
        FROM service_areas AS area
        WHERE EXISTS (
            SELECT 1 FROM districts AS district
            WHERE area.code = 'district_' || district.id
        )
          AND NOT EXISTS (
              SELECT 1 FROM divisions AS existing
              WHERE existing.service_area_id = area.id
          )
        ORDER BY area.id
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ensure_district_service_area()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            INSERT INTO service_areas (code, name)
            VALUES ('district_' || NEW.id, NEW.name)
            ON CONFLICT DO NOTHING;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER district_service_area_after_insert
        AFTER INSERT ON districts
        FOR EACH ROW EXECUTE FUNCTION ensure_district_service_area();

        CREATE OR REPLACE FUNCTION ensure_service_area_division()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM districts AS district
                WHERE NEW.code = 'district_' || district.id
            ) THEN
                INSERT INTO divisions (service_area_id)
                VALUES (NEW.id)
                ON CONFLICT (service_area_id) DO NOTHING;
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER service_area_division_after_insert
        AFTER INSERT ON service_areas
        FOR EACH ROW EXECUTE FUNCTION ensure_service_area_division();

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
            JOIN divisions AS div ON div.service_area_id = building.service_area_id
            WHERE office.id = NEW.office_id;

            IF NEW.division_id IS NULL THEN
                RAISE EXCEPTION 'Brigade office must belong to a service area';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )


def downgrade() -> None:
    # Restoring district columns requires a canonical district mapping for every
    # stored service area reference. Refuse to lose references for custom areas.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM (
                    SELECT service_area_id FROM buildings
                    UNION ALL SELECT service_area_id FROM divisions
                    UNION ALL SELECT service_area_id FROM work_events
                    UNION ALL SELECT service_area_id FROM worker_day_states
                ) AS refs
                JOIN service_areas AS area ON area.id = refs.service_area_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM districts AS district
                    WHERE area.code = 'district_' || district.id
                )
            ) THEN
                RAISE EXCEPTION 'Cannot restore district IDs without a mapping';
            END IF;
        END $$;
        """
    )
    op.execute("DROP TRIGGER service_area_division_after_insert ON service_areas")
    op.execute("DROP FUNCTION ensure_service_area_division()")
    op.execute("DROP TRIGGER district_service_area_after_insert ON districts")
    op.execute("DROP FUNCTION ensure_district_service_area()")

    op.drop_constraint(
        "fk_buildings_service_area_id_service_areas", "buildings", type_="foreignkey"
    )
    op.drop_index("ix_buildings_service_area_id", table_name="buildings")
    op.drop_constraint(
        "fk_divisions_service_area_id_service_areas", "divisions", type_="foreignkey"
    )
    op.drop_index("uq_divisions_service_area_id", table_name="divisions")
    op.drop_constraint(
        "fk_work_events_service_area_id_service_areas", "work_events", type_="foreignkey"
    )
    op.drop_index("ix_work_events_service_area_id", table_name="work_events")
    op.drop_constraint(
        "fk_worker_day_states_service_area_id_service_areas",
        "worker_day_states",
        type_="foreignkey",
    )
    op.drop_index("uq_worker_day_states_worker_service_area_date", table_name="worker_day_states")

    op.execute("ALTER TABLE work_events DISABLE TRIGGER work_events_append_only")
    for table in ("buildings", "divisions", "work_events", "worker_day_states"):
        op.execute(
            f"""
            UPDATE {table} AS record
            SET service_area_id = district.id
            FROM service_areas AS area
            JOIN districts AS district ON area.code = 'district_' || district.id
            WHERE area.id = record.service_area_id
            """
        )
    op.execute("ALTER TABLE work_events ENABLE TRIGGER work_events_append_only")

    op.alter_column("buildings", "service_area_id", new_column_name="district_id")
    op.create_foreign_key(
        "fk_buildings_district_city",
        "buildings",
        "districts",
        ["district_id", "city_id"],
        ["id", "city_id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_buildings_district_id", "buildings", ["district_id"])

    op.alter_column("divisions", "service_area_id", new_column_name="district_id")
    op.create_foreign_key(
        "fk_divisions_district_id_districts",
        "divisions",
        "districts",
        ["district_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("uq_divisions_district_id", "divisions", ["district_id"], unique=True)

    op.alter_column("work_events", "service_area_id", new_column_name="district_id")
    op.create_foreign_key(
        "fk_work_events_district_id_districts",
        "work_events",
        "districts",
        ["district_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_work_events_district_id", "work_events", ["district_id"])

    op.alter_column("worker_day_states", "service_area_id", new_column_name="district_id")
    op.create_foreign_key(
        "fk_worker_day_states_district_id_districts",
        "worker_day_states",
        "districts",
        ["district_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_worker_day_states_worker_district_date",
        "worker_day_states",
        ["worker_id", "district_id", "route_date"],
        unique=True,
    )

    # 0025 retained service_area_id and made district_id nullable for migrated history.
    # Restore that legacy field alongside the existing service-area identity.
    op.add_column("day_plan_revisions", sa.Column("district_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE day_plan_revisions AS revision_row
        SET district_id = district.id
        FROM service_areas AS area
        JOIN districts AS district ON area.code = 'district_' || district.id
        WHERE area.id = revision_row.service_area_id
        """
    )
    op.create_foreign_key(
        "fk_day_plan_revisions_district_id_districts",
        "day_plan_revisions",
        "districts",
        ["district_id"],
        ["id"],
        ondelete="RESTRICT",
    )

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

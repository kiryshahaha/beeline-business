"""Model-level contracts for the district-to-service-area identifier change."""

import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.modules.buildings.models import Building
from app.modules.execution.day_models import WorkerDayState
from app.modules.execution.models import Division, WorkEvent
from app.modules.planning.day_models import DayPlanRevision
from tests.support import DatabaseTestCase


class ServiceAreaIdModelTests(unittest.TestCase):
    def test_persisted_area_references_point_to_service_areas(self):
        for model in (Building, Division, WorkEvent, WorkerDayState):
            with self.subTest(model=model.__name__):
                self.assertIn("service_area_id", model.__table__.c)
                self.assertNotIn("district_id", model.__table__.c)
                foreign_keys = model.__table__.c.service_area_id.foreign_keys
                self.assertEqual(
                    {foreign_key.target_fullname for foreign_key in foreign_keys},
                    {"service_areas.id"},
                )

    def test_day_plan_revision_keeps_one_area_identity(self):
        self.assertIn("service_area_id", DayPlanRevision.__table__.c)
        self.assertNotIn("district_id", DayPlanRevision.__table__.c)


class ServiceAreaIdMigrationTests(DatabaseTestCase):
    def migration_config(self):
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.attributes["connection"] = self.connection
        return config

    def test_upgrade_maps_existing_district_references_to_areas(self):
        config = self.migration_config()
        command.downgrade(config, "0025")

        # This earlier area makes its ID differ from the district ID.
        self.connection.execute(
            text("INSERT INTO service_areas (code, name) VALUES ('unrelated', 'Другой участок')")
        )
        city_id = self.connection.execute(
            text("INSERT INTO cities (name) VALUES ('Тестовый город') RETURNING id")
        ).scalar_one()
        street_id = self.connection.execute(
            text(
                "INSERT INTO streets (city_id, name) "
                "VALUES (:city_id, 'Тестовая улица') RETURNING id"
            ),
            {"city_id": city_id},
        ).scalar_one()
        district_id = self.connection.execute(
            text(
                "INSERT INTO districts (city_id, name) "
                "VALUES (:city_id, 'Тестовый район') RETURNING id"
            ),
            {"city_id": city_id},
        ).scalar_one()
        building_id = self.connection.execute(
            text("""
                INSERT INTO buildings (city_id, street_id, district_id, number)
                VALUES (:city_id, :street_id, :district_id, '1') RETURNING id
            """),
            {"city_id": city_id, "street_id": street_id, "district_id": district_id},
        ).scalar_one()
        worker_id = self.connection.execute(
            text("""
                INSERT INTO users (name, surname, username, password_hash, role)
                VALUES ('Работник', 'Тестов', 'area-migration-worker', 'hash', 'worker')
                RETURNING id
            """)
        ).scalar_one()
        self.connection.execute(
            text(
                "INSERT INTO workers (user_id, workshift_start, workshift_end) "
                "VALUES (:id, '09:00', '18:00')"
            ),
            {"id": worker_id},
        )
        event_id = self.connection.execute(
            text(
                "INSERT INTO work_events "
                "(event_type, district_id, occurred_at, idempotency_key) "
                "VALUES ('new_ticket', :district_id, '2026-09-25T09:00:00+03:00', "
                "'area-migration-event') RETURNING id"
            ),
            {"district_id": district_id},
        ).scalar_one()
        state_id = self.connection.execute(
            text("""
                INSERT INTO worker_day_states (worker_id, district_id, route_date)
                VALUES (:worker_id, :district_id, '2026-09-25') RETURNING id
            """),
            {"worker_id": worker_id, "district_id": district_id},
        ).scalar_one()

        command.upgrade(config, "head")

        area_id = self.connection.execute(
            text("SELECT id FROM service_areas WHERE code = :code"),
            {"code": f"district_{district_id}"},
        ).scalar_one()
        self.assertNotEqual(area_id, district_id)

        custom_area_id = self.connection.execute(
            text(
                "INSERT INTO service_areas (code, name) VALUES ('districtish', 'Зона') RETURNING id"
            )
        ).scalar_one()
        self.assertEqual(
            self.connection.execute(
                text("SELECT count(*) FROM divisions WHERE service_area_id = :id"),
                {"id": custom_area_id},
            ).scalar_one(),
            0,
        )

        new_district_id = self.connection.execute(
            text(
                "INSERT INTO districts (city_id, name) "
                "VALUES (:city_id, 'Новый район') RETURNING id"
            ),
            {"city_id": city_id},
        ).scalar_one()
        new_area_id = self.connection.execute(
            text("SELECT id FROM service_areas WHERE code = :code"),
            {"code": f"district_{new_district_id}"},
        ).scalar_one()
        self.assertEqual(
            self.connection.execute(
                text("SELECT count(*) FROM divisions WHERE service_area_id = :id"),
                {"id": new_area_id},
            ).scalar_one(),
            1,
        )

        for table, row_id in (
            ("buildings", building_id),
            ("divisions", district_id),
            ("work_events", event_id),
            ("worker_day_states", state_id),
        ):
            actual = self.connection.execute(
                text(f"SELECT service_area_id FROM {table} WHERE id = :id"), {"id": row_id}
            ).scalar_one()
            self.assertEqual(actual, area_id, table)

        for table in (
            "buildings",
            "divisions",
            "work_events",
            "worker_day_states",
            "day_plan_revisions",
        ):
            columns = {column["name"] for column in inspect(self.connection).get_columns(table)}
            self.assertIn("service_area_id", columns, table)
            self.assertNotIn("district_id", columns, table)

        command.downgrade(config, "0025")
        for table, row_id in (
            ("buildings", building_id),
            ("divisions", district_id),
            ("work_events", event_id),
            ("worker_day_states", state_id),
        ):
            actual = self.connection.execute(
                text(f"SELECT district_id FROM {table} WHERE id = :id"), {"id": row_id}
            ).scalar_one()
            self.assertEqual(actual, district_id, table)

        revision_columns = {
            column["name"] for column in inspect(self.connection).get_columns("day_plan_revisions")
        }
        self.assertIn("district_id", revision_columns)
        self.assertIn("service_area_id", revision_columns)
        append_only_enabled = self.connection.execute(
            text(
                "SELECT tgenabled FROM pg_trigger "
                "WHERE tgname = 'work_events_append_only' "
                "AND tgrelid = 'work_events'::regclass"
            )
        ).scalar_one()
        self.assertEqual(append_only_enabled, "O")

    def test_building_rejects_an_unknown_service_area(self):
        city_id = self.connection.execute(
            text("INSERT INTO cities (name) VALUES ('Другой город') RETURNING id")
        ).scalar_one()
        street_id = self.connection.execute(
            text(
                "INSERT INTO streets (city_id, name) VALUES (:city_id, 'Другая улица') RETURNING id"
            ),
            {"city_id": city_id},
        ).scalar_one()

        with self.assertRaises(IntegrityError):
            with self.connection.begin_nested():
                self.connection.execute(
                    text("""
                        INSERT INTO buildings (city_id, street_id, service_area_id, number)
                        VALUES (:city_id, :street_id, 2147483647, '1')
                    """),
                    {"city_id": city_id, "street_id": street_id},
                )

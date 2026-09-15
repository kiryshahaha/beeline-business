"""The fresh-database district migration must not guess districts for existing buildings."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.support import DatabaseTestCase


class DistrictMigrationTests(DatabaseTestCase):
    def test_upgrade_rejects_old_buildings_without_district_and_preserves_records(self):
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.attributes["connection"] = self.connection
        command.downgrade(config, "0001")
        statements = (
            "INSERT INTO cities (id, name) VALUES (10, 'Тестовый город')",
            "INSERT INTO streets (id, city_id, name) VALUES (20, 10, 'Тестовая улица')",
            "INSERT INTO buildings (id, street_id, number, block) VALUES (30, 20, '1', 'корпус 2')",
            "INSERT INTO entrances (id, building_id, number) VALUES (40, 30, '1')",
            """
            INSERT INTO locations (
                id, building_id, entrance_id, floor, apartment, latitude, longitude
            )
            VALUES (50, 30, 40, 3, '12', 59.9156, 30.4631)
            """,
            """
            INSERT INTO tickets (
                id, location_id, title, work_type, visit_window_start, visit_window_end,
                estimated_duration_minutes, actual_duration_minutes, status
            ) VALUES (
                60, 50, 'Существующая заявка', 'Настройка сети',
                '2026-09-14T10:00:00+03:00', '2026-09-14T14:00:00+03:00', 60, 75, 'completed'
            )
            """,
        )
        for statement in statements:
            self.connection.execute(text(statement))
        # Whole-row snapshots include timestamps and manually entered values.
        tables = ("cities", "streets", "entrances", "locations", "tickets")
        original = {
            table: self.connection.execute(text(f"SELECT * FROM {table}")).all() for table in tables
        }
        original_building = self.connection.execute(text("SELECT * FROM buildings")).one()
        with self.assertRaises(IntegrityError) as raised:
            with self.connection.begin_nested():
                command.upgrade(config, "head")
        self.assertEqual(raised.exception.orig.sqlstate, "23502")
        self.assertEqual(
            self.connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(),
            "0001",
        )
        self.assertEqual(
            self.connection.execute(text("SELECT * FROM buildings")).one(), original_building
        )
        for table in tables:
            self.assertEqual(
                self.connection.execute(text(f"SELECT * FROM {table}")).all(), original[table]
            )

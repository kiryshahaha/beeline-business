"""Ticket brigade column, foreign key, and migration backfill behavior."""

import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.modules.tickets.models import Ticket
from tests.support import DatabaseTestCase


class TicketBrigadeModelTests(unittest.TestCase):
    def test_brigade_reference_is_nullable_and_points_to_brigades(self):
        column = Ticket.__table__.c.brigade_id

        self.assertTrue(column.nullable)
        self.assertEqual(
            {foreign_key.target_fullname for foreign_key in column.foreign_keys},
            {"brigades.id"},
        )


class TicketBrigadeMigrationTests(DatabaseTestCase):
    def test_upgrade_backfills_unique_and_worker_known_brigades_only(self):
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.attributes["connection"] = self.connection
        command.downgrade(config, "0029")

        def make_area(suffix):
            city_id = self.connection.execute(
                text("INSERT INTO cities (name) VALUES (:name) RETURNING id"),
                {"name": f"Город {suffix}"},
            ).scalar_one()
            street_id = self.connection.execute(
                text("INSERT INTO streets (city_id, name) VALUES (:city_id, :name) RETURNING id"),
                {"city_id": city_id, "name": f"Улица {suffix}"},
            ).scalar_one()
            district_id = self.connection.execute(
                text("INSERT INTO districts (city_id, name) VALUES (:city_id, :name) RETURNING id"),
                {"city_id": city_id, "name": f"Район {suffix}"},
            ).scalar_one()
            area_id = self.service_area_for_district(district_id)
            building_id = self.connection.execute(
                text("""
                    INSERT INTO buildings (city_id, street_id, service_area_id, number)
                    VALUES (:city_id, :street_id, :area_id, '1') RETURNING id
                """),
                {"city_id": city_id, "street_id": street_id, "area_id": area_id},
            ).scalar_one()
            location_id = self.connection.execute(
                text("INSERT INTO locations (building_id) VALUES (:id) RETURNING id"),
                {"id": building_id},
            ).scalar_one()
            office_id = self.connection.execute(
                text("INSERT INTO offices (name, location_id) VALUES (:name, :id) RETURNING id"),
                {"name": f"Офис {suffix}", "id": location_id},
            ).scalar_one()
            return area_id, location_id, office_id

        def make_user(username, role):
            return self.connection.execute(
                text("""
                    INSERT INTO users (name, surname, username, password_hash, role)
                    VALUES (:username, 'Миграция', :username, 'test-hash', :role)
                    RETURNING id
                """),
                {"username": username, "role": role},
            ).scalar_one()

        def make_brigade(name, office_id):
            foreman_id = make_user(f"foreman_{name}", "foreman")
            return self.connection.execute(
                text("""
                    INSERT INTO brigades (name, foreman_id, office_id)
                    VALUES (:name, :foreman_id, :office_id) RETURNING id
                """),
                {"name": name, "foreman_id": foreman_id, "office_id": office_id},
            ).scalar_one()

        def make_ticket(location_id, *, service_area_id=None, worker_id=None, title):
            return self.connection.execute(
                text("""
                    INSERT INTO tickets (
                        location_id, service_area_id, assigned_worker_id, title,
                        visit_window_start, visit_window_end, estimated_duration_minutes
                    ) VALUES (
                        :location_id, :service_area_id, :worker_id, :title,
                        '2026-09-27T10:00:00+03:00', '2026-09-27T12:00:00+03:00', 60
                    ) RETURNING id
                """),
                {
                    "location_id": location_id,
                    "service_area_id": service_area_id,
                    "worker_id": worker_id,
                    "title": title,
                },
            ).scalar_one()

        unique_area, unique_location, unique_office = make_area("Единый")
        first_brigade = make_brigade("unique", unique_office)
        worker_id = make_user("unique_worker", "worker")
        self.connection.execute(
            text(
                "INSERT INTO workers (user_id, workshift_start, workshift_end) "
                "VALUES (:id, '09:00', '18:00')"
            ),
            {"id": worker_id},
        )
        self.connection.execute(
            text("INSERT INTO brigade_members (brigade_id, worker_id) VALUES (:b, :w)"),
            {"b": first_brigade, "w": worker_id},
        )
        assigned_ticket = make_ticket(
            unique_location, worker_id=worker_id, title="Исполнитель известен"
        )
        unique_ticket = make_ticket(unique_location, title="Одна бригада в районе")

        ambiguous_area, ambiguous_location, ambiguous_office = make_area("Неоднозначный")
        make_brigade("ambiguous_one", ambiguous_office)
        make_brigade("ambiguous_two", ambiguous_office)
        ambiguous_ticket = make_ticket(
            ambiguous_location,
            service_area_id=ambiguous_area,
            title="Несколько бригад в районе",
        )

        command.upgrade(config, "head")

        actual = dict(
            self.connection.execute(text("SELECT id, brigade_id FROM tickets ORDER BY id")).all()
        )
        self.assertEqual(actual[assigned_ticket], first_brigade)
        self.assertEqual(actual[unique_ticket], first_brigade)
        self.assertIsNone(actual[ambiguous_ticket])

        foreign_keys = inspect(self.connection).get_foreign_keys("tickets")
        brigade_fk = next(
            item for item in foreign_keys if item["constrained_columns"] == ["brigade_id"]
        )
        self.assertEqual(brigade_fk["options"]["ondelete"], "SET NULL")


if __name__ == "__main__":
    unittest.main()

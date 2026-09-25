"""Integration tests use migrations and a unique schema in a dedicated test database."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.db.models import Building, City, District, Entrance, Location, Street, Ticket
from app.modules.tickets.enums import TicketStatus
from tests.support import DatabaseTestCase


class DatabaseTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()

        self.city = self.save(City(name="Санкт-Петербург"))
        self.district = self.save(District(city_id=self.city.id, name="Невский район"))
        self.street = self.save(Street(city_id=self.city.id, name="улица Ленина"))
        self.building = self.save(
            Building(
                city_id=self.city.id,
                district_id=self.district.id,
                street_id=self.street.id,
                number="12А",
            )
        )
        self.entrance = self.save(Entrance(building_id=self.building.id, number="1"))
        self.location = self.save(
            Location(
                building_id=self.building.id,
                entrance_id=self.entrance.id,
                apartment="24Б",
                floor=5,
                latitude=Decimal("59.940000"),
                longitude=Decimal("30.320000"),
            )
        )
        self.window_start = datetime(2026, 9, 12, 10, tzinfo=timezone(timedelta(hours=3)))

    def save(self, model):
        self.session.add(model)
        self.session.flush()
        return model

    def ticket(self, **overrides):
        values = {
            "location_id": self.location.id,
            "title": "Настроить Wi-Fi",
            "work_type_id": 1,
            "visit_window_start": self.window_start,
            "visit_window_end": self.window_start + timedelta(hours=4),
            "estimated_duration_minutes": 60,
        }
        return Ticket(**(values | overrides))

    def rejected(self, model):
        with self.assertRaises(IntegrityError):
            with self.session.begin_nested():
                self.save(model)

    def test_two_tickets_share_apartment_and_keep_manual_duration(self):
        first = self.save(
            self.ticket(
                planned_start_at=self.window_start + timedelta(hours=1),
                planned_end_at=self.window_start + timedelta(hours=2),
                actual_duration_minutes=75,
            )
        )
        second = self.save(self.ticket(title="Проверить соединение"))
        self.session.expire_all()
        self.assertEqual(first.location_id, second.location_id)
        self.assertEqual(first.actual_duration_minutes, 75)
        self.assertEqual(second.status, TicketStatus.PLANNED)
        self.assertIsNone(second.actual_duration_minutes)
        self.assertIsNone(second.planned_start_at)
        self.assertEqual(first.visit_window_start, self.window_start)
        self.assertIsNotNone(first.created_at.tzinfo)

    def test_city_duplicate_is_case_insensitive_in_cyrillic(self):
        self.rejected(City(name="санкт-петербург"))

    def test_street_duplicate_is_scoped_to_city(self):
        self.rejected(Street(city_id=self.city.id, name="УЛИЦА ЛЕНИНА"))
        other_city = self.save(City(name="Москва"))
        other_street = self.save(Street(city_id=other_city.id, name="улица Ленина"))
        self.assertNotEqual(other_street.id, self.street.id)

    def test_district_duplicate_is_case_insensitive_and_scoped_to_city(self):
        district = self.district
        self.rejected(District(city_id=self.city.id, name="НЕВСКИЙ РАЙОН"))
        other_city = self.save(City(name="Другой город"))
        other = self.save(District(city_id=other_city.id, name="Невский район"))
        self.assertNotEqual(district.id, other.id)
        for name in ("", " ", " Район", "Район "):
            with self.subTest(name=name):
                self.rejected(District(city_id=self.city.id, name=name))

    def test_building_rejects_district_or_street_from_another_city(self):
        other_city = self.save(City(name="Другой город"))
        district = self.save(District(city_id=other_city.id, name="Центральный район"))
        other_street = self.save(Street(city_id=other_city.id, name="улица Ленина"))
        for values in (
            {"street_id": self.street.id, "district_id": district.id},
            {"street_id": other_street.id, "district_id": self.district.id},
        ):
            with self.subTest(values=values):
                self.rejected(Building(city_id=self.city.id, number="100", **values))
        # Updating an existing row through literal SQL must enforce the same rule.
        with self.assertRaises(IntegrityError):
            with self.session.begin_nested():
                self.session.execute(
                    text("UPDATE buildings SET district_id = :district_id WHERE id = :id"),
                    {"district_id": district.id, "id": self.building.id},
                )

    def test_one_street_can_have_buildings_in_different_districts(self):
        first = self.save(District(city_id=self.city.id, name="Первый район"))
        second = self.save(District(city_id=self.city.id, name="Второй район"))
        self.building.district_id = first.id
        other = self.save(
            Building(
                city_id=self.city.id, street_id=self.street.id, district_id=second.id, number="14"
            )
        )
        self.assertEqual(other.street_id, self.building.street_id)
        self.assertNotEqual(other.district_id, self.building.district_id)
        other_city = self.save(City(name="Другой город"))
        for query in (
            "DELETE FROM districts WHERE id = :id",
            "UPDATE districts SET city_id = :city_id WHERE id = :id",
        ):
            with self.subTest(query=query):
                with self.assertRaises(IntegrityError):
                    with self.session.begin_nested():
                        self.session.execute(
                            text(query), {"id": first.id, "city_id": other_city.id}
                        )

    def test_building_without_block_cannot_be_duplicated(self):
        self.rejected(
            Building(
                city_id=self.city.id,
                district_id=self.district.id,
                street_id=self.street.id,
                number="12а",
            )
        )

    def test_building_district_cannot_be_omitted_null_or_cleared(self):
        statements = (
            """
            INSERT INTO buildings (city_id, street_id, number)
            VALUES (:city_id, :street_id, '100')
            """,
            """
            INSERT INTO buildings (city_id, street_id, district_id, number)
            VALUES (:city_id, :street_id, NULL, '100')
            """,
            "UPDATE buildings SET district_id = NULL WHERE id = :id",
        )
        for statement in statements:
            with self.subTest(statement=statement):
                with self.assertRaises(IntegrityError) as raised:
                    with self.session.begin_nested():
                        self.session.execute(
                            text(statement),
                            {
                                "city_id": self.city.id,
                                "street_id": self.street.id,
                                "id": self.building.id,
                            },
                        )
                self.assertEqual(raised.exception.orig.sqlstate, "23502")
                self.assertEqual(raised.exception.orig.diag.column_name, "district_id")
        self.session.refresh(self.building)
        self.assertEqual(self.building.district_id, self.district.id)

    def test_buildings_with_different_blocks_are_distinct(self):
        other_building = self.save(
            Building(
                city_id=self.city.id,
                district_id=self.district.id,
                street_id=self.street.id,
                number="12А",
                block="корпус 2",
            )
        )
        self.assertNotEqual(other_building.id, self.building.id)

    def test_entrance_duplicate_is_scoped_to_building(self):
        self.rejected(Entrance(building_id=self.building.id, number="1"))
        other_building = self.save(
            Building(
                city_id=self.city.id,
                district_id=self.district.id,
                street_id=self.street.id,
                number="14",
            )
        )
        other_entrance = self.save(Entrance(building_id=other_building.id, number="1"))
        self.assertNotEqual(other_entrance.id, self.entrance.id)

    def test_apartment_duplicate_cannot_be_disguised_by_floor(self):
        self.rejected(
            Location(
                building_id=self.building.id, entrance_id=self.entrance.id, apartment="24б", floor=7
            )
        )

    def test_location_with_unspecified_entrance_and_apartment_is_unique(self):
        self.save(Location(building_id=self.building.id))
        self.rejected(Location(building_id=self.building.id))

    def test_entrance_from_another_building_is_rejected(self):
        other_building = self.save(
            Building(
                city_id=self.city.id,
                district_id=self.district.id,
                street_id=self.street.id,
                number="14",
            )
        )
        self.rejected(Location(building_id=other_building.id, entrance_id=self.entrance.id))

    def test_invalid_coordinate_pairs_are_rejected(self):
        invalid_pairs = [(60, None), (None, 30), (91, 30), (60, 181), (-91, 0), (0, -181)]
        for latitude, longitude in invalid_pairs:
            with self.subTest(latitude=latitude, longitude=longitude):
                self.rejected(
                    Location(building_id=self.building.id, latitude=latitude, longitude=longitude)
                )

    def test_coordinate_boundaries_and_missing_coordinates_are_allowed(self):
        self.save(
            Location(building_id=self.building.id, apartment="1", latitude=-90, longitude=180)
        )
        self.save(
            Location(building_id=self.building.id, apartment="2", latitude=90, longitude=-180)
        )
        self.save(Location(building_id=self.building.id, apartment="3"))

    def test_invalid_intervals_and_durations_are_rejected(self):
        invalid_values = [
            {"visit_window_end": self.window_start},
            {"planned_start_at": self.window_start},
            {"planned_end_at": self.window_start},
            {"planned_start_at": self.window_start, "planned_end_at": self.window_start},
            {"estimated_duration_minutes": 0},
            {"estimated_duration_minutes": -1},
            {"actual_duration_minutes": -1},
        ]
        for values in invalid_values:
            with self.subTest(values=values):
                self.rejected(self.ticket(**values))

    def test_zero_manual_duration_is_distinct_from_missing(self):
        ticket = self.save(self.ticket(actual_duration_minutes=0))
        self.session.refresh(ticket)
        self.assertEqual(ticket.actual_duration_minutes, 0)

    def test_status_is_checked_by_database(self):
        self.rejected(self.ticket(status="unknown"))
        for status in TicketStatus:
            with self.subTest(status=status):
                ticket = self.save(self.ticket(status=status))
                self.session.refresh(ticket)
                self.assertEqual(ticket.status, status)

    def test_blank_directory_names_and_ticket_titles_are_rejected(self):
        for name in ["", " ", " Москва", "Москва "]:
            with self.subTest(name=name):
                self.rejected(City(name=name))
        self.rejected(self.ticket(title=" "))

    def test_referenced_location_cannot_be_deleted(self):
        self.save(self.ticket())
        with self.assertRaises(IntegrityError):
            with self.session.begin_nested():
                self.session.execute(delete(Location).where(Location.id == self.location.id))

    def test_report_groups_tickets_by_city_through_directory(self):
        self.save(self.ticket())
        self.save(self.ticket())
        other_city = self.save(City(name="Москва"))
        other_street = self.save(Street(city_id=other_city.id, name="улица Ленина"))
        other_district = self.save(District(city_id=other_city.id, name="Тестовый район"))
        other_building = self.save(
            Building(
                city_id=other_city.id,
                district_id=other_district.id,
                street_id=other_street.id,
                number="12А",
            )
        )
        other_location = self.save(Location(building_id=other_building.id, apartment="24Б"))
        self.save(self.ticket(location_id=other_location.id, status=TicketStatus.COMPLETED))
        report = self.session.execute(
            select(City.id, Ticket.status, func.count(Ticket.id))
            .select_from(Ticket)
            .join(Location, Location.id == Ticket.location_id)
            .join(Building, Building.id == Location.building_id)
            .join(Street, Street.id == Building.street_id)
            .join(City, City.id == Street.city_id)
            .group_by(City.id, Ticket.status)
        ).all()
        self.assertCountEqual(
            report,
            [
                (self.city.id, TicketStatus.PLANNED, 2),
                (other_city.id, TicketStatus.COMPLETED, 1),
            ],
        )

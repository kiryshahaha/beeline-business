"""Demo data is repeatable, preserves existing records and needs no geocoding network call."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import func, select

from app.db.models import (
    Brigade,
    BrigadeMember,
    Building,
    City,
    District,
    Entrance,
    Location,
    ServiceArea,
    Street,
    Ticket,
    TicketComment,
    User,
    Worker,
)
from app.modules.tickets.enums import TicketStatus
from app.modules.tickets.service import get_ticket_unscoped
from seed_demo import DEMO_OFFICES, DEMO_USERS, DEMO_VISITS, MOSCOW_TIME, seed_data
from synthetic_moscow.geography import buildings_by_district
from tests.support import DatabaseTestCase


def expected_counts(visits=DEMO_VISITS, extra_locations=0, extra_tickets=0):
    """Cities, streets, buildings, entrances, locations and tickets of a demo set."""

    def house(street, number, block):
        return (street.lower(), number.lower(), (block or "").lower())

    streets = {v.street.lower() for v in visits} | {o.street.lower() for o in DEMO_OFFICES}
    buildings = {house(v.street, v.building, v.block) for v in visits}
    office_buildings = {house(o.street, o.building, o.block) for o in DEMO_OFFICES}
    entrances = {
        (house(v.street, v.building, v.block), v.entrance.lower())
        for v in visits
        if v.entrance is not None
    }
    locations = {
        (house(v.street, v.building, v.block), v.entrance, v.apartment) for v in visits
    } | {(building, None, None) for building in office_buildings}
    tickets = {
        (house(v.street, v.building, v.block), v.entrance, v.apartment, v.title) for v in visits
    }
    return [
        1,
        len(streets),
        len(buildings | office_buildings),
        len(entrances),
        len(locations) + extra_locations,
        len(tickets) + extra_tickets,
    ]


class SeedDemoTests(DatabaseTestCase):
    visit_date = date(2026, 9, 14)

    def counts(self):
        return [
            self.session.scalar(select(func.count()).select_from(model))
            for model in (City, Street, Building, Entrance, Location, Ticket)
        ]

    def test_demo_set_is_three_areas_of_real_moscow_houses(self):
        self.assertEqual({v.district for v in DEMO_VISITS}, {"Восток", "Юго-восток", "Югоцентр"})
        real = {
            (b.street, b.number, b.block): b
            for rows in buildings_by_district().values()
            for b in rows
        }
        for visit in DEMO_VISITS:
            with self.subTest(address=visit.address):
                building = real[(visit.street, visit.building, visit.block)]
                self.assertIn(visit.source_url, (f"https://www.openstreetmap.org/{building.osm}",))
                points = {
                    (f"{e.latitude:.6f}", f"{e.longitude:.6f}")
                    for e in building.entrances
                    if visit.entrance is None or e.number == visit.entrance
                }
                self.assertIn((visit.latitude, visit.longitude), points)
                if visit.apartment is not None:
                    entrance = next(e for e in building.entrances if e.number == visit.entrance)
                    self.assertTrue(
                        entrance.first_apartment <= int(visit.apartment) <= entrance.last_apartment
                    )
                    self.assertLessEqual(visit.floor, building.levels)

    def test_complete_data_set_includes_blocks_entrances_and_apartments(self):
        results = seed_data(self.session, self.visit_date)
        self.assertEqual(self.counts(), expected_counts())
        self.assertEqual(self.session.scalar(select(func.count()).select_from(District)), 3)
        self.assertTrue(all(result.created for result in results))
        for result, visit in zip(results, DEMO_VISITS, strict=True):
            ticket = self.session.get(Ticket, result.ticket_id)
            location = self.session.get(Location, result.location_id)
            self.assertEqual(location.latitude, Decimal(visit.latitude))
            self.assertEqual(location.longitude, Decimal(visit.longitude))
            building = self.session.get(Building, location.building_id)
            self.assertEqual(location.apartment, visit.apartment)
            self.assertEqual(location.floor, visit.floor)
            if visit.entrance is not None:
                entrance = self.session.get(Entrance, location.entrance_id)
                self.assertEqual(entrance.number, visit.entrance)
                self.assertEqual(entrance.building_id, building.id)
            self.assertEqual(building.block, visit.block)
            service_area = self.session.get(ServiceArea, building.service_area_id)
            district_row_id = int(service_area.code.removeprefix("district_"))
            district = self.session.get(District, district_row_id)
            self.assertEqual(district.name, visit.district)
            self.assertEqual(district.city_id, building.city_id)
            self.assertEqual(
                get_ticket_unscoped(self.session, ticket.id).location.service_area_id,
                service_area.id,
            )
            self.assertEqual(result.address, visit.address)
            self.assertEqual(
                get_ticket_unscoped(self.session, ticket.id).location.address, visit.address
            )
            local_start = ticket.visit_window_start.astimezone(MOSCOW_TIME)
            self.assertEqual(local_start.date(), self.visit_date)
            self.assertEqual(
                (local_start.hour, local_start.minute), (visit.start_hour, visit.start_minute)
            )
            self.assertEqual(ticket.status, TicketStatus.PLANNED)
            self.assertEqual(ticket.request_type_hd, visit.request_type_hd)
            self.assertIsNone(ticket.planned_start_at)
            self.assertIsNone(ticket.assigned_worker_id)
            self.assertIsNone(ticket.actual_duration_minutes)

    def test_rerun_even_on_another_day_keeps_ids_and_manual_edits(self):
        first = seed_data(self.session, self.visit_date)
        ticket = self.session.get(Ticket, first[0].ticket_id)
        original_window = ticket.visit_window_start
        ticket.status = TicketStatus.COMPLETED
        ticket.actual_duration_minutes = 75
        ticket.description = "Пояснение после выполнения"
        self.session.flush()
        second = seed_data(self.session, self.visit_date + timedelta(days=1))
        self.assertEqual([r.ticket_id for r in first], [r.ticket_id for r in second])
        self.assertFalse(any(result.created for result in second))
        self.assertEqual(self.counts(), expected_counts())
        self.session.expire_all()
        self.assertEqual(ticket.visit_window_start, original_window)
        self.assertEqual(ticket.status, TicketStatus.COMPLETED)
        self.assertEqual(ticket.actual_duration_minutes, 75)
        self.assertEqual(ticket.description, "Пояснение после выполнения")

    def test_brigades_serve_their_areas_and_nobody_is_assigned_before_planning(self):
        results = seed_data(self.session, self.visit_date)
        users = {u.username: u for u in self.session.scalars(select(User))}
        areas = {
            area.name: area.id
            for area in self.session.scalars(select(ServiceArea))
            if area.name in {"Восток", "Юго-восток", "Югоцентр"}
        }
        for info in DEMO_USERS:
            if info["role"] != "worker":
                continue
            with self.subTest(worker=info["username"]):
                worker = self.session.get(Worker, users[info["username"]].id)
                self.assertEqual(worker.service_area_id, areas[info["area"]])
                member = self.session.scalar(
                    select(BrigadeMember).where(BrigadeMember.worker_id == worker.user_id)
                )
                brigade = self.session.get(Brigade, member.brigade_id)
                foreman = self.session.get(User, brigade.foreman_id)
                foreman_area = next(
                    u["area"] for u in DEMO_USERS if u["username"] == foreman.username
                )
                self.assertEqual(foreman_area, info["area"])
                self.assertEqual(
                    brigade.name,
                    f"Бригада {foreman.surname} {foreman.name[0]}. {foreman.lastname[0]}.",
                )
        first_brigade = self.session.scalar(select(Brigade).order_by(Brigade.id))
        self.assertEqual(self.session.get(User, first_brigade.foreman_id).username, "demo_foreman")
        self.assertIsNone(
            self.session.scalar(
                select(Brigade).where(Brigade.foreman_id == users["demo_foreman_free"].id)
            )
        )
        self.assertEqual(
            self.session.scalar(
                select(func.count())
                .select_from(Ticket)
                .where(Ticket.assigned_worker_id.is_not(None))
            ),
            0,
        )
        first_ticket = get_ticket_unscoped(self.session, results[0].ticket_id)
        self.assertEqual(
            self.session.get(Worker, users["demo_worker_1"].id).service_area_id,
            first_ticket.location.service_area_id,
        )

    def test_dispatcher_notes_are_repeatable_and_preserve_manual_text(self):
        seed_data(self.session, self.visit_date)
        notes = sum(visit.note is not None for visit in DEMO_VISITS)
        self.assertGreater(notes, 0)
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(TicketComment)), notes
        )
        first_comment = self.session.scalars(
            select(TicketComment).order_by(TicketComment.id)
        ).first()
        first_comment.text = "Исправленная вручную заметка"
        self.session.flush()
        seed_data(self.session, self.visit_date + timedelta(days=1))
        self.session.expire_all()
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(TicketComment)), notes
        )
        self.assertEqual(
            self.session.get(TicketComment, first_comment.id).text,
            "Исправленная вручную заметка",
        )

    def test_two_apartments_share_building_and_two_tickets_share_one_apartment(self):
        results = seed_data(self.session, self.visit_date)
        first = self.session.get(Location, results[0].location_id)
        second = self.session.get(Location, results[1].location_id)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(first.building_id, second.building_id)
        self.assertEqual(first.entrance_id, second.entrance_id)
        self.assertEqual(
            (first.apartment, second.apartment),
            (DEMO_VISITS[0].apartment, DEMO_VISITS[1].apartment),
        )
        self.assertEqual(results[0].location_id, results[2].location_id)
        self.assertNotEqual(results[0].ticket_id, results[2].ticket_id)

    def test_same_apartment_number_in_another_entrance_is_a_different_location(self):
        first_visit = DEMO_VISITS[0]
        other = next(
            e.number
            for rows in buildings_by_district().values()
            for b in rows
            if (b.street, b.number, b.block)
            == (first_visit.street, first_visit.building, first_visit.block)
            for e in b.entrances
            if e.number != first_visit.entrance
        )
        second_visit = replace(first_visit, entrance=other)
        with patch("seed_demo.DEMO_VISITS", (first_visit, second_visit)):
            results = seed_data(self.session, self.visit_date)
            repeated = seed_data(self.session, self.visit_date)
        self.assertNotEqual(results[0].location_id, results[1].location_id)
        self.assertEqual(self.counts(), expected_counts((first_visit, second_visit)))
        self.assertFalse(any(result.created for result in repeated))

    def test_unspecified_destination_does_not_get_overwritten_with_an_apartment(self):
        basic = replace(DEMO_VISITS[0], entrance=None, floor=None, apartment=None)
        with patch("seed_demo.DEMO_VISITS", (basic,)):
            old = seed_data(self.session, self.visit_date)[0]
        results = seed_data(self.session, self.visit_date)
        self.assertNotEqual(old.location_id, results[0].location_id)
        self.assertEqual(self.counts(), expected_counts(extra_locations=1, extra_tickets=1))
        old_location = self.session.get(Location, old.location_id)
        self.assertIsNone(old_location.apartment)
        self.assertIsNone(old_location.entrance_id)
        self.assertEqual(self.session.get(Ticket, old.ticket_id).location_id, old.location_id)

    def test_missing_block_and_entrance_are_still_supported_without_duplicates(self):
        basic = replace(DEMO_VISITS[0], block=None, entrance=None, floor=None, apartment=None)
        with patch("seed_demo.DEMO_VISITS", (basic,)):
            seed_data(self.session, self.visit_date)
            repeated = seed_data(self.session, self.visit_date)
        self.assertEqual(self.counts(), expected_counts((basic,)))
        self.assertFalse(repeated[0].created)

    def test_conflicting_floor_is_not_overwritten(self):
        results = seed_data(self.session, self.visit_date)
        index = max(i for i, visit in enumerate(DEMO_VISITS) if visit.floor is not None)
        location = self.session.get(Location, results[index].location_id)
        location.floor = DEMO_VISITS[index].floor + 1
        self.session.flush()
        with self.assertRaisesRegex(RuntimeError, "другой этаж"):
            with self.session.begin_nested():
                seed_data(self.session, self.visit_date)
        self.assertEqual(location.floor, DEMO_VISITS[index].floor + 1)
        self.assertEqual(self.counts(), expected_counts())

    def test_existing_directory_is_reused_case_insensitively(self):
        visit = DEMO_VISITS[0]
        city = City(name="москва")
        self.session.add(city)
        self.session.flush()
        district = District(city_id=city.id, name=visit.district.upper())
        self.session.add(district)
        self.session.flush()
        street = Street(city_id=city.id, name=visit.street.upper())
        self.session.add(street)
        self.session.flush()
        building = Building(
            city_id=city.id,
            service_area_id=self.service_area_for_district(district.id),
            street_id=street.id,
            number=visit.building,
            block=visit.block.upper() if visit.block else None,
        )
        self.session.add(building)
        self.session.flush()
        entrance = Entrance(building_id=building.id, number=visit.entrance)
        self.session.add(entrance)
        self.session.flush()
        location = Location(
            building_id=building.id, entrance_id=entrance.id, apartment=visit.apartment
        )
        self.session.add(location)
        self.session.flush()
        results = seed_data(self.session, self.visit_date)
        self.session.refresh(location)
        self.assertEqual(results[0].location_id, location.id)
        self.assertEqual(self.counts(), expected_counts())
        self.assertEqual(location.latitude, Decimal(visit.latitude))
        self.assertEqual(location.floor, visit.floor)
        self.assertEqual(city.name, "москва")
        self.session.refresh(building)
        self.assertEqual(building.service_area_id, self.service_area_for_district(district.id))
        self.assertEqual(self.session.scalar(select(func.count()).select_from(District)), 3)

    def test_conflicting_district_rolls_back_new_tickets(self):
        original = seed_data(self.session, self.visit_date)
        first_location = self.session.get(Location, original[0].location_id)
        last_location = self.session.get(Location, original[-1].location_id)
        first = self.session.get(Building, first_location.building_id)
        last = self.session.get(Building, last_location.building_id)
        self.assertNotEqual(first.service_area_id, last.service_area_id)
        last.service_area_id = first.service_area_id
        conflicting_id = last.service_area_id
        for result in original[:-1]:
            self.session.delete(self.session.get(Ticket, result.ticket_id))
        self.session.flush()
        with self.assertRaisesRegex(RuntimeError, "другая зона обслуживания"):
            with self.session.begin_nested():
                seed_data(self.session, self.visit_date)
        self.session.expire_all()
        self.assertEqual(first.service_area_id, conflicting_id)
        self.assertEqual(last.service_area_id, conflicting_id)
        self.assertEqual(self.counts(), expected_counts(extra_tickets=1 - len(expected_tickets())))

    def test_coordinate_conflict_rolls_back_the_whole_attempt(self):
        results = seed_data(self.session, self.visit_date)
        # Leave only the last ticket, so a failed rerun first attempts the other inserts.
        for result in results[:-1]:
            self.session.delete(self.session.get(Ticket, result.ticket_id))
        location = self.session.get(Location, results[-1].location_id)
        location.latitude = Decimal("55.500000")
        self.session.flush()
        with self.assertRaisesRegex(RuntimeError, "другие координаты"):
            with self.session.begin_nested():
                seed_data(self.session, self.visit_date)
        self.assertEqual(self.counts(), expected_counts(extra_tickets=1 - len(expected_tickets())))
        self.assertEqual(location.latitude, Decimal("55.500000"))

    def test_existing_non_demo_ticket_at_same_address_is_preserved(self):
        results = seed_data(self.session, self.visit_date)
        demo = self.session.get(Ticket, results[0].ticket_id)
        real = Ticket(
            location_id=demo.location_id,
            title="Обычная заявка",
            work_type=demo.work_type,
            estimated_duration_minutes=30,
            visit_window_start=demo.visit_window_start,
            visit_window_end=demo.visit_window_end,
        )
        self.session.add(real)
        self.session.flush()
        seed_data(self.session, self.visit_date)
        self.assertEqual(self.counts(), expected_counts(extra_tickets=1))
        self.assertEqual(self.session.get(Ticket, real.id).title, "Обычная заявка")

    def test_quotes_in_demo_values_are_saved_as_text(self):
        visit = replace(DEMO_VISITS[0], title="Офис 'Север'; SELECT 1 --")
        with patch("seed_demo.DEMO_VISITS", (visit,)):
            first = seed_data(self.session, self.visit_date)
            second = seed_data(self.session, self.visit_date)
        ticket = self.session.get(Ticket, first[0].ticket_id)
        self.assertEqual(ticket.title, visit.title)
        self.assertEqual(first[0].ticket_id, second[0].ticket_id)
        self.assertEqual(self.counts(), expected_counts((visit,)))


def expected_tickets():
    return {(v.street, v.building, v.block, v.entrance, v.apartment, v.title) for v in DEMO_VISITS}

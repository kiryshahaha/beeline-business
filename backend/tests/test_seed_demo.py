"""Demo data is repeatable, preserves existing records and needs no geocoding network call."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import func, select

from app.db.models import (
    Building,
    City,
    District,
    Entrance,
    Location,
    Street,
    Ticket,
    TicketAssignment,
    TicketComment,
)
from app.modules.tickets.enums import TicketStatus
from app.modules.tickets.service import get_ticket
from seed_demo import DEMO_VISITS, MOSCOW_TIME, seed_data
from tests.support import DatabaseTestCase


class SeedDemoTests(DatabaseTestCase):
    visit_date = date(2026, 9, 14)

    def counts(self):
        return [
            self.session.scalar(select(func.count()).select_from(City)) - 1,
            self.session.scalar(select(func.count()).select_from(Street)) - 3,
            self.session.scalar(select(func.count()).select_from(Building)) - 3,
            self.session.scalar(select(func.count()).select_from(Entrance)),
            self.session.scalar(select(func.count()).select_from(Location)) - 3,
            self.session.scalar(select(func.count()).select_from(Ticket)),
        ]

    def test_complete_data_set_includes_blocks_entrances_and_apartments(self):
        results = seed_data(self.session, self.visit_date)
        self.assertEqual(self.counts(), [1, 4, 6, 6, 7, 8])
        self.assertEqual(self.session.scalar(select(func.count()).select_from(District)), 3)
        self.assertTrue(all(result.created for result in results))
        for result, visit in zip(results, DEMO_VISITS, strict=True):
            ticket = self.session.get(Ticket, result.ticket_id)
            location = self.session.get(Location, result.location_id)
            self.assertEqual(location.latitude, Decimal(visit.latitude))
            self.assertEqual(location.longitude, Decimal(visit.longitude))
            entrance = self.session.get(Entrance, location.entrance_id)
            building = self.session.get(Building, location.building_id)
            self.assertEqual(location.apartment, visit.apartment)
            self.assertEqual(location.floor, visit.floor)
            self.assertEqual(entrance.number, visit.entrance)
            self.assertEqual(entrance.building_id, building.id)
            self.assertEqual(building.block, visit.block)
            district = self.session.get(District, building.district_id)
            self.assertEqual(district.name, visit.district)
            self.assertEqual(district.city_id, building.city_id)
            self.assertEqual(get_ticket(self.session, ticket.id).location.district_id, district.id)
            self.assertEqual(result.address, visit.address)
            self.assertEqual(get_ticket(self.session, ticket.id).location.address, visit.address)
            local_start = ticket.visit_window_start.astimezone(MOSCOW_TIME)
            self.assertEqual(local_start.date(), self.visit_date)
            self.assertEqual(local_start.hour, visit.start_hour)
            self.assertEqual(ticket.status, TicketStatus.PLANNED)
            self.assertIsNone(ticket.planned_start_at)
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
        self.assertEqual(self.counts(), [1, 4, 6, 6, 7, 8])
        self.session.expire_all()
        self.assertEqual(ticket.visit_window_start, original_window)
        self.assertEqual(ticket.status, TicketStatus.COMPLETED)
        self.assertEqual(ticket.actual_duration_minutes, 75)
        self.assertEqual(ticket.description, "Пояснение после выполнения")

    def test_demo_assignments_and_comments_are_repeatable_and_preserve_manual_text(self):
        first = seed_data(self.session, self.visit_date)
        assignment_count = self.session.scalar(select(func.count()).select_from(TicketAssignment))
        comment_count = self.session.scalar(select(func.count()).select_from(TicketComment))
        self.assertEqual(assignment_count, len(DEMO_VISITS))
        self.assertEqual(comment_count, len(DEMO_VISITS))
        self.assertTrue(
            all(get_ticket(self.session, item.ticket_id).assignee_ids for item in first)
        )

        first_comment = self.session.scalars(
            select(TicketComment).order_by(TicketComment.id)
        ).first()
        first_comment.text = "Исправленная вручную заметка"
        self.session.flush()
        seed_data(self.session, self.visit_date + timedelta(days=1))
        self.session.expire_all()

        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(TicketAssignment)),
            assignment_count,
        )
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(TicketComment)),
            comment_count,
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
        self.assertEqual((first.apartment, second.apartment), ("12", "16"))
        self.assertEqual(results[0].location_id, results[2].location_id)
        self.assertNotEqual(results[0].ticket_id, results[2].ticket_id)

    def test_same_apartment_number_in_another_entrance_is_a_different_location(self):
        first_visit = DEMO_VISITS[0]
        second_visit = replace(first_visit, entrance="2")
        with patch("seed_demo.DEMO_VISITS", (first_visit, second_visit)):
            results = seed_data(self.session, self.visit_date)
            repeated = seed_data(self.session, self.visit_date)
        self.assertNotEqual(results[0].location_id, results[1].location_id)
        self.assertEqual(self.counts(), [1, 1, 1, 2, 2, 2])
        self.assertFalse(any(result.created for result in repeated))

    def test_unspecified_destination_does_not_get_overwritten_with_an_apartment(self):
        basic = replace(DEMO_VISITS[0], entrance=None, floor=None, apartment=None)
        with patch("seed_demo.DEMO_VISITS", (basic,)):
            old = seed_data(self.session, self.visit_date)[0]
        results = seed_data(self.session, self.visit_date)
        self.assertNotEqual(old.location_id, results[0].location_id)
        self.assertEqual(self.counts(), [1, 4, 6, 6, 8, 9])
        old_location = self.session.get(Location, old.location_id)
        self.assertIsNone(old_location.apartment)
        self.assertIsNone(old_location.entrance_id)
        self.assertEqual(self.session.get(Ticket, old.ticket_id).location_id, old.location_id)

    def test_missing_block_and_entrance_are_still_supported_without_duplicates(self):
        basic = replace(DEMO_VISITS[0], block=None, entrance=None, floor=None, apartment=None)
        with patch("seed_demo.DEMO_VISITS", (basic,)):
            seed_data(self.session, self.visit_date)
            repeated = seed_data(self.session, self.visit_date)
        self.assertEqual(self.counts(), [1, 1, 1, 0, 1, 1])
        self.assertFalse(repeated[0].created)

    def test_conflicting_floor_is_not_overwritten(self):
        results = seed_data(self.session, self.visit_date)
        location = self.session.get(Location, results[-1].location_id)
        location.floor = 8
        self.session.flush()
        with self.assertRaisesRegex(RuntimeError, "другой этаж"):
            with self.session.begin_nested():
                seed_data(self.session, self.visit_date)
        self.assertEqual(location.floor, 8)
        self.assertEqual(self.counts(), [1, 4, 6, 6, 7, 8])

    def test_existing_directory_is_reused_case_insensitively(self):
        city = City(name="санкт-петербург")
        self.session.add(city)
        self.session.flush()
        district = District(city_id=city.id, name=DEMO_VISITS[0].district.upper())
        self.session.add(district)
        self.session.flush()
        street = Street(city_id=city.id, name=DEMO_VISITS[0].street.upper())
        self.session.add(street)
        self.session.flush()
        building = Building(
            city_id=city.id,
            district_id=district.id,
            street_id=street.id,
            number=DEMO_VISITS[0].building,
            block=DEMO_VISITS[0].block.upper(),
        )
        self.session.add(building)
        self.session.flush()
        entrance = Entrance(building_id=building.id, number=DEMO_VISITS[0].entrance)
        self.session.add(entrance)
        self.session.flush()
        location = Location(
            building_id=building.id, entrance_id=entrance.id, apartment=DEMO_VISITS[0].apartment
        )
        self.session.add(location)
        self.session.flush()
        results = seed_data(self.session, self.visit_date)
        self.session.refresh(location)
        self.assertEqual(results[0].location_id, location.id)
        self.assertEqual(self.counts(), [1, 4, 6, 6, 7, 8])
        self.assertEqual(location.latitude, Decimal(DEMO_VISITS[0].latitude))
        self.assertEqual(location.floor, DEMO_VISITS[0].floor)
        self.assertEqual(city.name, "санкт-петербург")
        self.session.refresh(building)
        self.assertEqual(building.district_id, district.id)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(District)), 3)

    def test_conflicting_district_rolls_back_new_tickets(self):
        original = seed_data(self.session, self.visit_date)
        first_location = self.session.get(Location, original[0].location_id)
        last_location = self.session.get(Location, original[-1].location_id)
        first = self.session.get(Building, first_location.building_id)
        last = self.session.get(Building, last_location.building_id)
        last.district_id = first.district_id
        conflicting_id = last.district_id
        for result in original[:-1]:
            self.session.delete(self.session.get(Ticket, result.ticket_id))
        self.session.flush()
        with self.assertRaisesRegex(RuntimeError, "другой район"):
            with self.session.begin_nested():
                seed_data(self.session, self.visit_date)
        self.session.expire_all()
        self.assertEqual(first.district_id, conflicting_id)
        self.assertEqual(last.district_id, conflicting_id)
        self.assertEqual(self.counts(), [1, 4, 6, 6, 7, 1])

    def test_coordinate_conflict_rolls_back_the_whole_attempt(self):
        results = seed_data(self.session, self.visit_date)
        # Leave only the last ticket, so a failed rerun first attempts seven inserts.
        for result in results[:-1]:
            self.session.delete(self.session.get(Ticket, result.ticket_id))
        location = self.session.get(Location, results[-1].location_id)
        location.latitude = Decimal("59.950000")
        self.session.flush()
        with self.assertRaisesRegex(RuntimeError, "другие координаты"):
            with self.session.begin_nested():
                seed_data(self.session, self.visit_date)
        self.assertEqual(self.counts(), [1, 4, 6, 6, 7, 1])
        self.assertEqual(location.latitude, Decimal("59.950000"))

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
        self.assertEqual(self.counts(), [1, 4, 6, 6, 7, 9])
        self.assertEqual(self.session.get(Ticket, real.id).title, "Обычная заявка")

    def test_quotes_in_demo_values_are_saved_as_text(self):
        visit = replace(DEMO_VISITS[0], title="[Демо] Офис 'Север'; SELECT 1 --")
        with patch("seed_demo.DEMO_VISITS", (visit,)):
            first = seed_data(self.session, self.visit_date)
            second = seed_data(self.session, self.visit_date)
        ticket = self.session.get(Ticket, first[0].ticket_id)
        self.assertEqual(ticket.title, visit.title)
        self.assertEqual(first[0].ticket_id, second[0].ticket_id)
        self.assertEqual(self.counts(), [1, 1, 1, 1, 1, 1])

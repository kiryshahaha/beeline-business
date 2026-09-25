"""Calendar feed: iCalendar rendering, secret links, rotation, revocation and access."""

import hashlib
import unittest
from datetime import UTC, datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from icalendar import Calendar
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.models import (
    Building,
    City,
    District,
    Entrance,
    Location,
    Street,
    Ticket,
)
from app.db.session import get_session
from app.main import app
from app.modules.calendar_feed.ics import build_calendar
from app.modules.tickets.enums import TicketStatus
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from tests.support import DatabaseTestCase

MOSCOW = timezone(timedelta(hours=3))


def ticket_row(**overrides) -> dict:
    row = {
        "id": 42,
        "title": "Монтаж оборудования",
        "description": "Клиент просит позвонить за час, домофон; не работает",
        "work_type": "Подключение клиентов Базовая",
        "status": "planned",
        "visit_window_start": datetime(2026, 9, 21, 10, tzinfo=MOSCOW),
        "visit_window_end": datetime(2026, 9, 21, 14, tzinfo=MOSCOW),
        "planned_start_at": datetime(2026, 9, 21, 11, tzinfo=MOSCOW),
        "planned_end_at": datetime(2026, 9, 21, 12, 30, tzinfo=MOSCOW),
        "updated_at": datetime(2026, 9, 19, 9, tzinfo=UTC),
        "location_id": 7,
        "city_id": 1,
        "city": "Москва",
        "district_id": 1,
        "district": "Тверской район",
        "street_id": 1,
        "street": "Тверская улица",
        "building_id": 1,
        "building_number": "4",
        "block": "корпус 2",
        "entrance_id": 1,
        "entrance_number": "3",
        "floor": 5,
        "apartment": "17",
        "latitude": 55.757,
        "longitude": 37.615,
    }
    return row | overrides


def parse(content: bytes) -> dict[int, object]:
    calendar = Calendar.from_ical(content)
    return {
        int(str(event["uid"]).split("-")[1].split("@")[0]): event
        for event in calendar.walk("VEVENT")
    }


class BuildCalendarTests(unittest.TestCase):
    def test_event_contains_time_navigation_address_and_details(self):
        content = build_calendar(
            "Кузнецов Дмитрий", [ticket_row()], frontend_url="https://front.example.ru/"
        )
        calendar = Calendar.from_ical(content)
        (event,) = calendar.walk("VEVENT")

        self.assertEqual(str(calendar["x-wr-calname"]), "Заявки: Кузнецов Дмитрий")
        self.assertEqual(str(event["uid"]), "ticket-42@beeline-business")
        self.assertEqual(str(event["summary"]), "Заявка #42: Монтаж оборудования")
        self.assertEqual(event.decoded("dtstart"), datetime(2026, 9, 21, 8, tzinfo=UTC))
        self.assertEqual(event.decoded("dtend"), datetime(2026, 9, 21, 9, 30, tzinfo=UTC))
        self.assertEqual(str(event["location"]), "Москва, Тверская улица, д. 4, корпус 2")
        self.assertEqual((event["geo"].latitude, event["geo"].longitude), (55.757, 37.615))
        self.assertEqual(str(event["url"]), "https://front.example.ru/tickets/42")
        self.assertEqual(str(event["status"]), "CONFIRMED")
        description = str(event["description"])
        for fragment in (
            "Тип работ: Подключение клиентов Базовая",
            "Статус: Запланирована",
            "подъезд 3, этаж 5, кв./пом. 17",
            "Окно визита (МСК): 21.09 10:00 – 21.09 14:00",
            "домофон; не работает",
            "Карточка заявки: https://front.example.ru/tickets/42",
        ):
            self.assertIn(fragment, description)

    def test_cancelled_ticket_and_missing_optional_data(self):
        content = build_calendar(
            "Кузнецов Дмитрий",
            [ticket_row(status="wont_fix", description=None, latitude=None, block=None)],
            frontend_url=None,
        )
        (event,) = Calendar.from_ical(content).walk("VEVENT")

        self.assertEqual(str(event["status"]), "CANCELLED")
        self.assertEqual(str(event["location"]), "Москва, Тверская улица, д. 4")
        self.assertNotIn("geo", event)
        self.assertNotIn("url", event)
        self.assertNotIn("Карточка заявки", str(event["description"]))

    def test_empty_feed_is_a_valid_calendar(self):
        calendar = Calendar.from_ical(build_calendar("Кузнецов Дмитрий", [], frontend_url=None))

        self.assertEqual(calendar.walk("VEVENT"), [])
        self.assertEqual(str(calendar["version"]), "2.0")


class CalendarFeedApiTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        city = self.save(City(name="Москва"))
        district = self.save(District(city_id=city.id, name="Тверской район"))
        street = self.save(Street(city_id=city.id, name="Тверская улица"))
        building = self.save(
            Building(
                city_id=city.id,
                district_id=district.id,
                street_id=street.id,
                number="4",
                block="корпус 2",
            )
        )
        entrance = self.save(Entrance(building_id=building.id, number="3"))
        self.location_id = self.save(
            Location(
                building_id=building.id,
                entrance_id=entrance.id,
                floor=5,
                apartment="17",
                latitude=55.757,
                longitude=37.615,
            )
        ).id
        self.session.commit()

        self.observer = self.new_user("observer", UserRole.OBSERVER)
        self.foreman = self.new_user("foreman", UserRole.FOREMAN)
        self.worker = self.new_user("worker", UserRole.WORKER)
        self.other_worker = self.new_user("other", UserRole.WORKER)

        now = datetime.now(UTC)
        self.upcoming = self.new_ticket([self.worker], now + timedelta(days=1))
        self.recent = self.new_ticket([self.worker], now - timedelta(days=5))
        self.cancelled = self.new_ticket(
            [self.worker], now + timedelta(days=2), TicketStatus.WONT_FIX
        )
        # Not in the feed: too old, without a plan, or assigned to someone else.
        self.new_ticket([self.worker], now - timedelta(days=40))
        self.new_ticket([self.worker], None)
        self.new_ticket([self.other_worker], now + timedelta(days=1))
        self.session.commit()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))

    def save(self, instance):
        self.session.add(instance)
        self.session.flush()
        return instance

    def new_user(self, username, role):
        return create_user(
            self.session,
            UserCreate(
                name="Дмитрий",
                surname=username.capitalize(),
                username=username,
                password="Password123!",
                role=role,
                worker_profile=WorkerProfileCreate(
                    workshift_start="09:00", workshift_end="18:00", skills=["Монтаж"]
                )
                if role == UserRole.WORKER
                else None,
            ),
        )

    def new_ticket(self, workers, planned_start, status=TicketStatus.PLANNED):
        ticket = self.save(
            Ticket(
                location_id=self.location_id,
                title="Монтаж оборудования",
                work_type="Подключение клиентов Базовая",
                status=status,
                visit_window_start=datetime(2026, 9, 1, tzinfo=UTC),
                visit_window_end=datetime(2027, 9, 1, tzinfo=UTC),
                planned_start_at=planned_start,
                planned_end_at=planned_start + timedelta(hours=1) if planned_start else None,
                estimated_duration_minutes=60,
                assigned_worker_id=workers[0].id if workers else None,
            )
        )
        return ticket.id

    @staticmethod
    def auth(user):
        return {
            "Authorization": "Bearer "
            + create_access_token({"sub": str(user.id), "role": user.role.value})
        }

    def issue(self, user=None):
        response = self.client.post(
            "/api/v1/schedule/calendar/token", headers=self.auth(user or self.worker)
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def feed(self, url):
        parts = urlsplit(url)
        return self.client.get(f"{parts.path}?{parts.query}")

    @staticmethod
    def token_of(url):
        return urlsplit(url).query.removeprefix("token=")

    def test_worker_subscribes_to_own_planned_tickets(self):
        link = self.issue()
        self.assertTrue(
            link["url"].startswith("http://testserver/api/v1/schedule/calendar.ics?token=")
        )
        self.assertGreaterEqual(len(self.token_of(link["url"])), 40)

        response = self.feed(link["url"])

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.headers["content-type"].startswith("text/calendar"))
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        events = parse(response.content)
        self.assertEqual(set(events), {self.upcoming, self.recent, self.cancelled})
        self.assertEqual(str(events[self.cancelled]["status"]), "CANCELLED")
        self.assertEqual(
            str(events[self.upcoming]["location"]), "Москва, Тверская улица, д. 4, корпус 2"
        )

    def test_only_token_hash_is_stored(self):
        token = self.token_of(self.issue()["url"])

        stored = self.connection.execute(
            text("SELECT token_hash FROM calendar_tokens WHERE user_id = :id"),
            {"id": self.worker.id},
        ).scalar_one()

        self.assertNotEqual(stored, token)
        self.assertEqual(stored, hashlib.sha256(token.encode()).hexdigest())

    def test_reissue_invalidates_previous_link(self):
        first = self.issue()["url"]
        second = self.issue()["url"]

        self.assertNotEqual(first, second)
        self.assertEqual(self.feed(first).status_code, 404)
        self.assertEqual(self.feed(second).status_code, 200)

    def test_status_and_revocation(self):
        path = "/api/v1/schedule/calendar/token"
        headers = self.auth(self.worker)
        self.assertEqual(
            self.client.get(path, headers=headers).json(), {"active": False, "created_at": None}
        )

        url = self.issue()["url"]
        status = self.client.get(path, headers=headers).json()
        self.assertTrue(status["active"])
        self.assertIsNotNone(status["created_at"])

        for _ in range(2):
            self.assertEqual(self.client.delete(path, headers=headers).status_code, 204)
        self.assertEqual(self.feed(url).status_code, 404)
        self.assertFalse(self.client.get(path, headers=headers).json()["active"])

    def test_deleting_worker_without_history_removes_link(self):
        newcomer = self.new_user("newcomer", UserRole.WORKER)
        self.session.commit()
        url = self.issue(newcomer)["url"]

        response = self.client.delete(
            f"/api/v1/users/{newcomer.id}", headers=self.auth(self.observer)
        )

        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(self.feed(url).status_code, 404)

    def test_archive_or_role_change_closes_the_link_and_keeps_history(self):
        url = self.issue()["url"]
        # A surviving token row of an archived account opens nothing.
        self.connection.execute(
            text("UPDATE users SET archived_at = now() WHERE id = :id"), {"id": self.worker.id}
        )
        self.assertEqual(self.feed(url).status_code, 404)
        self.connection.execute(
            text("UPDATE users SET archived_at = NULL WHERE id = :id"), {"id": self.worker.id}
        )
        self.assertEqual(self.feed(url).status_code, 200)

        # A worker with finished history leaves the role: the link is deleted, not reused.
        self.connection.execute(
            text("UPDATE tickets SET status = 'completed' WHERE status = 'planned'")
        )
        response = self.client.patch(
            f"/api/v1/users/{self.worker.id}",
            json={"role": "observer"},
            headers=self.auth(self.observer),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.feed(url).status_code, 404)
        self.assertEqual(
            self.connection.execute(
                text("SELECT count(*) FROM tickets WHERE assigned_worker_id = :id"),
                {"id": self.worker.id},
            ).scalar_one(),
            5,
        )

    def test_only_workers_manage_links_and_jwt_is_required(self):
        path = "/api/v1/schedule/calendar/token"
        for user in (self.observer, self.foreman):
            for method in ("post", "get", "delete"):
                with self.subTest(role=user.role, method=method):
                    response = getattr(self.client, method)(path, headers=self.auth(user))
                    self.assertEqual(response.status_code, 403)
        for method in ("post", "get", "delete"):
            with self.subTest(method=method):
                self.assertEqual(getattr(self.client, method)(path).status_code, 401)

    def test_unknown_missing_and_oversized_tokens(self):
        path = "/api/v1/schedule/calendar.ics"
        response = self.client.get(path, params={"token": "unknown-token"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Календарь не найден")
        self.assertEqual(self.client.get(path).status_code, 422)
        self.assertEqual(self.client.get(path, params={"token": "x" * 201}).status_code, 422)

    def test_public_urls_come_from_settings(self):
        settings = get_settings()
        previous = settings.public_api_url, settings.frontend_url
        self.addCleanup(setattr, settings, "public_api_url", previous[0])
        self.addCleanup(setattr, settings, "frontend_url", previous[1])
        settings.public_api_url = "https://api.example.ru/"
        settings.frontend_url = "https://front.example.ru"

        url = self.issue()["url"]
        events = parse(self.feed(url).content)

        self.assertTrue(
            url.startswith("https://api.example.ru/api/v1/schedule/calendar.ics?token=")
        )
        self.assertEqual(
            str(events[self.upcoming]["url"]), f"https://front.example.ru/tickets/{self.upcoming}"
        )

    def test_openapi_marks_only_link_management_as_protected(self):
        paths = app.openapi()["paths"]

        self.assertNotIn("security", paths["/api/v1/schedule/calendar.ics"]["get"])
        for method in ("post", "get", "delete"):
            self.assertIn(
                {"BearerAuth": []}, paths["/api/v1/schedule/calendar/token"][method]["security"]
            )

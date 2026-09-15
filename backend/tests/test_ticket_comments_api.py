"""Ticket comment feed behavior and access rules."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.models import Building, City, District, Location, Street
from app.db.session import get_session
from app.main import app
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from tests.support import DatabaseTestCase


class TicketCommentsApiTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        city = self.save(City(name="Санкт-Петербург"))
        district = self.save(District(city_id=city.id, name="Невский район"))
        street = self.save(Street(city_id=city.id, name="Тестовая улица"))
        building = self.save(
            Building(
                city_id=city.id,
                street_id=street.id,
                district_id=district.id,
                number="11",
            )
        )
        location = self.save(Location(building_id=building.id))
        self.location_id = location.id
        self.session.commit()
        self.observer = self.create_user("comment_observer", UserRole.OBSERVER)
        self.worker = self.create_user("comment_worker", UserRole.WORKER)
        self.other_worker = self.create_user("other_comment_worker", UserRole.WORKER)
        self.session.commit()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))
        ticket = self.client.post(
            "/api/v1/tickets",
            json={
                "location_id": self.location_id,
                "title": "Проверить линию",
                "work_type": "Диагностика сети",
                "visit_window_start": "2026-09-14T10:00:00+03:00",
                "visit_window_end": "2026-09-14T14:00:00+03:00",
                "estimated_duration_minutes": 60,
            },
        )
        self.assertEqual(ticket.status_code, 201, ticket.text)
        self.ticket_id = ticket.json()["id"]
        assigned = self.client.put(
            f"/api/v1/tickets/{self.ticket_id}/assignees",
            json={"worker_ids": [self.worker.id]},
            headers=self.auth(self.observer),
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)

    def save(self, instance):
        self.session.add(instance)
        self.session.flush()
        return instance

    def create_user(self, username, role):
        profile = None
        if role == UserRole.WORKER:
            profile = WorkerProfileCreate(
                workshift_start="09:00:00",
                workshift_end="18:00:00",
                skills=["Диагностика сети"],
            )
        return create_user(
            self.session,
            UserCreate(
                name="Тест",
                surname=username,
                username=username,
                password="Password123!",
                role=role,
                worker_profile=profile,
            ),
        )

    @staticmethod
    def auth(user):
        token = create_access_token({"sub": str(user.id), "role": user.role.value})
        return {"Authorization": f"Bearer {token}"}

    def test_observer_creates_and_lists_comments_in_creation_order(self):
        url = f"/api/v1/tickets/{self.ticket_id}/comments"
        texts = [
            "  Клиент просит позвонить за 15 минут  ",
            "Кавычки ' и SQL: SELECT 1 -- остаются текстом",
        ]
        created = []
        for text_value in texts:
            response = self.client.post(
                url,
                json={"text": text_value},
                headers=self.auth(self.observer),
            )
            self.assertEqual(response.status_code, 201, response.text)
            created.append(response.json())
        self.assertEqual([item["text"] for item in created], [text.strip() for text in texts])
        self.assertTrue(created[0]["id"] < created[1]["id"])
        self.assertEqual(created[0]["author"]["id"], self.observer.id)
        self.assertEqual(created[0]["author"]["role"], "observer")

        listed = self.client.get(url, headers=self.auth(self.observer))
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json(), created)

    def test_assigned_worker_can_comment_while_other_worker_is_denied(self):
        url = f"/api/v1/tickets/{self.ticket_id}/comments"
        denied = self.client.post(
            url,
            json={"text": "Чужая заметка"},
            headers=self.auth(self.other_worker),
        )
        self.assertEqual(denied.status_code, 403)
        allowed = self.client.post(
            url,
            json={"text": "Нужен новый разъём"},
            headers=self.auth(self.worker),
        )
        self.assertEqual(allowed.status_code, 201, allowed.text)
        self.assertEqual(allowed.json()["author"]["id"], self.worker.id)
        self.assertEqual(
            self.client.get(url, headers=self.auth(self.other_worker)).status_code,
            403,
        )

    def test_comment_endpoints_require_auth_and_existing_ticket(self):
        url = f"/api/v1/tickets/{self.ticket_id}/comments"
        self.assertEqual(self.client.get(url).status_code, 401)
        missing = self.client.post(
            "/api/v1/tickets/2147483647/comments",
            json={"text": "Заметка"},
            headers=self.auth(self.observer),
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json(), {"detail": "Заявка не найдена"})

    def test_invalid_comment_text_is_rejected(self):
        url = f"/api/v1/tickets/{self.ticket_id}/comments"
        for value in ("", "   ", "x" * 4001, "text\x00text", None, 123):
            with self.subTest(value_type=type(value).__name__):
                response = self.client.post(
                    url,
                    json={"text": value},
                    headers=self.auth(self.observer),
                )
                self.assertEqual(response.status_code, 422, response.text)

"""Authenticated notification history and Firebase token ownership."""

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.models import Building, City, District, Location, Street, Ticket
from app.db.session import get_session
from app.main import app
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate
from app.modules.users.service import create_user
from tests.support import DatabaseTestCase


class NotificationsApiTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        city = self.save(City(name="Санкт-Петербург"))
        district = self.save(District(city_id=city.id, name="Невский район"))
        street = self.save(Street(city_id=city.id, name="Тестовая улица"))
        building = self.save(
            Building(city_id=city.id, street_id=street.id, district_id=district.id, number="12")
        )
        location = self.save(Location(building_id=building.id))
        self.ticket = self.save(
            Ticket(
                location_id=location.id,
                title="Проверить линию",
                work_type="Диагностика сети",
                visit_window_start=datetime.now(UTC),
                visit_window_end=datetime.now(UTC) + timedelta(hours=2),
                estimated_duration_minutes=60,
            )
        )
        self.session.commit()
        self.first_user = self.create_observer("notify_observer_one")
        self.second_user = self.create_observer("notify_observer_two")
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

    def create_observer(self, username):
        return create_user(
            self.session,
            UserCreate(
                name="Тест",
                surname=username,
                username=username,
                password="Password123!",
                role=UserRole.OBSERVER,
            ),
        )

    @staticmethod
    def auth(user):
        token = create_access_token({"sub": str(user.id), "role": user.role.value})
        return {"Authorization": f"Bearer {token}"}

    def add_event(self, recipient_id, kind, data):
        event_id = self.session.execute(
            text("""
                INSERT INTO notification_events (recipient_id, ticket_id, kind, data)
                VALUES (:recipient_id, :ticket_id, :kind, CAST(:data AS JSONB))
                RETURNING id
            """),
            {
                "recipient_id": recipient_id,
                "ticket_id": self.ticket.id,
                "kind": kind,
                "data": json.dumps(data),
            },
        ).scalar_one()
        self.session.commit()
        return event_id

    def test_push_token_is_registered_transferred_and_removed_by_its_owner(self):
        url = "/api/v1/notifications/push-subscriptions"
        token_value = "firebase-registration-token"
        created = self.client.post(
            url,
            json={"token": token_value},
            headers=self.auth(self.first_user),
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["token"], token_value)

        transferred = self.client.post(
            url,
            json={"token": token_value},
            headers=self.auth(self.second_user),
        )
        self.assertEqual(transferred.status_code, 201, transferred.text)
        self.assertEqual(transferred.json()["user_id"], self.second_user.id)
        denied = self.client.request(
            "DELETE",
            url,
            json={"token": token_value},
            headers=self.auth(self.first_user),
        )
        self.assertEqual(denied.status_code, 404)
        removed = self.client.request(
            "DELETE",
            url,
            json={"token": token_value},
            headers=self.auth(self.second_user),
        )
        self.assertEqual(removed.status_code, 204, removed.text)

    def test_history_returns_only_current_user_events_with_pagination(self):
        first_id = self.add_event(
            self.first_user.id,
            "ticket_status_changed",
            {"previous_status": "planned", "status": "in_progress"},
        )
        second_id = self.add_event(
            self.first_user.id,
            "ticket_status_changed",
            {"previous_status": "in_progress", "status": "completed"},
        )
        self.add_event(
            self.second_user.id,
            "ticket_status_changed",
            {"previous_status": "planned", "status": "completed"},
        )

        response = self.client.get(
            "/api/v1/notifications",
            params={"limit": 1, "offset": 1},
            headers=self.auth(self.first_user),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["id"] for item in response.json()], [first_id])
        self.assertNotEqual(first_id, second_id)
        event = response.json()[0]
        self.assertEqual(event["recipient_id"], self.first_user.id)
        self.assertEqual(event["ticket_id"], self.ticket.id)
        self.assertEqual(event["data"]["status"], "in_progress")

    def test_notification_endpoints_require_auth_and_validate_input(self):
        subscriptions = "/api/v1/notifications/push-subscriptions"
        self.assertEqual(self.client.get("/api/v1/notifications").status_code, 401)
        self.assertEqual(
            self.client.post(subscriptions, json={"token": "token"}).status_code,
            401,
        )
        for token_value in ("", "   ", "x" * 4097, "text\x00text", None, 42):
            with self.subTest(token_type=type(token_value).__name__):
                response = self.client.post(
                    subscriptions,
                    json={"token": token_value},
                    headers=self.auth(self.first_user),
                )
                self.assertEqual(response.status_code, 422, response.text)
        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            response = self.client.get(
                "/api/v1/notifications",
                params=params,
                headers=self.auth(self.first_user),
            )
            self.assertEqual(response.status_code, 422, response.text)

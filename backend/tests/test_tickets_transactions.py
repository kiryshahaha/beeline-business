"""Verify ticket HTTP requests commit or roll back using the real session dependency."""

from datetime import date
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.main import app
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate
from app.modules.users.service import create_user
from seed_demo import run_seed
from tests.support import CommittedDatabaseTestCase


class TicketsTransactionTests(CommittedDatabaseTestCase):
    def setUp(self):
        super().setUp()
        # Demo data only supplies an existing address; the assertions below exercise HTTP.
        self.location_id = run_seed(self.engine, date(2026, 9, 14))[0].location_id
        with self.engine.connect() as connection:
            self.initial_ticket_count = connection.execute(
                text("SELECT count(*) FROM tickets")
            ).scalar_one()
        with Session(self.engine) as session:
            observer = create_user(
                session,
                UserCreate(
                    name="Тестовый",
                    surname="Наблюдатель",
                    username="ticket_transaction_observer",
                    password="Password123!",
                    role=UserRole.OBSERVER,
                ),
            )
            session.commit()
        self.auth_headers = {
            "Authorization": "Bearer "
            + create_access_token({"sub": str(observer.id), "role": observer.role.value})
        }
        # Keep the application's real get_session dependency, pointing to our test engine.
        self.enterContext(patch("app.db.session.get_engine", return_value=self.engine))
        self.client = self.enterContext(TestClient(app, raise_server_exceptions=False))
        self.payload = {
            "location_id": self.location_id,
            "title": "Проверка сохранения транзакции",
            "work_type_id": 1,
            "status": "completed",
            "visit_window_start": "2026-09-14T10:00:00+03:00",
            "visit_window_end": "2026-09-14T14:00:00+03:00",
            "estimated_duration_minutes": 60,
            "actual_duration_minutes": 75,
        }

    def test_post_is_committed_and_visible_to_an_independent_connection(self):
        response = self.client.post("/api/v1/tickets", json=self.payload, headers=self.auth_headers)
        self.assertEqual(response.status_code, 201, response.text)
        ticket_id = response.json()["id"]
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT title, location_id, status, actual_duration_minutes "
                        "FROM tickets WHERE id = :id"
                    ),
                    {"id": ticket_id},
                )
                .mappings()
                .one()
            )
        self.assertEqual(dict(row), {key: self.payload[key] for key in row})
        fetched = self.client.get(response.headers["Location"], headers=self.auth_headers)
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(fetched.json(), response.json())

    def test_failed_response_rolls_back_and_next_request_can_commit(self):
        with patch(
            "app.modules.tickets.service.get_ticket_unscoped", side_effect=RuntimeError("failed")
        ):
            failed = self.client.post(
                "/api/v1/tickets", json=self.payload, headers=self.auth_headers
            )
        self.assertEqual(failed.status_code, 500)
        with self.engine.connect() as connection:
            count = connection.execute(text("SELECT count(*) FROM tickets")).scalar_one()
        self.assertEqual(count, self.initial_ticket_count)

        response = self.client.post("/api/v1/tickets", json=self.payload, headers=self.auth_headers)
        self.assertEqual(response.status_code, 201, response.text)
        with self.engine.connect() as connection:
            count = connection.execute(text("SELECT count(*) FROM tickets")).scalar_one()
        self.assertEqual(count, self.initial_ticket_count + 1)

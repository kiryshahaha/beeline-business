"""Regression tests for the T13 access and token lifecycle requirements."""

import asyncio
import unittest
from threading import Barrier
from unittest.mock import patch

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.models import Building, City, District, Location, Street
from app.db.session import get_session
from app.main import app
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from tests.support import CommittedDatabaseTestCase, DatabaseTestCase


class TicketAndLocationAuthenticationTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        city = City(name="Тестовый город")
        self.session.add(city)
        self.session.flush()
        district = District(city_id=city.id, name="Тестовый район")
        self.session.add(district)
        self.session.flush()
        street = Street(city_id=city.id, name="Тестовая улица")
        self.session.add(street)
        self.session.flush()
        building = Building(
            city_id=city.id,
            district_id=district.id,
            street_id=street.id,
            number="1",
        )
        self.session.add(building)
        self.session.flush()
        location = Location(building_id=building.id)
        self.session.add(location)
        self.session.flush()
        self.location_id = location.id
        self.session.commit()

        self.observer = create_user(
            self.session,
            UserCreate(
                name="Тест",
                surname="Наблюдатель",
                username="t13_observer",
                password="Password123!",
                role=UserRole.OBSERVER,
            ),
        )
        self.worker = create_user(
            self.session,
            UserCreate(
                name="Исполнитель",
                surname="Тестовый",
                username="t13_worker",
                password="Password123!",
                role=UserRole.WORKER,
                worker_profile=WorkerProfileCreate(
                    workshift_start="09:00:00",
                    workshift_end="18:00:00",
                    skills=["Диагностика"],
                ),
            ),
        )
        self.foreman = create_user(
            self.session,
            UserCreate(
                name="Бригадир",
                surname="Тестовый",
                username="t13_foreman",
                password="Password123!",
                role=UserRole.FOREMAN,
            ),
        )
        self.session.commit()
        self.headers = {
            "Authorization": "Bearer "
            + create_access_token({"sub": str(self.observer.id), "role": "observer"})
        }

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))

    def ticket_payload(self):
        return {
            "location_id": self.location_id,
            "title": "Проверить соединение",
            "work_type_id": 1,
            "visit_window_start": "2026-09-24T10:00:00+03:00",
            "visit_window_end": "2026-09-24T14:00:00+03:00",
            "estimated_duration_minutes": 60,
        }

    def test_ticket_list_filters_detail_and_create_require_authentication(self):
        created = self.client.post(
            "/api/v1/tickets", json=self.ticket_payload(), headers=self.headers
        )
        self.assertEqual(created.status_code, 201, created.text)
        ticket_id = created.json()["id"]

        anonymous_requests = (
            self.client.get("/api/v1/tickets"),
            self.client.get("/api/v1/tickets", params={"city_id": 1, "status": "planned"}),
            self.client.get(f"/api/v1/tickets/{ticket_id}"),
            self.client.post("/api/v1/tickets", json=self.ticket_payload()),
        )
        for response in anonymous_requests:
            with self.subTest(path=response.request.url.path, method=response.request.method):
                self.assertEqual(response.status_code, 401, response.text)

    def test_address_creation_requires_observer_authentication(self):
        address = {
            "city": "Тестовый город",
            "district": "Тестовый район",
            "street": "Другая улица",
            "building_number": "2",
        }
        anonymous = self.client.post("/api/v1/location", json=address)
        self.assertEqual(anonymous.status_code, 401, anonymous.text)

        authorized = self.client.post("/api/v1/location", json=address, headers=self.headers)
        self.assertEqual(authorized.status_code, 201, authorized.text)

        for user in (self.worker, self.foreman):
            token = create_access_token({"sub": str(user.id), "role": user.role.value})
            denied = self.client.post(
                "/api/v1/location",
                json={**address, "street": f"Улица {user.username}"},
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(denied.status_code, 403, denied.text)

    def test_only_observer_can_create_tickets(self):
        for user in (self.worker, self.foreman):
            token = create_access_token({"sub": str(user.id), "role": user.role.value})
            denied = self.client.post(
                "/api/v1/tickets",
                json=self.ticket_payload(),
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(denied.status_code, 403, denied.text)


class ConcurrentRefreshRotationTests(CommittedDatabaseTestCase):
    def setUp(self):
        super().setUp()
        with Session(bind=self.engine) as session:
            self.user = create_user(
                session,
                UserCreate(
                    name="Параллельный",
                    surname="Вход",
                    username="t13_parallel_refresh",
                    password="Password123!",
                    role=UserRole.OBSERVER,
                ),
            )

        def override_session():
            with Session(bind=self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)

    def test_two_simultaneous_refreshes_create_only_one_active_successor(self):
        async def run_requests():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                login = await client.post(
                    "/api/v1/auth/login",
                    json={"username": self.user.username, "password": "Password123!"},
                )
                self.assertEqual(login.status_code, 200, login.text)
                refresh_token = login.cookies.get("refresh_token")
                self.assertIsNotNone(refresh_token)

                barrier = Barrier(2)
                from app.modules.auth import repository as auth_repository

                consume = auth_repository.consume_active_refresh_token

                def synchronized_consume(*args, **kwargs):
                    barrier.wait(timeout=10)
                    return consume(*args, **kwargs)

                with patch.object(
                    auth_repository,
                    "consume_active_refresh_token",
                    side_effect=synchronized_consume,
                ):
                    responses = await asyncio.gather(
                        *(
                            client.post(
                                "/api/v1/auth/refresh",
                                cookies={"refresh_token": refresh_token},
                            )
                            for _ in range(2)
                        )
                    )
                return responses

        responses = asyncio.run(run_requests())
        self.assertCountEqual([response.status_code for response in responses], [200, 401])
        successful = next(response for response in responses if response.status_code == 200)
        self.assertIsNotNone(successful.cookies.get("refresh_token"))
        failed = next(response for response in responses if response.status_code == 401)
        self.assertIsNone(failed.cookies.get("refresh_token"))

        with Session(bind=self.engine) as session:
            active_tokens = session.execute(
                text(
                    "SELECT count(*) FROM refresh_tokens "
                    "WHERE user_id = :user_id AND revoked_at IS NULL"
                ),
                {"user_id": self.user.id},
            ).scalar_one()
        self.assertEqual(active_tokens, 1)


if __name__ == "__main__":
    unittest.main()

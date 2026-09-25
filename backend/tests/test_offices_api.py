"""Integration tests for offices API."""

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.main import app
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from tests.support import DatabaseTestCase


class OfficesApiTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))

        self.observer = self.create_user("observer", UserRole.OBSERVER)
        self.worker = self.create_user("worker", UserRole.WORKER)

        # Create geographical hierarchy for tests
        city_id = self.connection.execute(
            text("INSERT INTO cities (name) VALUES ('Город') RETURNING id")
        ).scalar_one()
        street_id = self.connection.execute(
            text("INSERT INTO streets (name, city_id) VALUES ('Улица', :city_id) RETURNING id"),
            {"city_id": city_id},
        ).scalar_one()
        district_row_id = self.connection.execute(
            text("INSERT INTO districts (name, city_id) VALUES ('Район', :city_id) RETURNING id"),
            {"city_id": city_id},
        ).scalar_one()
        service_area_id = self.service_area_for_district(district_row_id)
        building_id = self.connection.execute(
            text(
                "INSERT INTO buildings (city_id, street_id, service_area_id, number) VALUES (:city_id, :street_id, :service_area_id, '1') RETURNING id"  # noqa: E501
            ),
            {"city_id": city_id, "street_id": street_id, "service_area_id": service_area_id},
        ).scalar_one()

        self.location_id = self.connection.execute(
            text("INSERT INTO locations (building_id) VALUES (:building_id) RETURNING id"),
            {"building_id": building_id},
        ).scalar_one()

        self.session.commit()

    def create_user(self, username: str, role: UserRole):
        worker_profile = None
        if role == UserRole.WORKER:
            worker_profile = WorkerProfileCreate(
                workshift_start="09:00:00",
                workshift_end="18:00:00",
                skills=["Монтаж"],
            )
        user_in = UserCreate(
            name=f"Имя {username}",
            surname=f"Фамилия {username}",
            username=username,
            password="Password123!",
            role=role,
            worker_profile=worker_profile,
        )
        return create_user(self.session, user_in)

    def _auth_headers(self, user) -> dict:
        response = self.client.post(
            "/api/v1/auth/login", json={"username": user.username, "password": "Password123!"}
        )
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def test_create_office_success(self):
        headers = self._auth_headers(self.observer)
        response = self.client.post(
            "/api/v1/offices/",
            json={"name": "Новый Офис", "location_id": self.location_id},
            headers=headers,
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("id", data)
        self.assertEqual(data["name"], "Новый Офис")
        self.assertEqual(data["location_id"], self.location_id)

    def test_create_office_duplicate_name(self):
        headers = self._auth_headers(self.observer)
        self.client.post(
            "/api/v1/offices/",
            json={"name": "Новый Офис", "location_id": self.location_id},
            headers=headers,
        )
        response = self.client.post(
            "/api/v1/offices/",
            json={"name": "Новый Офис", "location_id": self.location_id},
            headers=headers,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Офис с таким названием уже существует")

    def test_create_office_invalid_location(self):
        headers = self._auth_headers(self.observer)
        response = self.client.post(
            "/api/v1/offices/", json={"name": "Новый Офис", "location_id": 9999}, headers=headers
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Локация с таким ID не найдена")

    def test_list_offices(self):
        headers = self._auth_headers(self.observer)
        self.client.post(
            "/api/v1/offices/",
            json={"name": "Офис 1", "location_id": self.location_id},
            headers=headers,
        )
        self.client.post(
            "/api/v1/offices/",
            json={"name": "Офис 2", "location_id": self.location_id},
            headers=headers,
        )

        response = self.client.get("/api/v1/offices/", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["name"], "Офис 1")
        self.assertEqual(data[1]["name"], "Офис 2")

    def test_worker_cannot_create_office(self):
        headers = self._auth_headers(self.worker)
        response = self.client.post(
            "/api/v1/offices/",
            json={"name": "Новый Офис", "location_id": self.location_id},
            headers=headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_worker_can_list_offices(self):
        headers_obs = self._auth_headers(self.observer)
        self.client.post(
            "/api/v1/offices/",
            json={"name": "Офис 1", "location_id": self.location_id},
            headers=headers_obs,
        )

        headers_worker = self._auth_headers(self.worker)
        response = self.client.get("/api/v1/offices/", headers=headers_worker)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

    def test_get_office_success(self):
        headers = self._auth_headers(self.observer)
        create_resp = self.client.post(
            "/api/v1/offices/",
            json={"name": "Офис Для Чтения", "location_id": self.location_id},
            headers=headers,
        )
        office_id = create_resp.json()["id"]

        response = self.client.get(f"/api/v1/offices/{office_id}", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Офис Для Чтения")

    def test_get_office_not_found(self):
        headers = self._auth_headers(self.observer)
        response = self.client.get("/api/v1/offices/9999", headers=headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Офис не найден")

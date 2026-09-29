"""HTTP contracts for the locations API."""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.models import Building, City, District, Entrance, Location, Street
from app.db.session import get_session
from app.main import app
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate
from app.modules.users.service import create_user
from tests.support import DatabaseTestCase


class LocationsApiTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        observer = create_user(
            self.session,
            UserCreate(
                name="Тестовый",
                surname="Наблюдатель",
                username="locations_api_observer",
                password="Password123!",
                role=UserRole.OBSERVER,
            ),
        )
        self.session.commit()
        self.auth_headers = {
            "Authorization": "Bearer "
            + create_access_token({"sub": str(observer.id), "role": observer.role.value})
        }
        self.client = self.enterContext(TestClient(app, headers=self.auth_headers))

    def payload(self, **overrides):
        return {
            "city": "Москва",
            "district": "Кузьминки",
            "street": "улица Юных Ленинцев",
            "building_number": "44",
            "block": "корпус 1",
            "entrance_number": "1",
            "floor": 2,
            "apartment": "5",
            "latitude": 55.700654,
            "longitude": 37.759714,
        } | overrides

    def test_post_creates_full_address_hierarchy(self):
        response = self.client.post("/api/v1/location", json=self.payload())
        self.assertEqual(response.status_code, 201, response.text)
        created = response.json()

        self.assertIn("id", created)
        self.assertEqual(created["city"], "Москва")
        self.assertEqual(created["district"], "Кузьминки")
        self.assertEqual(created["street"], "улица Юных Ленинцев")
        self.assertEqual(created["building_number"], "44")
        self.assertEqual(created["block"], "корпус 1")
        self.assertEqual(created["entrance_number"], "1")
        self.assertEqual(created["floor"], 2)
        self.assertEqual(created["apartment"], "5")
        self.assertEqual(created["latitude"], 55.700654)
        self.assertEqual(created["longitude"], 37.759714)

        # Verify db counts
        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(City)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(District)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Street)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Building)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Entrance)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Location)), 1)

    def test_post_existing_location_does_not_create_duplicates(self):
        # First call
        response1 = self.client.post("/api/v1/location", json=self.payload())
        self.assertEqual(response1.status_code, 201)
        id1 = response1.json()["id"]

        # Second call with the exact same data
        response2 = self.client.post("/api/v1/location", json=self.payload())
        self.assertEqual(response2.status_code, 201)
        id2 = response2.json()["id"]

        self.assertEqual(id1, id2)

        # Verify db counts remain 1 for each level
        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(City)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(District)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Street)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Building)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Entrance)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Location)), 1)

    def test_post_missing_required_field_returns_422(self):
        payload = self.payload()
        del payload["city"]
        response = self.client.post("/api/v1/location", json=payload)
        self.assertEqual(response.status_code, 422)

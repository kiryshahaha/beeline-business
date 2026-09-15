"""HTTP contracts for the locations API."""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Building, City, District, Entrance, Location, Street
from app.db.session import get_session
from app.main import app
from tests.support import DatabaseTestCase


class LocationsApiTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))

    def payload(self, **overrides):
        return {
            "city": "Санкт-Петербург",
            "district": "Невский район",
            "street": "Искровский проспект",
            "building_number": "4",
            "block": "корпус 2",
            "entrance_number": "1",
            "floor": 3,
            "apartment": "12",
            "latitude": 59.9156,
            "longitude": 30.4631,
        } | overrides

    def test_post_creates_full_address_hierarchy(self):
        response = self.client.post("/api/v1/location", json=self.payload())
        self.assertEqual(response.status_code, 201, response.text)
        created = response.json()

        self.assertIn("id", created)
        self.assertEqual(created["city"], "Санкт-Петербург")
        self.assertEqual(created["district"], "Невский район")
        self.assertEqual(created["street"], "Искровский проспект")
        self.assertEqual(created["building_number"], "4")
        self.assertEqual(created["block"], "корпус 2")
        self.assertEqual(created["entrance_number"], "1")
        self.assertEqual(created["floor"], 3)
        self.assertEqual(created["apartment"], "12")
        self.assertEqual(created["latitude"], 59.9156)
        self.assertEqual(created["longitude"], 30.4631)

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

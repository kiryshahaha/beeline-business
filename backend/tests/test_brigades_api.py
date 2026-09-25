"""Integration coverage for brigade management and read visibility."""

from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.main import app
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from tests.support import DatabaseTestCase


class BrigadesApiTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))
        self.observer = self.create_user("observer", UserRole.OBSERVER)
        self.foreman_one = self.create_user("foreman_one", UserRole.FOREMAN)
        self.foreman_two = self.create_user("foreman_two", UserRole.FOREMAN)
        self.worker_one = self.create_user("worker_one", UserRole.WORKER)
        self.worker_two = self.create_user("worker_two", UserRole.WORKER)
        self.worker_three = self.create_user("worker_three", UserRole.WORKER)

        # Create geographical hierarchy and an office for tests
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
        location_id = self.connection.execute(
            text("INSERT INTO locations (building_id) VALUES (:building_id) RETURNING id"),
            {"building_id": building_id},
        ).scalar_one()
        self.office_id = self.connection.execute(
            text(
                "INSERT INTO offices (name, location_id) VALUES ('Офис 1', :location_id) RETURNING id"  # noqa: E501
            ),
            {"location_id": location_id},
        ).scalar_one()

        self.session.commit()

    def create_user(self, username: str, role: UserRole):
        worker_profile = None
        if role == UserRole.WORKER:
            worker_profile = WorkerProfileCreate(
                workshift_start="09:00:00",
                workshift_end="18:00:00",
                skills=["Монтаж ВОЛС"],
            )
        return create_user(
            self.session,
            UserCreate(
                name=username,
                surname="Тестов",
                username=username,
                password="StrongPassword123!",
                role=role,
                worker_profile=worker_profile,
            ),
        )

    def auth_header(self, username: str) -> dict[str, str]:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": "StrongPassword123!"},
        )
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def create_brigade(self, name: str, foreman_id: int, worker_ids: list[int]) -> dict:
        response = self.client.post(
            "/api/v1/brigades",
            json={
                "name": name,
                "foreman_id": foreman_id,
                "office_id": self.office_id,
                "worker_ids": worker_ids,
            },
            headers=self.auth_header("observer"),
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_observer_creates_brigade_and_duplicate_name_returns_conflict(self):
        brigade = self.create_brigade(
            "Север", self.foreman_one.id, [self.worker_one.id, self.worker_two.id]
        )
        self.assertEqual(brigade["name"], "Север")
        self.assertEqual(brigade["foreman_id"], self.foreman_one.id)
        self.assertCountEqual(brigade["worker_ids"], [self.worker_one.id, self.worker_two.id])

        duplicate = self.client.post(
            "/api/v1/brigades",
            json={
                "name": "север",
                "foreman_id": self.foreman_two.id,
                "office_id": self.office_id,
                "worker_ids": [],
            },
            headers=self.auth_header("observer"),
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_creation_rejects_non_foreman_and_unknown_worker(self):
        non_foreman = self.client.post(
            "/api/v1/brigades",
            json={
                "name": "Неверный",
                "foreman_id": self.worker_one.id,
                "office_id": self.office_id,
                "worker_id": None,
            },
            headers=self.auth_header("observer"),
        )
        self.assertEqual(non_foreman.status_code, 422)

        unknown_worker = self.client.post(
            "/api/v1/brigades",
            json={
                "name": "Неизвестный работник",
                "foreman_id": self.foreman_one.id,
                "office_id": self.office_id,
                "worker_ids": [999_999],
            },
            headers=self.auth_header("observer"),
        )
        self.assertEqual(unknown_worker.status_code, 422)

    def test_creation_and_replacement_lock_foreman_role_before_writing(self):
        role_queries = []

        def capture_role_query(connection, cursor, statement, parameters, context, executemany):
            normalized = " ".join(statement.upper().split())
            if normalized.startswith("SELECT ROLE FROM USERS WHERE ID ="):
                role_queries.append(normalized)

        event.listen(self.connection, "before_cursor_execute", capture_role_query)
        self.addCleanup(event.remove, self.connection, "before_cursor_execute", capture_role_query)
        brigade = self.create_brigade("Север", self.foreman_one.id, [self.worker_one.id])
        replaced = self.client.put(
            f"/api/v1/brigades/{brigade['id']}/members",
            json={
                "foreman_id": self.foreman_two.id,
                "office_id": self.office_id,
                "worker_ids": [self.worker_two.id],
            },
            headers=self.auth_header("observer"),
        )

        self.assertEqual(replaced.status_code, 200)
        self.assertEqual(replaced.json()["foreman_id"], self.foreman_two.id)
        self.assertEqual(len(role_queries), 2)
        self.assertTrue(all(query.endswith("FOR UPDATE") for query in role_queries))

        invalid = self.client.put(
            f"/api/v1/brigades/{brigade['id']}/members",
            json={
                "foreman_id": self.worker_three.id,
                "office_id": self.office_id,
                "worker_id": None,
            },
            headers=self.auth_header("observer"),
        )
        self.assertEqual(invalid.status_code, 422)
        unchanged = self.client.get(
            f"/api/v1/brigades/{brigade['id']}", headers=self.auth_header("observer")
        )
        self.assertEqual(unchanged.json()["foreman_id"], self.foreman_two.id)
        self.assertEqual(unchanged.json()["worker_ids"], [self.worker_two.id])

    def test_observer_replaces_members_and_rejects_occupied_member(self):
        brigade_one = self.create_brigade("Север", self.foreman_one.id, [self.worker_one.id])
        self.create_brigade("Юг", self.foreman_two.id, [self.worker_three.id])

        replaced = self.client.put(
            f"/api/v1/brigades/{brigade_one['id']}/members",
            json={
                "foreman_id": self.foreman_one.id,
                "office_id": self.office_id,
                "worker_ids": [self.worker_two.id],
            },
            headers=self.auth_header("observer"),
        )
        self.assertEqual(replaced.status_code, 200)
        self.assertEqual(replaced.json()["worker_ids"], [self.worker_two.id])

        occupied = self.client.put(
            f"/api/v1/brigades/{brigade_one['id']}/members",
            json={
                "foreman_id": self.foreman_one.id,
                "office_id": self.office_id,
                "worker_ids": [self.worker_three.id],
            },
            headers=self.auth_header("observer"),
        )
        self.assertEqual(occupied.status_code, 409)

    def test_brigade_reads_are_scoped_by_role(self):
        brigade_one = self.create_brigade("Север", self.foreman_one.id, [self.worker_one.id])
        brigade_two = self.create_brigade("Юг", self.foreman_two.id, [self.worker_three.id])

        observer_list = self.client.get("/api/v1/brigades", headers=self.auth_header("observer"))
        self.assertEqual(observer_list.status_code, 200)
        self.assertCountEqual(
            [item["id"] for item in observer_list.json()],
            [brigade_one["id"], brigade_two["id"]],
        )

        foreman_list = self.client.get("/api/v1/brigades", headers=self.auth_header("foreman_one"))
        self.assertEqual(foreman_list.status_code, 200)
        self.assertEqual([item["id"] for item in foreman_list.json()], [brigade_one["id"]])

        worker_list = self.client.get("/api/v1/brigades", headers=self.auth_header("worker_three"))
        self.assertEqual(worker_list.status_code, 200)
        self.assertEqual([item["id"] for item in worker_list.json()], [brigade_two["id"]])

        hidden = self.client.get(
            f"/api/v1/brigades/{brigade_two['id']}",
            headers=self.auth_header("foreman_one"),
        )
        self.assertEqual(hidden.status_code, 404)

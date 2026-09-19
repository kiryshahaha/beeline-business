"""Work type reference: seeded organizer norms, read API and database constraints."""

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.main import app
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from tests.support import DatabaseTestCase

EXPECTED_NORMS = [
    ("Подключение клиентов Базовая", 20, 60, 10, 90),
    ("Аварий на ТКД", 20, 80, 0, 100),
    ("Дозаказ оборудования", 20, 10, 10, 40),
    ("Локальная заявка/ремонт у клиента", 20, 30, 0, 50),
]


class WorkTypesApiTests(DatabaseTestCase):
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
        self.session.commit()

    def create_user(self, username: str, role: UserRole):
        worker_profile = None
        if role == UserRole.WORKER:
            worker_profile = WorkerProfileCreate(
                workshift_start="09:00:00", workshift_end="18:00:00", skills=["Монтаж"]
            )
        return create_user(
            self.session,
            UserCreate(
                name=f"Имя {username}",
                surname=f"Фамилия {username}",
                username=username,
                password="Password123!",
                role=role,
                worker_profile=worker_profile,
            ),
        )

    def auth_headers(self, user) -> dict[str, str]:
        response = self.client.post(
            "/api/v1/auth/login", json={"username": user.username, "password": "Password123!"}
        )
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def insert_work_type(self, name: str, travel: int, work: int, documents: int) -> int:
        return self.connection.execute(
            text("""
                INSERT INTO work_types (name, travel_minutes, work_minutes, documents_minutes)
                VALUES (:name, :travel, :work, :documents)
                RETURNING id
            """),
            {"name": name, "travel": travel, "work": work, "documents": documents},
        ).scalar_one()

    def test_migration_seeds_organizer_norms_in_file_order(self):
        response = self.client.get("/api/v1/work-types", headers=self.auth_headers(self.observer))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [
                (
                    item["name"],
                    item["travel_minutes"],
                    item["work_minutes"],
                    item["documents_minutes"],
                    item["norm_minutes"],
                )
                for item in response.json()
            ],
            EXPECTED_NORMS,
        )
        ids = [item["id"] for item in response.json()]
        self.assertEqual(ids, sorted(ids))

    def test_worker_reads_one_work_type(self):
        headers = self.auth_headers(self.worker)
        work_type_id = self.client.get("/api/v1/work-types", headers=headers).json()[1]["id"]

        response = self.client.get(f"/api/v1/work-types/{work_type_id}", headers=headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Аварий на ТКД")
        self.assertEqual(response.json()["norm_minutes"], 100)

    def test_missing_work_type_returns_404(self):
        response = self.client.get(
            "/api/v1/work-types/2147483647", headers=self.auth_headers(self.observer)
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Вид работ не найден")

    def test_invalid_id_returns_422(self):
        headers = self.auth_headers(self.observer)

        for work_type_id in ("0", "2147483648", "abc"):
            with self.subTest(work_type_id=work_type_id):
                response = self.client.get(f"/api/v1/work-types/{work_type_id}", headers=headers)
                self.assertEqual(response.status_code, 422)

    def test_reading_requires_authorization(self):
        for path in ("/api/v1/work-types", "/api/v1/work-types/1"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)

    def test_database_computes_norm_from_parts(self):
        work_type_id = self.insert_work_type("Выезд без документов", 15, 25, 0)

        norm = self.connection.execute(
            text("SELECT norm_minutes FROM work_types WHERE id = :id"), {"id": work_type_id}
        ).scalar_one()

        self.assertEqual(norm, 40)

    def test_database_rejects_invalid_rows(self):
        invalid_rows = (
            ("  ", 20, 60, 10),
            (" Пробел по краям", 20, 60, 10),
            ("Отрицательная дорога", -1, 60, 10),
            ("Отрицательные работы", 20, -1, 10),
            ("Отрицательные документы", 20, 60, -1),
            ("Нулевой норматив", 0, 0, 0),
            ("дОЗАКАЗ ОБОРУДОВАНИЯ", 20, 10, 10),
        )
        for row in invalid_rows:
            with self.subTest(row=row):
                savepoint = self.connection.begin_nested()
                with self.assertRaises(IntegrityError):
                    self.insert_work_type(*row)
                savepoint.rollback()

    def test_norm_cannot_be_written_directly(self):
        savepoint = self.connection.begin_nested()
        with self.assertRaises(ProgrammingError):
            self.connection.execute(
                text("UPDATE work_types SET norm_minutes = 1 WHERE name = 'Аварий на ТКД'")
            )
        savepoint.rollback()

    def create(self, user=None, **overrides):
        payload = {
            "name": "Монтаж СКС",
            "travel_minutes": 20,
            "work_minutes": 120,
            "documents_minutes": 15,
        } | overrides
        return self.client.post(
            "/api/v1/work-types", json=payload, headers=self.auth_headers(user or self.observer)
        )

    def patch(self, work_type_id, payload, user=None):
        return self.client.patch(
            f"/api/v1/work-types/{work_type_id}",
            json=payload,
            headers=self.auth_headers(user or self.observer),
        )

    def seeded_id(self, name):
        return self.connection.execute(
            text("SELECT id FROM work_types WHERE name = :name"), {"name": name}
        ).scalar_one()

    def test_observer_creates_work_type_and_database_computes_norm(self):
        response = self.create(name="  Монтаж СКС  ")

        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        self.assertEqual(response.headers["location"], f"/api/v1/work-types/{data['id']}")
        self.assertEqual(
            {key: value for key, value in data.items() if key != "id"},
            {
                "name": "Монтаж СКС",
                "travel_minutes": 20,
                "work_minutes": 120,
                "documents_minutes": 15,
                "norm_minutes": 155,
            },
        )
        listed = self.client.get("/api/v1/work-types", headers=self.auth_headers(self.worker))
        self.assertEqual(listed.json()[-1], data)

    def test_create_rejects_duplicate_name_in_any_case(self):
        for name in ("Аварий на ТКД", "аварий НА ткд"):
            with self.subTest(name=name):
                response = self.create(name=name)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(
                    response.json()["detail"], "Вид работ с таким названием уже существует"
                )

    def test_create_validates_payload(self):
        for overrides in (
            {"name": "   "},
            {"name": "x" * 101},
            {"name": "text\x00text"},
            {"travel_minutes": -1},
            {"work_minutes": 1441},
            {"documents_minutes": "10"},
            {"documents_minutes": 1.5},
            {"travel_minutes": 0, "work_minutes": 0, "documents_minutes": 0},
            {"norm_minutes": 90},
        ):
            with self.subTest(overrides=overrides):
                self.assertEqual(self.create(**overrides).status_code, 422)
        response = self.client.post(
            "/api/v1/work-types",
            json={"name": "Без минут"},
            headers=self.auth_headers(self.observer),
        )
        self.assertEqual(response.status_code, 422)

    def test_observer_updates_only_passed_fields(self):
        work_type_id = self.seeded_id("Дозаказ оборудования")

        response = self.patch(work_type_id, {"work_minutes": 25})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {
                "id": work_type_id,
                "name": "Дозаказ оборудования",
                "travel_minutes": 20,
                "work_minutes": 25,
                "documents_minutes": 10,
                "norm_minutes": 55,
            },
        )

    def test_update_renames_and_allows_changing_case_of_own_name(self):
        work_type_id = self.seeded_id("Аварий на ТКД")

        response = self.patch(work_type_id, {"name": "Авария на ТКД"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "Авария на ТКД")

        response = self.patch(work_type_id, {"name": "АВАРИЯ НА ТКД"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "АВАРИЯ НА ТКД")

    def test_update_rejects_name_of_another_work_type(self):
        response = self.patch(self.seeded_id("Аварий на ТКД"), {"name": "дозаказ оборудования"})

        self.assertEqual(response.status_code, 409)

    def test_update_rejects_zero_norm_and_invalid_payload(self):
        work_type_id = self.seeded_id("Локальная заявка/ремонт у клиента")

        response = self.patch(work_type_id, {"travel_minutes": 0, "work_minutes": 0})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "Норматив должен быть больше нуля")
        for payload in (
            {},
            {"name": None},
            {"work_minutes": None},
            {"work_minutes": -5},
            {"norm_minutes": 10},
            {"unknown": 1},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.patch(work_type_id, payload).status_code, 422)
        unchanged = self.client.get(
            f"/api/v1/work-types/{work_type_id}", headers=self.auth_headers(self.observer)
        )
        self.assertEqual(unchanged.json()["norm_minutes"], 50)

    def test_update_missing_work_type_returns_404(self):
        response = self.patch(2_147_483_647, {"work_minutes": 10})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Вид работ не найден")

    def test_only_observer_creates_and_updates(self):
        work_type_id = self.seeded_id("Дозаказ оборудования")
        self.assertEqual(self.create(user=self.worker).status_code, 403)
        self.assertEqual(
            self.patch(work_type_id, {"work_minutes": 5}, self.worker).status_code, 403
        )
        self.assertEqual(self.client.post("/api/v1/work-types", json={}).status_code, 401)
        self.assertEqual(
            self.client.patch(f"/api/v1/work-types/{work_type_id}", json={}).status_code, 401
        )

"""HTTP coverage for brigade workload analytics and role-based visibility."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.tickets.enums import TicketStatus
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from tests.support import DatabaseTestCase


class BrigadesWorkloadApiTests(DatabaseTestCase):
    """Exercise workload aggregation against an isolated PostgreSQL schema."""

    def setUp(self):
        super().setUp()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_current_user] = lambda: self.current_user
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.addCleanup(lambda: app.dependency_overrides.pop(get_current_user, None))
        self.client = self.enterContext(TestClient(app))

        self.observer = self.create_user("observer", UserRole.OBSERVER)
        self.foreman_one = self.create_user("foreman_one", UserRole.FOREMAN)
        self.foreman_two = self.create_user("foreman_two", UserRole.FOREMAN)
        self.foreman_without_brigade = self.create_user("foreman_three", UserRole.FOREMAN)
        self.foreman_empty = self.create_user("foreman_empty", UserRole.FOREMAN)
        self.worker_one = self.create_user("worker_one", UserRole.WORKER)
        self.worker_two = self.create_user("worker_two", UserRole.WORKER)

        location_id = self.connection.execute(
            text("INSERT INTO locations (building_id) VALUES (:building_id) RETURNING id"),
            {"building_id": self.create_building()},
        ).scalar_one()
        office_id = self.connection.execute(
            text(
                "INSERT INTO offices (name, location_id) "
                "VALUES ('Офис аналитики', :location_id) RETURNING id"
            ),
            {"location_id": location_id},
        ).scalar_one()
        self.brigade_one = self.create_brigade(
            "Альфа", self.foreman_one.id, office_id, self.worker_one.id
        )
        self.brigade_two = self.create_brigade(
            "Бета", self.foreman_two.id, office_id, self.worker_two.id
        )
        self.brigade_empty = self.connection.execute(
            text(
                "INSERT INTO brigades (name, foreman_id, office_id) "
                "VALUES ('Пустая', :foreman_id, :office_id) RETURNING id"
            ),
            {"foreman_id": self.foreman_empty.id, "office_id": office_id},
        ).scalar_one()
        self.connection.execute(
            text("DELETE FROM brigade_members WHERE brigade_id = :brigade_id"),
            {"brigade_id": self.brigade_empty},
        )
        self.session.commit()
        self.seed_tickets(location_id)
        self.session.commit()
        self.current_user = self.observer

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

    def create_building(self) -> int:
        city_id = self.connection.execute(
            text("INSERT INTO cities (name) VALUES ('Город') RETURNING id")
        ).scalar_one()
        street_id = self.connection.execute(
            text("INSERT INTO streets (name, city_id) VALUES ('Улица', :city_id) RETURNING id"),
            {"city_id": city_id},
        ).scalar_one()
        district_id = self.connection.execute(
            text("INSERT INTO districts (name, city_id) VALUES ('Район', :city_id) RETURNING id"),
            {"city_id": city_id},
        ).scalar_one()
        return self.connection.execute(
            text(
                "INSERT INTO buildings (city_id, street_id, district_id, number) "
                "VALUES (:city_id, :street_id, :district_id, '1') RETURNING id"
            ),
            {"city_id": city_id, "street_id": street_id, "district_id": district_id},
        ).scalar_one()

    def create_brigade(self, name: str, foreman_id: int, office_id: int, worker_id: int) -> int:
        brigade_id = self.connection.execute(
            text(
                "INSERT INTO brigades (name, foreman_id, office_id) "
                "VALUES (:name, :foreman_id, :office_id) RETURNING id"
            ),
            {"name": name, "foreman_id": foreman_id, "office_id": office_id},
        ).scalar_one()
        self.connection.execute(
            text(
                "INSERT INTO brigade_members (brigade_id, worker_id) "
                "VALUES (:brigade_id, :worker_id)"
            ),
            {"brigade_id": brigade_id, "worker_id": worker_id},
        )
        return brigade_id

    def add_ticket(
        self,
        location_id: int,
        status: TicketStatus,
        created_at: datetime,
        worker_id: int | None = None,
        updated_at: datetime | None = None,
    ) -> int:
        updated_at = updated_at or created_at
        ticket_id = self.connection.execute(
            text(
                "INSERT INTO tickets ("
                "location_id, title, work_type, status, visit_window_start, "
                "visit_window_end, estimated_duration_minutes, created_at, updated_at"
                ") VALUES ("
                ":location_id, :title, 'Настройка сети', :status, :visit_start, "
                ":visit_end, 60, :created_at, :updated_at"
                ") RETURNING id"
            ),
            {
                "location_id": location_id,
                "title": f"Заявка {status.value} {created_at.timestamp()}",
                "status": status.value,
                "visit_start": created_at,
                "visit_end": created_at + timedelta(hours=1),
                "created_at": created_at,
                "updated_at": updated_at,
            },
        ).scalar_one()
        if worker_id is not None:
            self.connection.execute(
                text("UPDATE tickets SET assigned_worker_id = :worker_id WHERE id = :ticket_id"),
                {"ticket_id": ticket_id, "worker_id": worker_id},
            )
        return ticket_id

    def seed_tickets(self, location_id: int) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        self.add_ticket(location_id, TicketStatus.PLANNED, now, self.worker_one.id)
        self.add_ticket(location_id, TicketStatus.IN_PROGRESS, now, self.worker_one.id)
        self.add_ticket(location_id, TicketStatus.COMPLETED, now, self.worker_one.id)
        self.add_ticket(
            location_id,
            TicketStatus.COMPLETED,
            now - timedelta(days=40),
            self.worker_one.id,
        )
        self.add_ticket(location_id, TicketStatus.PLANNED, now, self.worker_two.id)
        self.add_ticket(
            location_id,
            TicketStatus.COMPLETED,
            now - timedelta(days=2),
            self.worker_two.id,
            updated_at=now,
        )

    def test_observer_sees_workload_for_all_brigades(self):
        self.current_user = self.observer

        response = self.client.get("/api/v1/analytics/brigades-workload")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            [
                {"brigade_name": "Альфа", "active_tickets": 2, "completed_today": 1},
                {"brigade_name": "Бета", "active_tickets": 1, "completed_today": 1},
                {"brigade_name": "Пустая", "active_tickets": 0, "completed_today": 0},
            ],
        )

    def test_foreman_sees_only_own_brigade(self):
        self.current_user = self.foreman_one

        response = self.client.get("/api/v1/analytics/brigades-workload")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            [{"brigade_name": "Альфа", "active_tickets": 2, "completed_today": 1}],
        )

    def test_foreman_without_brigade_gets_empty_list(self):
        self.current_user = self.foreman_without_brigade

        response = self.client.get("/api/v1/analytics/brigades-workload")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

    def test_worker_is_forbidden_and_missing_token_is_unauthorized(self):
        self.current_user = self.worker_one
        forbidden = self.client.get("/api/v1/analytics/brigades-workload")
        self.assertEqual(forbidden.status_code, 403)

        app.dependency_overrides.pop(get_current_user, None)
        unauthorized = self.client.get("/api/v1/analytics/brigades-workload")
        self.assertEqual(unauthorized.status_code, 401)

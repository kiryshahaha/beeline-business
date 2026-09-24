"""HTTP coverage for ticket status summaries and role-based scoping."""

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


class TicketsSummaryApiTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_current_user] = lambda: self.current_user
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.addCleanup(app.dependency_overrides.pop, get_current_user)
        self.client = self.enterContext(TestClient(app))

        self.observer = self.create_user("observer", UserRole.OBSERVER)
        self.foreman_one = self.create_user("foreman_one", UserRole.FOREMAN)
        self.foreman_two = self.create_user("foreman_two", UserRole.FOREMAN)
        self.foreman_without_brigade = self.create_user("foreman_three", UserRole.FOREMAN)
        self.worker_one = self.create_user("worker_one", UserRole.WORKER)
        self.worker_two = self.create_user("worker_two", UserRole.WORKER)

        location_id = self.connection.execute(
            text("INSERT INTO locations (building_id) VALUES (:building_id) RETURNING id"),
            {"building_id": self.create_building()},
        ).scalar_one()
        self.office_one = self.connection.execute(
            text(
                "INSERT INTO offices (name, location_id) "
                "VALUES ('Офис 1', :location_id) RETURNING id"
            ),
            {"location_id": location_id},
        ).scalar_one()
        self.office_two = self.connection.execute(
            text(
                "INSERT INTO offices (name, location_id) "
                "VALUES ('Офис 2', :location_id) RETURNING id"
            ),
            {"location_id": location_id},
        ).scalar_one()
        self.brigade_one = self.create_brigade(
            "Север", self.foreman_one.id, self.office_one, self.worker_one.id
        )
        self.brigade_two = self.create_brigade(
            "Юг", self.foreman_two.id, self.office_two, self.worker_two.id
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
    ) -> int:
        ticket_id = self.connection.execute(
            text(
                "INSERT INTO tickets ("
                "location_id, title, work_type, status, visit_window_start, "
                "visit_window_end, estimated_duration_minutes, created_at, updated_at"
                ") VALUES ("
                ":location_id, :title, 'Настройка сети', :status, :visit_start, "
                ":visit_end, 60, :created_at, :created_at"
                ") RETURNING id"
            ),
            {
                "location_id": location_id,
                "title": f"Заявка {status.value} {created_at.timestamp()}",
                "status": status.value,
                "visit_start": created_at,
                "visit_end": created_at + timedelta(hours=1),
                "created_at": created_at,
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
        self.add_ticket(location_id, TicketStatus.PLANNED, now)
        self.add_ticket(location_id, TicketStatus.PLANNED, now, self.worker_one.id)
        self.add_ticket(location_id, TicketStatus.IN_PROGRESS, now, self.worker_one.id)
        self.add_ticket(location_id, TicketStatus.COMPLETED, now, self.worker_one.id)
        self.add_ticket(location_id, TicketStatus.PLANNED, now, self.worker_two.id)
        self.add_ticket(
            location_id,
            TicketStatus.COMPLETED,
            now - timedelta(days=40),
            self.worker_one.id,
        )

    def test_observer_counts_all_recent_tickets(self):
        self.current_user = self.observer
        response = self.client.get("/api/v1/analytics/tickets-summary?period=month")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {"open": 1, "assigned": 2, "in_progress": 1, "completed": 1},
        )

    def test_all_supported_periods_return_summary(self):
        self.current_user = self.observer
        for period in ("today", "week", "month"):
            with self.subTest(period=period):
                response = self.client.get(f"/api/v1/analytics/tickets-summary?period={period}")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(
                    set(response.json()), {"open", "assigned", "in_progress", "completed"}
                )

    def test_observer_office_filter_uses_assigned_brigade_office(self):
        self.current_user = self.observer
        response = self.client.get(
            f"/api/v1/analytics/tickets-summary?period=month&office_id={self.office_one}"
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {"open": 0, "assigned": 1, "in_progress": 1, "completed": 1},
        )

    def test_foreman_scope_ignores_requested_office(self):
        self.current_user = self.foreman_one
        response = self.client.get(
            f"/api/v1/analytics/tickets-summary?period=month&office_id={self.office_two}"
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {"open": 0, "assigned": 1, "in_progress": 1, "completed": 1},
        )

    def test_foreman_without_brigade_gets_zero_summary(self):
        self.current_user = self.foreman_without_brigade
        response = self.client.get("/api/v1/analytics/tickets-summary?period=today")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {"open": 0, "assigned": 0, "in_progress": 0, "completed": 0},
        )

    def test_worker_is_forbidden_and_invalid_period_is_rejected(self):
        self.current_user = self.worker_one
        forbidden = self.client.get("/api/v1/analytics/tickets-summary?period=today")
        self.assertEqual(forbidden.status_code, 403)

        self.current_user = self.observer
        invalid = self.client.get("/api/v1/analytics/tickets-summary?period=year")
        self.assertEqual(invalid.status_code, 422)

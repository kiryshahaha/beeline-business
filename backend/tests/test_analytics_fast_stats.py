"""HTTP coverage for fast stats and role-based scoping."""

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


class FastStatsApiTests(DatabaseTestCase):
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

        # Mark worker_one as offline, worker_two as online
        self.connection.execute(
            text("UPDATE workers SET is_on_line = FALSE WHERE user_id = :w"),
            {"w": self.worker_one.id},
        )
        self.connection.execute(
            text("UPDATE workers SET is_on_line = TRUE WHERE user_id = :w"),
            {"w": self.worker_two.id},
        )
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
        district_row_id = self.connection.execute(
            text("INSERT INTO districts (name, city_id) VALUES ('Район', :city_id) RETURNING id"),
            {"city_id": city_id},
        ).scalar_one()
        service_area_id = self.service_area_for_district(district_row_id)
        return self.connection.execute(
            text(
                "INSERT INTO buildings (city_id, street_id, service_area_id, number) "
                "VALUES (:city_id, :street_id, :service_area_id, '1') RETURNING id"
            ),
            {"city_id": city_id, "street_id": street_id, "service_area_id": service_area_id},
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
        visit_end_offset: int = 1,
        actual_started_offset: int | None = None,
    ) -> int:
        visit_start = created_at
        visit_end = created_at + timedelta(hours=visit_end_offset)

        actual_started_at = None
        if actual_started_offset is not None:
            actual_started_at = created_at + timedelta(hours=actual_started_offset)

        ticket_id = self.connection.execute(
            text(
                "INSERT INTO tickets ("
                "location_id, title, work_type, status, visit_window_start, "
                "visit_window_end, estimated_duration_minutes, created_at, "
                "updated_at, actual_started_at"
                ") VALUES ("
                ":location_id, :title, 'Настройка сети', :status, :visit_start, "
                ":visit_end, 60, :created_at, :created_at, :actual_started_at"
                ") RETURNING id"
            ),
            {
                "location_id": location_id,
                "title": f"Заявка {status.value} {created_at.timestamp()}",
                "status": status.value,
                "visit_start": visit_start,
                "visit_end": visit_end,
                "created_at": created_at,
                "actual_started_at": actual_started_at,
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
        # Compliant ticket
        self.add_ticket(location_id, TicketStatus.COMPLETED, now)
        # Delayed ticket (planned but overdue)
        past_time = now - timedelta(hours=2)
        self.delayed_ticket_id = self.add_ticket(
            location_id, TicketStatus.PLANNED, past_time, visit_end_offset=1
        )

    def test_observer_sees_fast_stats(self):
        self.current_user = self.observer
        response = self.client.get("/api/v1/analytics/fast-stats")

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertIn("sla_compliance_percent", data)
        self.assertIn("at_risk_tickets_count", data)
        self.assertIn("average_delay_minutes", data)
        self.assertIn("idle_workers_count", data)
        self.assertIn("at_risk_tickets_ids", data)
        self.assertIn("idle_workers_ids", data)
        self.assertIn("active_brigades_count", data)

        self.assertEqual(data["at_risk_tickets_count"], 1)
        self.assertEqual(data["at_risk_tickets_ids"], [self.delayed_ticket_id])

        # worker_two is online but has no tickets, worker_one is offline
        self.assertEqual(data["idle_workers_count"], 1)
        self.assertEqual(data["idle_workers_ids"], [self.worker_two.id])

        # 2 brigades created
        self.assertEqual(data["active_brigades_count"], 2)

    def test_foreman_without_brigade_gets_zero_fast_stats(self):
        self.current_user = self.foreman_without_brigade
        response = self.client.get("/api/v1/analytics/fast-stats")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {
                "sla_compliance_percent": 100,
                "at_risk_tickets_count": 0,
                "average_delay_minutes": 0,
                "idle_workers_count": 0,
                "at_risk_tickets_ids": [],
                "idle_workers_ids": [],
                "active_brigades_count": 0,
            },
        )

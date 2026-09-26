"""Ticket summary: current queue, created, completed and planned are different numbers."""

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.main import app
from app.modules.analytics.schemas import AnalyticsPeriod
from app.modules.analytics.service import get_tickets_summary
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
        *,
        completed_at: datetime | None = None,
        updated_at: datetime | None = None,
        planned_start_at: datetime | None = None,
    ) -> int:
        return self.connection.execute(
            text(
                "INSERT INTO tickets ("
                "location_id, title, work_type, status, visit_window_start, visit_window_end, "
                "estimated_duration_minutes, assigned_worker_id, actual_completed_at, "
                "planned_start_at, planned_end_at, created_at, updated_at"
                ") VALUES ("
                ":location_id, :title, 'Настройка сети', :status, :created_at, :window_end, "
                "60, :worker_id, :completed_at, :planned_start, :planned_end, :created_at, "
                ":updated_at"
                ") RETURNING id"
            ),
            {
                "location_id": location_id,
                "title": f"Заявка {status.value} {created_at.timestamp()}",
                "status": status.value,
                "created_at": created_at,
                "window_end": created_at + timedelta(hours=1),
                "worker_id": worker_id,
                "completed_at": completed_at,
                "planned_start": planned_start_at,
                "planned_end": planned_start_at + timedelta(hours=1) if planned_start_at else None,
                "updated_at": updated_at or created_at,
            },
        ).scalar_one()

    def seed_tickets(self, location_id: int) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        self.now = now
        # Open queue opened long ago: it must not vanish from a "today" board (A31).
        self.add_ticket(location_id, TicketStatus.PLANNED, now - timedelta(days=40))
        self.add_ticket(location_id, TicketStatus.PLANNED, now, self.worker_one.id)
        self.add_ticket(location_id, TicketStatus.IN_PROGRESS, now, self.worker_one.id)
        self.add_ticket(
            location_id, TicketStatus.COMPLETED, now, self.worker_one.id, completed_at=now
        )
        self.add_ticket(location_id, TicketStatus.PLANNED, now, self.worker_two.id)
        # Closed forty days ago and edited today: an edit is not a completion (A31).
        self.add_ticket(
            location_id,
            TicketStatus.COMPLETED,
            now - timedelta(days=40),
            self.worker_one.id,
            completed_at=now - timedelta(days=40),
            updated_at=now,
        )

    def summary(self, **params):
        response = self.client.get("/api/v1/analytics/tickets-summary", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    @staticmethod
    def counts(body: dict) -> dict:
        keys = ("open", "assigned", "in_progress", "created_in_period", "completed")
        return {key: body[key] for key in keys}

    def test_observer_sees_current_queue_and_period_counts_separately(self):
        self.current_user = self.observer
        body = self.summary(period="today")

        self.assertEqual(
            self.counts(body),
            {"open": 1, "assigned": 2, "in_progress": 1, "created_in_period": 4, "completed": 1},
        )
        self.assertEqual(body["open_unassigned"], body["open"])
        self.assertEqual(body["open_assigned"], body["assigned"])
        self.assertEqual(body["completed_in_period"], body["completed"])

    def test_every_period_reports_moscow_bounds_and_the_same_current_state(self):
        self.current_user = self.observer
        for period in ("today", "week", "month"):
            with self.subTest(period=period):
                body = self.summary(period=period)
                start = datetime.fromisoformat(body["period_start"])
                end = datetime.fromisoformat(body["period_end"])
                self.assertEqual(start.utcoffset(), timedelta(hours=3))
                self.assertEqual((start.hour, start.minute), (0, 0))
                self.assertLess(start, end)
                self.assertEqual(body["open"], 1, "current state must not depend on the period")

    def test_office_filter_keeps_the_area_queue_and_own_brigade_work(self):
        self.current_user = self.observer
        body = self.summary(period="month", office_id=self.office_one)

        # The unassigned ticket has no area of its own; its building's area is the office's.
        self.assertEqual(
            self.counts(body),
            {"open": 1, "assigned": 1, "in_progress": 1, "created_in_period": 3, "completed": 1},
        )

    def test_foreman_sees_own_brigade_and_the_queue_of_its_office_area(self):
        self.current_user = self.foreman_one
        body = self.summary(period="month", office_id=self.office_two)

        self.assertEqual(
            self.counts(body),
            {"open": 1, "assigned": 1, "in_progress": 1, "created_in_period": 3, "completed": 1},
        )

    def test_foreman_without_brigade_gets_zero_summary(self):
        self.current_user = self.foreman_without_brigade
        body = self.summary(period="today")

        self.assertEqual(
            self.counts(body),
            {"open": 0, "assigned": 0, "in_progress": 0, "created_in_period": 0, "completed": 0},
        )

    def test_planned_for_date_counts_promises_of_that_moscow_day(self):
        self.current_user = self.observer
        location = self.connection.execute(text("SELECT id FROM locations LIMIT 1")).scalar_one()
        day = date(2030, 5, 20)
        midnight = datetime(2030, 5, 19, 21, 0, tzinfo=UTC)  # 00:00 MSK on the 20th
        self.add_ticket(location, TicketStatus.PLANNED, self.now, planned_start_at=midnight)
        self.add_ticket(
            location,
            TicketStatus.PLANNED,
            self.now,
            planned_start_at=midnight - timedelta(minutes=1),
        )
        self.session.commit()

        body = self.summary(period="today", date=day.isoformat())
        self.assertEqual(body["plan_date"], day.isoformat())
        self.assertEqual(body["planned_for_date"], 1)

    def test_day_boundary_is_moscow_midnight_even_when_the_database_runs_in_utc(self):
        location = self.connection.execute(text("SELECT id FROM locations LIMIT 1")).scalar_one()
        self.connection.execute(text("SET TIME ZONE 'UTC'"))
        midnight = datetime(2030, 5, 19, 21, 0, tzinfo=UTC)  # 00:00 MSK on the 20th
        # 23:50 MSK yesterday and 00:10 MSK today; in UTC both are the same date.
        self.add_ticket(location, TicketStatus.PLANNED, midnight - timedelta(minutes=10))
        self.add_ticket(location, TicketStatus.PLANNED, midnight + timedelta(minutes=10))
        self.add_ticket(
            location,
            TicketStatus.COMPLETED,
            midnight - timedelta(hours=2),
            completed_at=midnight - timedelta(seconds=1),
        )
        self.add_ticket(
            location, TicketStatus.COMPLETED, midnight - timedelta(hours=2), completed_at=midnight
        )

        summary = get_tickets_summary(
            self.session,
            period=AnalyticsPeriod.TODAY,
            office_id=None,
            current_user=self.observer,
            now=midnight + timedelta(hours=10),
        )
        self.assertEqual(summary.period_start, midnight)
        self.assertEqual(summary.created_in_period, 1)
        self.assertEqual(summary.completed_in_period, 1)

    def test_worker_is_forbidden_and_invalid_period_is_rejected(self):
        self.current_user = self.worker_one
        forbidden = self.client.get("/api/v1/analytics/tickets-summary?period=today")
        self.assertEqual(forbidden.status_code, 403)

        self.current_user = self.observer
        invalid = self.client.get("/api/v1/analytics/tickets-summary?period=year")
        self.assertEqual(invalid.status_code, 422)

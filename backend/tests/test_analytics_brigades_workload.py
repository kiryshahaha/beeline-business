"""Brigade workload on one date: the planner's shift, saved routes and dated absences."""

import json
from datetime import UTC, date, datetime, timedelta

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

MOSCOW_OFFSET = timedelta(hours=3)
DAY = date(2030, 3, 11)


def at(hour: int, minute: int = 0) -> datetime:
    """A moment of DAY in Moscow time, stored as UTC."""
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=UTC) - MOSCOW_OFFSET


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
        district_row_id = self.connection.execute(
            text("INSERT INTO districts (name, city_id) VALUES ('Район', :city_id) RETURNING id"),
            {"city_id": city_id},
        ).scalar_one()
        service_area_id = self.service_area_for_district(district_row_id)
        self.service_area_id = service_area_id
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
        start: datetime,
        worker_id: int | None = None,
        *,
        minutes: int = 60,
        completed_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> int:
        return self.connection.execute(
            text(
                "INSERT INTO tickets ("
                "location_id, title, work_type, status, visit_window_start, visit_window_end, "
                "estimated_duration_minutes, planned_start_at, planned_end_at, "
                "assigned_worker_id, actual_completed_at, created_at, updated_at"
                ") VALUES ("
                ":location_id, :title, 'Настройка сети', :status, :start, :window_end, "
                ":minutes, :start, :end, :worker_id, :completed_at, :start, :updated_at"
                ") RETURNING id"
            ),
            {
                "location_id": location_id,
                "title": f"Заявка {status.value} {start.isoformat()}",
                "status": status.value,
                "start": start,
                "end": start + timedelta(minutes=minutes),
                "window_end": start + timedelta(hours=4),
                "minutes": minutes,
                "worker_id": worker_id,
                "completed_at": completed_at,
                "updated_at": updated_at or start,
            },
        ).scalar_one()

    def add_route(self, worker_id: int, stops: list[dict]) -> None:
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [37.6, 55.7]},
                "properties": {"sequence": number, **stop},
            }
            for number, stop in enumerate(stops, 1)
        ]
        self.connection.execute(
            text(
                "INSERT INTO routes (worker_id, route_date, route_number, geojson) "
                "VALUES (:worker_id, :day, 1, CAST(:geojson AS JSONB))"
            ),
            {
                "worker_id": worker_id,
                "day": DAY,
                "geojson": json.dumps(
                    {"type": "FeatureCollection", "features": features}, ensure_ascii=False
                ),
            },
        )

    def seed_tickets(self, location_id: int) -> None:
        first = self.add_ticket(location_id, TicketStatus.PLANNED, at(9, 30), self.worker_one.id)
        second = self.add_ticket(location_id, TicketStatus.PLANNED, at(10, 50), self.worker_one.id)
        # Office 09:00 → client (20 min, waits 10) → client (20 min) → office (20 min).
        self.add_route(
            self.worker_one.id,
            [
                {"location_id": location_id, "arrival_at": at(9, 0).isoformat()},
                {
                    "location_id": location_id,
                    "ticket_id": first,
                    "arrival_at": at(9, 20).isoformat(),
                    "service_start_at": at(9, 30).isoformat(),
                    "service_end_at": at(10, 30).isoformat(),
                    "waiting_minutes": 10,
                },
                {
                    "location_id": location_id,
                    "ticket_id": second,
                    "arrival_at": at(10, 50).isoformat(),
                    "service_start_at": at(10, 50).isoformat(),
                    "service_end_at": at(11, 50).isoformat(),
                    "waiting_minutes": 0,
                },
                {"location_id": location_id, "arrival_at": at(12, 10).isoformat()},
            ],
        )
        self.add_ticket(
            location_id,
            TicketStatus.COMPLETED,
            at(14, 0),
            self.worker_one.id,
            completed_at=at(15, 0),
        )
        # Closed two days ago and only edited today: not a completion of today (A31).
        self.add_ticket(
            location_id,
            TicketStatus.COMPLETED,
            at(9, 0) - timedelta(days=2),
            self.worker_two.id,
            completed_at=at(10, 0) - timedelta(days=2),
            updated_at=at(16, 0),
        )
        # The engineer of the second brigade is marked unavailable for the whole date.
        self.add_ticket(location_id, TicketStatus.PLANNED, at(12, 0), self.worker_two.id)
        self.connection.execute(
            text(
                "INSERT INTO worker_day_states "
                "(worker_id, service_area_id, route_date, available, unavailable_at, reason) "
                "VALUES (:worker_id, :area, :day, false, :since, 'Больничный')"
            ),
            {
                "worker_id": self.worker_two.id,
                "area": self.service_area_id,
                "day": DAY,
                "since": at(8, 0),
            },
        )

    def workload(self, **params):
        response = self.client.get(
            "/api/v1/analytics/brigades-workload", params={"date": DAY.isoformat(), **params}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {item["brigade_name"]: item for item in response.json()}

    def test_load_comes_from_the_shift_and_the_saved_route(self):
        self.current_user = self.observer
        alpha = self.workload()["Альфа"]

        self.assertEqual(alpha["date"], DAY.isoformat())
        self.assertEqual((alpha["workers"], alpha["available_workers"]), (1, 1))
        self.assertEqual(alpha["tickets"], 3)
        # 09:00–18:00 shift; two routed visits plus the completed afternoon one.
        self.assertEqual(alpha["shift_minutes"], 540)
        self.assertEqual(alpha["service_minutes"], 180)
        self.assertEqual(alpha["travel_minutes"], 60)
        self.assertEqual(alpha["waiting_minutes"], 10)
        self.assertEqual(alpha["free_minutes"], 540 - 180 - 60 - 10)
        self.assertEqual(alpha["overtime_minutes"], 0)
        self.assertEqual(alpha["completed_today"], 1)

    def test_absent_engineer_gives_no_capacity_and_a_conflict(self):
        self.current_user = self.observer
        beta = self.workload()["Бета"]

        self.assertEqual((beta["workers"], beta["available_workers"]), (1, 0))
        self.assertEqual((beta["shift_minutes"], beta["free_minutes"]), (0, 0))
        self.assertEqual(beta["tickets"], 1)
        self.assertEqual(beta["conflicts"], 1)
        # An old closed ticket edited today is not today's completion.
        self.assertEqual(beta["completed_today"], 0)

    def test_empty_brigade_is_listed_with_zero_load(self):
        self.current_user = self.observer
        empty = self.workload()["Пустая"]

        self.assertEqual(
            {key: empty[key] for key in ("workers", "tickets", "shift_minutes", "conflicts")},
            {"workers": 0, "tickets": 0, "shift_minutes": 0, "conflicts": 0},
        )

    def test_another_date_has_nothing_planned(self):
        self.current_user = self.observer
        alpha = self.workload(date=(DAY + timedelta(days=1)).isoformat())["Альфа"]

        self.assertEqual((alpha["tickets"], alpha["service_minutes"]), (0, 0))
        self.assertEqual(alpha["free_minutes"], alpha["shift_minutes"])

    def test_foreman_sees_only_own_brigade(self):
        self.current_user = self.foreman_one

        self.assertEqual(list(self.workload()), ["Альфа"])

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

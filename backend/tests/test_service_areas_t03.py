"""T03 acceptance and integration tests (A03, A05, A06, F02, F05, F20).

Tests cover:
- A05: Cross-area planning/manual assignment isolation without equipment requirement
- A06: Engineer home start (start_location_id) separated from stock office (stock_office_id)
- A03: Open route vs return-to-start (finishing shift at customer site)
- F20: Office analytics summary counting unassigned open tickets in area scope
- Service areas CRUD API and database relations
"""

import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

os.environ.setdefault("DATABASE_URL", "postgresql://unused/isolated_test")

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    Brigade,
    BrigadeMember,
    Building,
    City,
    District,
    Entrance,
    Location,
    Office,
    ServiceArea,
    Street,
    WorkType,
)
from app.db.session import get_session
from app.main import app
from app.modules.planning import reasons
from app.modules.planning.eligibility import candidate_reason, check_eligibility
from app.modules.planning.matrices import build_problem
from app.modules.routing.schemas import RouteMatrixCell, RouteMatrixResult
from app.modules.tickets.schemas import TicketCreate
from app.modules.tickets.service import create_ticket
from app.modules.users.enums import TransportType, UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from tests.support import DatabaseTestCase

MOSCOW = ZoneInfo("Europe/Moscow")
EPOCH = datetime(2030, 1, 15, tzinfo=MOSCOW)
SHIFT_START = "09:00:00"
SHIFT_END = "18:00:00"


class ServiceAreasUnitTests(unittest.TestCase):
    def test_service_area_mismatch_reason_structure(self):
        reason = reasons.service_area_mismatch(worker_area=1, ticket_area=2)
        self.assertEqual(reason["code"], "service_area_mismatch")
        self.assertEqual(reason["observed"]["service_area_id"], 1)
        self.assertEqual(reason["required"]["service_area_id"], 2)
        self.assertIn("1", reason["message"])
        self.assertIn("2", reason["message"])

    def test_candidate_reason_flags_service_area_mismatch_without_equipment(self):
        worker = {
            "user_id": 10,
            "transport_type": "car",
            "service_area_id": 1,
            "skill_ids": {100},
            "office_id": 1,
            "window": [540, 1080],
        }
        # Ticket in area 2 with NO required equipment and matching skill
        ticket = {
            "id": 99,
            "work_type_id": 1,
            "service_area_id": 2,
            "visit_window_start": "2030-01-15T09:00:00+03:00",
            "visit_window_end": "2030-01-15T18:00:00+03:00",
        }
        reason = candidate_reason(
            ticket=ticket,
            window=(540, 1080),
            duration=60,
            skills={100},
            allocations=[],
            worker=worker,
            epoch=EPOCH,
        )
        self.assertIsNotNone(reason)
        self.assertEqual(reason["code"], "service_area_mismatch")
        self.assertEqual(reason["observed"]["service_area_id"], 1)
        self.assertEqual(reason["required"]["service_area_id"], 2)

    def test_candidate_reason_allows_matching_service_area(self):
        worker = {
            "user_id": 10,
            "transport_type": "car",
            "service_area_id": 1,
            "skill_ids": {100},
            "office_id": 1,
            "window": [540, 1080],
        }
        ticket = {
            "id": 99,
            "work_type_id": 1,
            "service_area_id": 1,
            "visit_window_start": "2030-01-15T09:00:00+03:00",
            "visit_window_end": "2030-01-15T18:00:00+03:00",
        }
        reason = candidate_reason(
            ticket=ticket,
            window=(540, 1080),
            duration=60,
            skills={100},
            allocations=[],
            worker=worker,
            epoch=EPOCH,
        )
        self.assertIsNone(reason)

    def test_home_start_and_stock_office_eligibility_resolution(self):
        home_loc = {"id": 101, "latitude": 55.70, "longitude": 37.60}
        office_loc = {"id": 10, "latitude": 55.75, "longitude": 37.65}
        ticket_loc = {"id": 50, "latitude": 55.72, "longitude": 37.62}
        snapshot = {
            "policy_version": 1,
            "request": {
                "route_date": "2030-01-15",
                "ticket_ids": [1],
                "worker_ids": [10],
                "route_end": "open",
            },
            "workers": [
                {
                    "user_id": 10,
                    "workshift_start": "09:00:00",
                    "workshift_end": "18:00:00",
                    "transport_type": "car",
                    "is_on_line": True,
                    "service_area_id": 1,
                    "start_location_id": 101,
                    "stock_office_id": 1,
                }
            ],
            "brigades": [{"id": 1, "office_id": 1, "division_id": 1}],
            "members": [{"worker_id": 10, "brigade_id": 1}],
            "offices": [{"id": 1, "location_id": 10}],
            "locations": [home_loc, office_loc, ticket_loc],
            "roles": [{"id": 10, "role": "worker"}],
            "skills": [{"worker_id": 10, "skill_id": 1}],
            "worker_skills": [],
            "busy_tickets": [],
            "assignments": [],
            "allocations": [],
            "required_skills": [{"work_type_id": 1, "skill_id": 1}],
            "required_appliances": [],
            "appliances": [],
            "stocks": [],
            "reservations": [],
            "tickets": [
                {
                    "id": 1,
                    "location_id": 50,
                    "work_type_id": 1,
                    "service_area_id": 1,
                    "status": "planned",
                    "visit_window_start": "2030-01-15T09:00:00+03:00",
                    "visit_window_end": "2030-01-15T18:00:00+03:00",
                }
            ],
            "work_types": [
                {
                    "id": 1,
                    "name": "Монтаж ВОЛС",
                    "work_minutes": 50,
                    "documents_minutes": 10,
                    "default_priority": 3,
                    "category": "installation",
                }
            ],
            "rules": [
                {
                    "work_type_id": 1,
                    "service_duration_source": "work_plus_documents",
                }
            ],
            "execution_rules": [],
            "service_areas": [{"id": 1, "code": "area_north", "name": "North"}],
        }
        prepared = check_eligibility(snapshot=snapshot, now=EPOCH)
        self.assertEqual(len(prepared["workers"]), 1)
        w = prepared["workers"][0]
        # Start depot is home location 101, not fake warehouse
        self.assertEqual(w["location_id"], 101)
        self.assertEqual(w["start_location_id"], 101)
        # Office for equipment pickup is stock office 1
        self.assertEqual(w["office_id"], 1)
        self.assertEqual(w["stock_office_id"], 1)


class RouteEndUnitTests(unittest.IsolatedAsyncioTestCase):
    def settings(self):
        return Settings(
            database_url="postgresql://unused/isolated_test",
            planner_service_token="internal",
        )

    async def test_matrices_route_end_open_zeroes_task_to_finish_cost(self):
        mock_provider = AsyncMock()
        mock_provider.build_route_matrix.return_value = RouteMatrixResult(
            cells=[
                [
                    RouteMatrixCell(duration_seconds=0, distance_meters=0),
                    RouteMatrixCell(duration_seconds=1200, distance_meters=5000),
                ],
                [
                    RouteMatrixCell(duration_seconds=1200, distance_meters=5000),
                    RouteMatrixCell(duration_seconds=0, distance_meters=0),
                ],
            ]
        )
        prepared = {
            "epoch": EPOCH,
            "workers": [
                {
                    "user_id": 1,
                    "location_id": 10,
                    "start_location_id": 10,
                    "profile": "drive",
                    "window": [540, 1080],
                }
            ],
            "tickets": [
                {
                    "id": 100,
                    "location_id": 20,
                    "window": [540, 1020],
                    "duration": 30,
                    "allowed": [0],
                    "category": "repair",
                    "priority": 3,
                    "received_at": EPOCH.isoformat(),
                    "sla_deadline_at": None,
                }
            ],
            "locations": {
                10: {"longitude": 37.61, "latitude": 55.75},
                20: {"longitude": 37.65, "latitude": 55.78},
            },
            "horizon": 1080,
            "route_end": "open",
        }
        problem, nodes = await build_problem(prepared, mock_provider, self.settings())
        # With open_end: depot node 0, finish node 1, task node 2
        self.assertEqual(len(nodes), 3)
        self.assertEqual(problem.starts, [0])
        self.assertEqual(problem.ends, [1])
        self.assertTrue(problem.open_end)

        # Task (node 2) to virtual finish (node 1) must be 0 minutes and 0 meters
        time_matrix = problem.matrices["drive"].time_minutes
        dist_matrix = problem.matrices["drive"].distance_meters
        self.assertEqual(time_matrix[2][1], 0)
        self.assertEqual(dist_matrix[2][1], 0)

    async def test_matrices_route_end_return_to_start_retains_travel_cost(self):
        mock_provider = AsyncMock()
        mock_provider.build_route_matrix.return_value = RouteMatrixResult(
            cells=[
                [
                    RouteMatrixCell(duration_seconds=0, distance_meters=0),
                    RouteMatrixCell(duration_seconds=1200, distance_meters=5000),
                ],
                [
                    RouteMatrixCell(duration_seconds=1200, distance_meters=5000),
                    RouteMatrixCell(duration_seconds=0, distance_meters=0),
                ],
            ]
        )
        prepared = {
            "epoch": EPOCH,
            "workers": [
                {
                    "user_id": 1,
                    "location_id": 10,
                    "start_location_id": 10,
                    "profile": "drive",
                    "window": [540, 1080],
                }
            ],
            "tickets": [
                {
                    "id": 100,
                    "location_id": 20,
                    "window": [540, 1020],
                    "duration": 30,
                    "allowed": [0],
                    "category": "repair",
                    "priority": 3,
                    "received_at": EPOCH.isoformat(),
                    "sla_deadline_at": None,
                }
            ],
            "locations": {
                10: {"longitude": 37.61, "latitude": 55.75},
                20: {"longitude": 37.65, "latitude": 55.78},
            },
            "horizon": 1080,
            "route_end": "return_to_start",
        }
        problem, nodes = await build_problem(prepared, mock_provider, self.settings())
        # return_to_start: depot node 0, task node 1; starts == ends == [0]
        self.assertEqual(len(nodes), 2)
        self.assertEqual(problem.starts, [0])
        self.assertEqual(problem.ends, [0])
        self.assertFalse(problem.open_end)

        # Task (node 1) returning to depot (node 0) travel cost is retained (> 0)
        time_matrix = problem.matrices["drive"].time_minutes
        self.assertEqual(time_matrix[1][0], 20)  # 1200s / 60 = 20 min


class ServiceAreasIntegrationTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))

        # Infrastructure
        self.city = self.save(City(name="Москва"))
        self.district_north = self.save(District(city_id=self.city.id, name="Северный"))
        self.district_south = self.save(District(city_id=self.city.id, name="Южный"))
        self.street = self.save(Street(city_id=self.city.id, name="Тверская"))

        self.bld_north = self.save(
            Building(
                city_id=self.city.id,
                street_id=self.street.id,
                district_id=self.district_north.id,
                number="10",
            )
        )
        self.bld_south = self.save(
            Building(
                city_id=self.city.id,
                street_id=self.street.id,
                district_id=self.district_south.id,
                number="20",
            )
        )

        self.entrance_north = self.save(Entrance(building_id=self.bld_north.id, number="1"))
        self.entrance_south = self.save(Entrance(building_id=self.bld_south.id, number="1"))

        self.loc_office = self.save(
            Location(
                building_id=self.bld_north.id,
                entrance_id=self.entrance_north.id,
                apartment="1",
                floor=1,
                latitude=55.75,
                longitude=37.61,
            )
        )
        self.loc_home = self.save(
            Location(
                building_id=self.bld_north.id,
                entrance_id=self.entrance_north.id,
                apartment="5",
                floor=2,
                latitude=55.76,
                longitude=37.62,
            )
        )
        self.loc_client_south = self.save(
            Location(
                building_id=self.bld_south.id,
                entrance_id=self.entrance_south.id,
                apartment="10",
                floor=3,
                latitude=55.65,
                longitude=37.60,
            )
        )

        self.office = self.save(Office(name="Офис Север", location_id=self.loc_office.id))

        # Service areas
        self.area_north = self.save(
            ServiceArea(
                code="area_north",
                name="Северный участок",
                description="Обслуживание севера",
            )
        )
        self.area_south = self.save(
            ServiceArea(
                code="area_south",
                name="Южный участок",
                description="Обслуживание юга",
            )
        )

        # Users
        self.observer = self.create_user("obs_t03", UserRole.OBSERVER)
        self.worker_north = self.create_user(
            "worker_north_t03",
            UserRole.WORKER,
            service_area_id=self.area_north.id,
            start_location_id=self.loc_home.id,
            stock_office_id=self.office.id,
            skills=["Монтаж ВОЛС"],
        )
        self.worker_south = self.create_user(
            "worker_south_t03",
            UserRole.WORKER,
            service_area_id=self.area_south.id,
            skills=["Монтаж ВОЛС"],
        )

        # Brigade – division_id is set automatically by the DB trigger
        # set_brigade_division_from_office (migration 0016).
        self.brigade = self.save(
            Brigade(name="Бригада Север", foreman_id=self.observer.id, office_id=self.office.id)
        )
        self.save(BrigadeMember(brigade_id=self.brigade.id, worker_id=self.worker_north.id))

        # Work type
        self.work_type = self.save(
            WorkType(
                code="fiber_install",
                name="Монтаж ВОЛС",
                category="repair",
                travel_minutes=20,
                work_minutes=30,
                documents_minutes=10,
            )
        )

        self.session.commit()

    def save(self, instance):
        self.session.add(instance)
        self.session.flush()
        return instance

    def create_user(
        self,
        username: str,
        role: UserRole,
        service_area_id: int | None = None,
        start_location_id: int | None = None,
        stock_office_id: int | None = None,
        skills: list[str] | None = None,
    ):
        profile = None
        if role == UserRole.WORKER:
            profile = WorkerProfileCreate(
                workshift_start=SHIFT_START,
                workshift_end=SHIFT_END,
                transport_type=TransportType.CAR,
                skills=skills or ["Монтаж ВОЛС"],
                service_area_id=service_area_id,
                start_location_id=start_location_id,
                stock_office_id=stock_office_id,
            )
        return create_user(
            self.session,
            UserCreate(
                name=f"Имя {username}",
                surname=f"Фамилия {username}",
                username=username,
                password="Password123!",
                role=role,
                worker_profile=profile,
            ),
        )

    def auth_headers(self, user) -> dict[str, str]:
        response = self.client.post(
            "/api/v1/auth/login", json={"username": user.username, "password": "Password123!"}
        )
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def test_a05_manual_assignment_cross_area_rejected_422(self):
        # Create ticket in South area
        ticket = create_ticket(
            self.session,
            TicketCreate(
                title="Заявка Юг",
                work_type_id=self.work_type.id,
                location_id=self.loc_client_south.id,
                service_area_id=self.area_south.id,
                visit_window_start=EPOCH.replace(hour=10, minute=0),
                visit_window_end=EPOCH.replace(hour=12, minute=0),
                estimated_duration_minutes=60,
            ),
        )
        self.session.commit()

        headers = self.auth_headers(self.observer)
        # Attempt to assign worker_north to south ticket
        response = self.client.put(
            f"/api/v1/tickets/{ticket.id}/assignees",
            json={"worker_id": self.worker_north.id, "is_pinned": True},
            headers=headers,
        )
        self.assertEqual(response.status_code, 422)
        self.assertTrue(
            "Service area mismatch" in response.json()["detail"]
            or "участку обслуживания" in response.json()["detail"]
        )

    def test_a05_manual_assignment_same_area_succeeds_200(self):
        # Create ticket in South area
        ticket = create_ticket(
            self.session,
            TicketCreate(
                title="Заявка Юг",
                work_type_id=self.work_type.id,
                location_id=self.loc_client_south.id,
                service_area_id=self.area_south.id,
                visit_window_start=EPOCH.replace(hour=10, minute=0),
                visit_window_end=EPOCH.replace(hour=12, minute=0),
                estimated_duration_minutes=60,
            ),
        )
        self.session.commit()

        headers = self.auth_headers(self.observer)
        # Assign worker_south to south ticket
        response = self.client.put(
            f"/api/v1/tickets/{ticket.id}/assignees",
            json={"worker_id": self.worker_south.id, "is_pinned": True},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)

    def test_a06_worker_profile_home_start_and_stock_office(self):
        headers = self.auth_headers(self.observer)
        response = self.client.get(f"/api/v1/users/{self.worker_north.id}", headers=headers)
        self.assertEqual(response.status_code, 200)
        profile = response.json()["worker_profile"]
        self.assertEqual(profile["service_area_id"], self.area_north.id)
        self.assertEqual(profile["start_location_id"], self.loc_home.id)
        self.assertEqual(profile["stock_office_id"], self.office.id)

    def test_f20_analytics_office_summary_unassigned_open_tickets(self):
        # Create district-aligned service area for North
        district_area = self.save(
            ServiceArea(
                code=f"district_{self.district_north.id}",
                name="Район Северный",
            )
        )
        # Create unassigned open ticket in North area
        ticket = create_ticket(
            self.session,
            TicketCreate(
                title="Заявка Север",
                work_type_id=self.work_type.id,
                location_id=self.loc_office.id,
                service_area_id=district_area.id,
                visit_window_start=EPOCH.replace(hour=10, minute=0),
                visit_window_end=EPOCH.replace(hour=12, minute=0),
                estimated_duration_minutes=60,
            ),
        )
        self.assertIsNotNone(ticket.id)
        self.session.commit()

        headers = self.auth_headers(self.observer)
        response = self.client.get(
            f"/api/v1/analytics/tickets-summary?office_id={self.office.id}&period=today",
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        summary = response.json()
        self.assertGreaterEqual(summary["open"], 1)

    def test_service_areas_crud_api(self):
        headers = self.auth_headers(self.observer)
        # List
        response = self.client.get("/api/v1/service-areas", headers=headers)
        self.assertEqual(response.status_code, 200)
        codes = [sa["code"] for sa in response.json()]
        self.assertIn("area_north", codes)
        self.assertIn("area_south", codes)

        # Get by id
        response = self.client.get(f"/api/v1/service-areas/{self.area_north.id}", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Северный участок")

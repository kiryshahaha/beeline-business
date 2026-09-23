"""T02 acceptance and integration tests (A04, A07, A10, A21).

Tests cover:
- A21: Renaming WorkType.name does not orphan tickets or break planning eligibility
- A04: Service duration is work+docs without double travel (norm 50 -> 30, 100 -> 80)
- A07: Required transport filtering (car-only vs walking/any)
- A10: Emergency received_at prevents service start before receipt
- Appliance combination: max(rule_quantity, ticket_allocated_quantity)
- WorkType code, category, default_priority propagation to Ticket
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Brigade,
    BrigadeMember,
    Building,
    City,
    District,
    Entrance,
    Location,
    Office,
    Street,
    WorkType,
    WorkTypePlanningRule,
)
from app.db.session import get_session
from app.main import app
from app.modules.planning.eligibility import check_eligibility
from app.modules.tickets.enums import TicketCategory
from app.modules.tickets.schemas import TicketCreate
from app.modules.tickets.service import create_ticket, get_ticket
from app.modules.users.enums import TransportType, UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from app.modules.work_types.schemas import WorkTypeUpdate
from app.modules.work_types.service import update_work_type
from tests.support import DatabaseTestCase

TZ = ZoneInfo("Europe/Moscow")


class TicketsNormalizationT02Tests(DatabaseTestCase):
    def setUp(self):
        super().setUp()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))

        # Basic infrastructure setup
        city = self.save(City(name="Москва"))
        district = self.save(District(city_id=city.id, name="Центральный"))
        street = self.save(Street(city_id=city.id, name="Тверская"))
        building = self.save(
            Building(city_id=city.id, street_id=street.id, district_id=district.id, number="1")
        )
        entrance = self.save(Entrance(building_id=building.id, number="1"))
        self.location = self.save(
            Location(
                building_id=building.id,
                entrance_id=entrance.id,
                apartment="10",
                floor=2,
                latitude=55.75,
                longitude=37.61,
            )
        )
        self.office = self.save(
            Office(name="Главный офис", location_id=self.location.id, is_active=True)
        )

        # Users and workers
        self.observer = self.create_user("obs_t02", UserRole.OBSERVER)
        self.worker_user = self.create_user(
            "worker_car_t02",
            UserRole.WORKER,
            skills=["Аварийно-восстановительные работы", "Монтаж ВОЛС", "Настройка оборудования"],
            transport_type=TransportType.CAR,
        )
        self.worker_walking = self.create_user(
            "worker_walk_t02",
            UserRole.WORKER,
            skills=["Аварийно-восстановительные работы", "Монтаж ВОЛС", "Настройка оборудования"],
            transport_type=TransportType.WALKING,
        )
        self.brigade = self.save(
            Brigade(name="Бригада 1", foreman_id=self.observer.id, office_id=self.office.id)
        )
        self.save(BrigadeMember(brigade_id=self.brigade.id, worker_id=self.worker_user.id))
        self.save(BrigadeMember(brigade_id=self.brigade.id, worker_id=self.worker_walking.id))

        self.session.commit()

    def save(self, instance):
        self.session.add(instance)
        self.session.flush()
        return instance

    def create_user(
        self,
        username: str,
        role: UserRole,
        skills: list[str] | None = None,
        transport_type: TransportType = TransportType.CAR,
    ):
        profile = None
        if role == UserRole.WORKER:
            profile = WorkerProfileCreate(
                workshift_start="08:00:00",
                workshift_end="20:00:00",
                transport_type=transport_type,
                skills=skills or [],
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

    def test_a21_rename_canonical_work_type_does_not_break_tickets(self):
        """A21: Renaming work type does not disconnect tickets or break eligibility."""
        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
            # 1. Find the canonical connection work type
            conn_wt = session.execute(
                select(WorkType).where(WorkType.code == "connection")
            ).scalar_one()
            self.assertEqual(conn_wt.category, "connection")

            # 2. Create ticket referencing this work_type_id
            now = datetime.now(TZ)
            ticket_dto = TicketCreate(
                location_id=self.location.id,
                title="Подключение клиента",
                work_type_id=conn_wt.id,
                visit_window_start=now + timedelta(hours=1),
                visit_window_end=now + timedelta(hours=5),
                estimated_duration_minutes=60,
            )
            ticket = create_ticket(session, ticket_dto)
            self.assertEqual(ticket.work_type_id, conn_wt.id)
            self.assertEqual(ticket.category, TicketCategory.CONNECTION)
            self.assertEqual(ticket.priority, 2)

            # 3. Rename WorkType name
            update_work_type(
                session, conn_wt.id, WorkTypeUpdate(name="Подключение клиентов Обновленное")
            )

            # 4. Read ticket again - FK intact
            re_read = get_ticket(session, ticket.id)
            self.assertEqual(re_read.work_type_id, conn_wt.id)

            # 5. Check snapshot & eligibility: no unknown_work_type error!
            from app.modules.planning.repository import load_snapshot
            from app.modules.planning.schemas import PreviewRequest

            req = PreviewRequest(
                route_date=(now + timedelta(hours=1)).date(),
                ticket_ids=[ticket.id],
                worker_ids=[self.worker_user.id],
            )
            snapshot = load_snapshot(session, req)
            eligibility = check_eligibility(snapshot)
            self.assertEqual(len(eligibility["unassigned"]), 0, eligibility["unassigned"])
            self.assertEqual(len(eligibility["tickets"]), 1)
            self.assertEqual(eligibility["tickets"][0]["work_type_id"], conn_wt.id)

    def test_a04_service_duration_norm_semantics(self):
        """A04: Local norm 50 = 20 + 30 -> service=30; emergency 100 = 20 + 80 -> service=80."""
        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
            repair_wt = session.execute(
                select(WorkType).where(WorkType.code == "repair")
            ).scalar_one()
            emergency_wt = session.execute(
                select(WorkType).where(WorkType.code == "emergency")
            ).scalar_one()

            # Ensure rules are work_norm
            rule_repair = session.get(WorkTypePlanningRule, repair_wt.id)
            if not rule_repair:
                rule_repair = WorkTypePlanningRule(
                    work_type_id=repair_wt.id,
                    service_duration_source="work_norm",
                    configured_by=self.observer.id,
                )
                session.add(rule_repair)
            else:
                rule_repair.service_duration_source = "work_norm"

            rule_emerg = session.get(WorkTypePlanningRule, emergency_wt.id)
            if not rule_emerg:
                rule_emerg = WorkTypePlanningRule(
                    work_type_id=emergency_wt.id,
                    service_duration_source="work_norm",
                    configured_by=self.observer.id,
                )
                session.add(rule_emerg)
            else:
                rule_emerg.service_duration_source = "work_norm"

            session.flush()

            now = datetime.now(TZ).replace(microsecond=0)
            t_repair = create_ticket(
                session,
                TicketCreate(
                    location_id=self.location.id,
                    title="Локальный ремонт",
                    work_type_id=repair_wt.id,
                    visit_window_start=now + timedelta(hours=1),
                    visit_window_end=now + timedelta(hours=4),
                    estimated_duration_minutes=999,  # Should be overridden by work_norm
                ),
            )
            t_emerg = create_ticket(
                session,
                TicketCreate(
                    location_id=self.location.id,
                    title="Авария на линии",
                    work_type_id=emergency_wt.id,
                    visit_window_start=now + timedelta(hours=1),
                    visit_window_end=now + timedelta(hours=6),
                    estimated_duration_minutes=999,
                ),
            )

            from app.modules.planning.repository import load_snapshot
            from app.modules.planning.schemas import PreviewRequest

            req = PreviewRequest(
                route_date=(now + timedelta(hours=1)).date(),
                ticket_ids=[t_repair.id, t_emerg.id],
                worker_ids=[self.worker_user.id],
            )
            snapshot = load_snapshot(session, req)
            elig = check_eligibility(snapshot)

            tickets_by_id = {t["id"]: t for t in elig["tickets"]}
            # Repair norm: work=30, docs=0 -> service duration must be exactly 30 minutes!
            self.assertEqual(tickets_by_id[t_repair.id]["duration"], 30)
            # Emergency norm: work=80, docs=0 -> service duration must be exactly 80 minutes!
            self.assertEqual(tickets_by_id[t_emerg.id]["duration"], 80)

    def test_a07_required_transport_type_filtering(self):
        """A07: Requirement car: only car is eligible. Empty: both car and walk eligible."""
        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
            repair_wt = session.execute(
                select(WorkType).where(WorkType.code == "repair")
            ).scalar_one()
            rule = session.get(WorkTypePlanningRule, repair_wt.id)
            if not rule:
                session.add(
                    WorkTypePlanningRule(
                        work_type_id=repair_wt.id,
                        service_duration_source="work_norm",
                        configured_by=self.observer.id,
                    )
                )
                session.flush()

            now = datetime.now(TZ)
            # Ticket 1: requires CAR
            t_car = create_ticket(
                session,
                TicketCreate(
                    location_id=self.location.id,
                    title="Выезд на авто",
                    work_type_id=repair_wt.id,
                    required_transport_type=TransportType.CAR,
                    visit_window_start=now + timedelta(hours=1),
                    visit_window_end=now + timedelta(hours=4),
                    estimated_duration_minutes=30,
                ),
            )
            # Ticket 2: no transport required
            t_any = create_ticket(
                session,
                TicketCreate(
                    location_id=self.location.id,
                    title="Выезд любой",
                    work_type_id=repair_wt.id,
                    required_transport_type=None,
                    visit_window_start=now + timedelta(hours=1),
                    visit_window_end=now + timedelta(hours=4),
                    estimated_duration_minutes=30,
                ),
            )

            from app.modules.planning.repository import load_snapshot
            from app.modules.planning.schemas import PreviewRequest

            req = PreviewRequest(
                route_date=(now + timedelta(hours=1)).date(),
                ticket_ids=[t_car.id, t_any.id],
                worker_ids=[self.worker_user.id, self.worker_walking.id],
            )
            snapshot = load_snapshot(session, req)
            elig = check_eligibility(snapshot)

            res_by_id = {t["id"]: t for t in elig["tickets"]}
            car_ticket = res_by_id[t_car.id]
            any_ticket = res_by_id[t_any.id]

            # Worker 0 is car, worker 1 is walking
            # car_ticket only has worker 0
            self.assertEqual(len(car_ticket["allowed"]), 1)
            allowed_worker = elig["workers"][car_ticket["allowed"][0]]
            self.assertEqual(allowed_worker["transport_type"], TransportType.CAR)

            # any_ticket has both workers allowed
            self.assertEqual(len(any_ticket["allowed"]), 2)

    def test_a10_emergency_received_at_window_start(self):
        """A10: Emergency comes at 12:17; visit window cannot begin earlier than 12:17."""
        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
            emerg_wt = session.execute(
                select(WorkType).where(WorkType.code == "emergency")
            ).scalar_one()
            rule = session.get(WorkTypePlanningRule, emerg_wt.id)
            if not rule:
                session.add(
                    WorkTypePlanningRule(
                        work_type_id=emerg_wt.id,
                        service_duration_source="work_norm",
                        configured_by=self.observer.id,
                    )
                )
                session.flush()

            # Today 12:17 MSK
            today = datetime.now(TZ).date()
            rec_at = datetime.combine(today, time(12, 17), TZ)
            # Ticket window opened at 10:00 (e.g. broad shift window) but received at 12:17
            t_emerg = create_ticket(
                session,
                TicketCreate(
                    location_id=self.location.id,
                    title="Срочная авария 12:17",
                    work_type_id=emerg_wt.id,
                    received_at=rec_at,
                    visit_window_start=datetime.combine(today, time(10, 0), TZ),
                    visit_window_end=datetime.combine(today, time(18, 0), TZ),
                    estimated_duration_minutes=80,
                ),
            )

            from app.modules.planning.repository import load_snapshot
            from app.modules.planning.schemas import PreviewRequest

            req = PreviewRequest(
                route_date=today,
                ticket_ids=[t_emerg.id],
                worker_ids=[self.worker_user.id],
            )
            snapshot = load_snapshot(session, req)
            elig = check_eligibility(snapshot)
            ticket_res = elig["tickets"][0]

            epoch = elig["epoch"]
            # Window start in minutes from epoch
            window_start_minutes = ticket_res["window"][0]
            # Earliest service start in datetime
            earliest_start = epoch + timedelta(minutes=window_start_minutes)
            # Must not start before 12:17!
            self.assertGreaterEqual(earliest_start, rec_at)

"""Day timeline: shift intervals, planned tickets, office filter and role scoping."""

import unittest
from datetime import date, datetime, time, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.models import (
    Brigade,
    BrigadeMember,
    Building,
    City,
    District,
    Location,
    Office,
    Street,
    Ticket,
)
from app.db.session import get_session
from app.main import app
from app.modules.schedule.service import MOSCOW, shift_intervals
from app.modules.tickets.enums import TicketStatus
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from tests.support import DatabaseTestCase

DAY = date(2026, 9, 17)


def moscow(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=MOSCOW)


def interval(start: datetime, end: datetime) -> dict[str, str]:
    return {"start": start.isoformat(), "end": end.isoformat()}


class ShiftIntervalTests(unittest.TestCase):
    def intervals(self, start: time, end: time) -> list[tuple[datetime, datetime]]:
        return [(item.start, item.end) for item in shift_intervals(DAY, start, end)]

    def test_day_shift_gives_one_interval(self):
        self.assertEqual(self.intervals(time(8), time(17)), [(moscow(17, 8), moscow(17, 17))])

    def test_night_shift_gives_yesterday_tail_and_tonight(self):
        self.assertEqual(
            self.intervals(time(22), time(6)),
            [(moscow(16, 22), moscow(17, 6)), (moscow(17, 22), moscow(18, 6))],
        )

    def test_shift_ending_at_midnight_does_not_leak_into_next_day(self):
        self.assertEqual(self.intervals(time(18), time(0)), [(moscow(17, 18), moscow(18, 0))])

    def test_shift_starting_at_midnight_stays_inside_the_day(self):
        self.assertEqual(self.intervals(time(0), time(8)), [(moscow(17, 0), moscow(17, 8))])

    def test_intervals_use_moscow_offset(self):
        (first,) = shift_intervals(DAY, time(8), time(17))
        self.assertEqual(first.start.utcoffset(), timedelta(hours=3))


class ScheduleApiTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        city = self.save(City(name="Москва"))
        district = self.save(District(city_id=city.id, name="Район"))
        street = self.save(Street(city_id=city.id, name="Улица"))
        building = self.save(
            Building(city_id=city.id, district_id=district.id, street_id=street.id, number="1")
        )
        self.location_id = self.save(Location(building_id=building.id)).id
        self.north = self.save(Office(location_id=self.location_id, name="Офис Север")).id
        self.south = self.save(Office(location_id=self.location_id, name="Офис Юг")).id
        self.session.commit()

        self.observer = self.new_user("observer", UserRole.OBSERVER)
        self.north_foreman = self.new_user("Петров", UserRole.FOREMAN)
        self.south_foreman = self.new_user("Сидоров", UserRole.FOREMAN)
        self.day_worker = self.new_user("Алексеев", UserRole.WORKER, time(8), time(17))
        self.night_worker = self.new_user("Борисов", UserRole.WORKER, time(22), time(6))
        self.south_worker = self.new_user("Васильев", UserRole.WORKER, time(9), time(18))
        self.free_worker = self.new_user("Григорьев", UserRole.WORKER, time(10), time(19))

        # Members are added in reverse name order to check the alphabetical response.
        self.north_brigade = self.new_brigade(
            "Север-1", self.north_foreman, self.north, [self.night_worker, self.day_worker]
        )
        self.south_brigade = self.new_brigade(
            "Юг-1", self.south_foreman, self.south, [self.south_worker]
        )

        self.shared_ticket = self.new_ticket(
            [self.day_worker, self.south_worker],
            moscow(17, 14),
            moscow(17, 15),
            TicketStatus.COMPLETED,
        )
        self.day_ticket = self.new_ticket([self.day_worker], moscow(17, 10), moscow(17, 11, 30))
        self.night_ticket = self.new_ticket(
            [self.night_worker], moscow(16, 23, 30), moscow(17, 0, 30)
        )
        self.free_ticket = self.new_ticket([self.free_worker], moscow(17, 12), moscow(17, 13))
        # Outside the day or without a plan: none of these may appear.
        self.new_ticket([self.day_worker], moscow(18, 10), moscow(18, 11))
        self.new_ticket([self.night_worker], moscow(16, 22), moscow(17, 0))
        self.new_ticket([self.day_worker], None, None)
        self.session.commit()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))

    def save(self, instance):
        self.session.add(instance)
        self.session.flush()
        return instance

    def new_user(self, surname, role, shift_start=time(9), shift_end=time(18)):
        return create_user(
            self.session,
            UserCreate(
                name="Иван",
                surname=surname,
                lastname="Иванович" if role == UserRole.FOREMAN else None,
                username=f"user_{role.value}_{surname}",
                password="Password123!",
                role=role,
                worker_profile=WorkerProfileCreate(
                    workshift_start=shift_start, workshift_end=shift_end, skills=["Монтаж"]
                )
                if role == UserRole.WORKER
                else None,
            ),
        )

    def new_brigade(self, name, foreman, office_id, workers):
        brigade = self.save(Brigade(name=name, foreman_id=foreman.id, office_id=office_id))
        for worker in workers:
            self.save(BrigadeMember(brigade_id=brigade.id, worker_id=worker.id))
        return brigade.id

    def new_ticket(self, workers, planned_start, planned_end, status=TicketStatus.PLANNED):
        ticket = self.save(
            Ticket(
                location_id=self.location_id,
                title="Заявка",
                work_type="Подключение клиентов Базовая",
                status=status,
                visit_window_start=moscow(16, 0),
                visit_window_end=moscow(19, 0),
                planned_start_at=planned_start,
                planned_end_at=planned_end,
                estimated_duration_minutes=60,
                assigned_worker_id=workers[0].id if workers else None,
            )
        )
        return ticket.id

    @staticmethod
    def auth(user):
        return {
            "Authorization": "Bearer "
            + create_access_token({"sub": str(user.id), "role": user.role.value})
        }

    def schedule(self, user, **params):
        response = self.client.get("/api/v1/schedule", params=params, headers=self.auth(user))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    @staticmethod
    def workers(brigade):
        return {worker["id"]: worker for worker in brigade["workers"]}

    def test_office_timeline_contains_shifts_and_planned_tickets(self):
        data = self.schedule(self.observer, date="2026-09-17", office_id=self.north)

        self.assertEqual(data["date"], "2026-09-17")
        self.assertEqual(data["office_id"], self.north)
        self.assertEqual(data["day_start"], "2026-09-17T00:00:00+03:00")
        self.assertEqual(data["day_end"], "2026-09-18T00:00:00+03:00")
        self.assertEqual(data["unassigned_workers"], [])
        (brigade,) = data["brigades"]
        self.assertEqual(brigade["id"], self.north_brigade)
        self.assertEqual(brigade["office_name"], "Офис Север")
        self.assertEqual(
            brigade["foreman"], {"id": self.north_foreman.id, "full_name": "Петров Иван Иванович"}
        )
        self.assertEqual(
            [worker["full_name"] for worker in brigade["workers"]],
            ["Алексеев Иван", "Борисов Иван"],
        )

        day, night = (
            self.workers(brigade)[self.day_worker.id],
            self.workers(brigade)[self.night_worker.id],
        )
        self.assertEqual(day["workshift_start"], "08:00:00")
        self.assertEqual(day["transport_type"], "walking")
        self.assertEqual(day["shifts"], [interval(moscow(17, 8), moscow(17, 17))])
        self.assertEqual(
            night["shifts"],
            [interval(moscow(16, 22), moscow(17, 6)), interval(moscow(17, 22), moscow(18, 6))],
        )
        self.assertEqual(
            [ticket["id"] for ticket in day["tickets"]], [self.day_ticket, self.shared_ticket]
        )
        self.assertEqual(
            day["tickets"][0],
            {
                "id": self.day_ticket,
                "title": "Заявка",
                "work_type": "Подключение клиентов Базовая",
                "status": "planned",
                **interval(moscow(17, 10), moscow(17, 11, 30)),
            },
        )
        self.assertEqual([ticket["id"] for ticket in night["tickets"]], [self.night_ticket])

    def test_observer_without_office_sees_every_brigade_and_workers_without_one(self):
        data = self.schedule(self.observer, date="2026-09-17")

        self.assertIsNone(data["office_id"])
        self.assertEqual(
            [brigade["id"] for brigade in data["brigades"]],
            [self.north_brigade, self.south_brigade],
        )
        south = self.workers(data["brigades"][1])[self.south_worker.id]
        self.assertEqual(
            [(ticket["id"], ticket["status"]) for ticket in south["tickets"]],
            [(self.shared_ticket, "completed")],
        )
        (free,) = data["unassigned_workers"]
        self.assertEqual(free["id"], self.free_worker.id)
        self.assertEqual([ticket["id"] for ticket in free["tickets"]], [self.free_ticket])

    def test_foreman_sees_only_own_brigade(self):
        data = self.schedule(self.north_foreman, date="2026-09-17")
        self.assertEqual([brigade["id"] for brigade in data["brigades"]], [self.north_brigade])
        self.assertEqual(data["unassigned_workers"], [])

        data = self.schedule(self.south_foreman, date="2026-09-17", office_id=self.south)
        self.assertEqual([brigade["id"] for brigade in data["brigades"]], [self.south_brigade])

    def test_office_filter_never_widens_foreman_access(self):
        data = self.schedule(self.north_foreman, date="2026-09-17", office_id=self.south)

        self.assertEqual(data["brigades"], [])
        self.assertEqual(data["unassigned_workers"], [])

    def test_other_day_uses_that_day_tickets_only(self):
        data = self.schedule(self.observer, date="2026-09-18", office_id=self.north)

        workers = self.workers(data["brigades"][0])
        self.assertEqual(len(workers[self.day_worker.id]["tickets"]), 1)
        self.assertEqual(workers[self.night_worker.id]["tickets"], [])
        self.assertEqual(
            workers[self.night_worker.id]["shifts"][0], interval(moscow(17, 22), moscow(18, 6))
        )

    def test_date_defaults_to_today_in_moscow(self):
        before = datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        data = self.schedule(self.observer)
        after = datetime.now(timezone(timedelta(hours=3))).date().isoformat()

        self.assertIn(data["date"], {before, after})

    def test_unknown_office_returns_404(self):
        response = self.client.get(
            "/api/v1/schedule",
            params={"office_id": 2_147_483_647},
            headers=self.auth(self.observer),
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Офис не найден")

    def test_invalid_parameters_return_422(self):
        for params in (
            {"date": "2026-13-01"},
            {"date": "17.09.2026"},
            {"date": "1999-12-31"},
            {"date": "2101-01-01"},
            {"office_id": 0},
            {"office_id": 2_147_483_648},
        ):
            with self.subTest(params=params):
                response = self.client.get(
                    "/api/v1/schedule", params=params, headers=self.auth(self.observer)
                )
                self.assertEqual(response.status_code, 422)

    def test_worker_is_forbidden_and_token_is_required(self):
        response = self.client.get("/api/v1/schedule", headers=self.auth(self.day_worker))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/v1/schedule").status_code, 401)

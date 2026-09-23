"""Observer-managed worker availability and its planning-side effects."""

import unittest
from datetime import UTC, date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.models import (
    Building,
    City,
    District,
    Location,
    Route,
    Street,
    Ticket,
    TicketAssignment,
)
from app.db.session import get_session
from app.main import app
from app.modules.planning.eligibility import prepare
from app.modules.tickets.enums import TicketStatus
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from testing.database import migrated_schema
from tests.support import DatabaseTestCase


class WorkerLineStatusApiTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        city = self.save(City(name="Москва"))
        district = self.save(District(city_id=city.id, name="Тестовый район"))
        street = self.save(Street(city_id=city.id, name="Тестовая улица"))
        building = self.save(
            Building(
                city_id=city.id,
                district_id=district.id,
                street_id=street.id,
                number="1",
            )
        )
        self.location_id = self.save(Location(building_id=building.id)).id
        self.session.commit()

        self.observer = self.new_user("observer", UserRole.OBSERVER)
        self.foreman = self.new_user("foreman", UserRole.FOREMAN)
        self.worker = self.new_user("worker_one", UserRole.WORKER)
        self.other_worker = self.new_user("worker_two", UserRole.WORKER)

        self.planned_ticket = self.new_ticket(TicketStatus.PLANNED, [self.worker.id])
        self.shared_planned_ticket = self.new_ticket(
            TicketStatus.PLANNED, [self.worker.id, self.other_worker.id]
        )
        self.in_progress_ticket = self.new_ticket(TicketStatus.IN_PROGRESS, [self.worker.id])
        self.completed_ticket = self.new_ticket(TicketStatus.COMPLETED, [self.worker.id])
        self.wont_fix_ticket = self.new_ticket(TicketStatus.WONT_FIX, [self.worker.id])
        self.save(
            Route(
                worker_id=self.worker.id,
                route_date=date(2026, 9, 17),
                route_number=1,
                geojson={"type": "FeatureCollection", "features": []},
            )
        )
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

    def new_user(self, username: str, role: UserRole):
        return create_user(
            self.session,
            UserCreate(
                name="Иван",
                surname=username,
                username=username,
                password="Password123!",
                role=role,
                worker_profile=WorkerProfileCreate(
                    workshift_start="09:00:00",
                    workshift_end="18:00:00",
                    skills=["Монтаж"],
                )
                if role == UserRole.WORKER
                else None,
            ),
        )

    def new_ticket(self, status: TicketStatus, worker_ids: list[int]) -> int:
        start = datetime(2026, 9, 17, 10, tzinfo=UTC)
        ticket = self.save(
            Ticket(
                location_id=self.location_id,
                title=f"Заявка {status.value}",
                work_type="Монтаж",
                status=status,
                visit_window_start=start,
                visit_window_end=datetime(2026, 9, 17, 16, tzinfo=UTC),
                planned_start_at=start,
                planned_end_at=datetime(2026, 9, 17, 11, tzinfo=UTC),
                estimated_duration_minutes=60,
            )
        )
        for worker_id in worker_ids:
            self.save(TicketAssignment(ticket_id=ticket.id, worker_id=worker_id))
        return ticket.id

    @staticmethod
    def auth(user) -> dict[str, str]:
        token = create_access_token({"sub": str(user.id), "role": user.role.value})
        return {"Authorization": f"Bearer {token}"}

    def update_line_status(self, is_on_line: bool, *, user=None, worker_id=None):
        return self.client.put(
            f"/api/v1/workers/{worker_id or self.worker.id}/line-status",
            json={"is_on_line": is_on_line},
            headers=self.auth(user or self.observer),
        )

    def assigned_workers(self, ticket_id: int) -> list[int]:
        return list(
            self.session.execute(
                text(
                    "SELECT worker_id FROM ticket_assignments "
                    "WHERE ticket_id=:ticket_id ORDER BY worker_id"
                ),
                {"ticket_id": ticket_id},
            ).scalars()
        )

    def test_observer_takes_worker_off_line_and_releases_only_planned_work(self):
        response = self.update_line_status(False)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {
                "worker_id": self.worker.id,
                "is_on_line": False,
                "released_ticket_ids": sorted([self.planned_ticket, self.shared_planned_ticket]),
            },
        )
        self.assertEqual(self.assigned_workers(self.planned_ticket), [])
        self.assertEqual(self.assigned_workers(self.shared_planned_ticket), [self.other_worker.id])
        for ticket_id in (
            self.in_progress_ticket,
            self.completed_ticket,
            self.wont_fix_ticket,
        ):
            self.assertEqual(self.assigned_workers(ticket_id), [self.worker.id])

        solo_plan = self.session.execute(
            text("SELECT planned_start_at, planned_end_at FROM tickets WHERE id=:ticket_id"),
            {"ticket_id": self.planned_ticket},
        ).one()
        shared_plan = self.session.execute(
            text("SELECT planned_start_at, planned_end_at FROM tickets WHERE id=:ticket_id"),
            {"ticket_id": self.shared_planned_ticket},
        ).one()
        self.assertEqual(tuple(solo_plan), (None, None))
        self.assertTrue(all(shared_plan))
        self.assertEqual(
            self.session.execute(
                text("SELECT count(*) FROM routes WHERE worker_id=:worker_id"),
                {"worker_id": self.worker.id},
            ).scalar_one(),
            1,
        )

        profile = self.client.get(
            f"/api/v1/users/{self.worker.id}", headers=self.auth(self.observer)
        )
        self.assertEqual(profile.status_code, 200, profile.text)
        self.assertIs(profile.json()["worker_profile"]["is_on_line"], False)

        schedule = self.client.get(
            "/api/v1/schedule",
            params={"date": "2026-09-17"},
            headers=self.auth(self.observer),
        )
        self.assertEqual(schedule.status_code, 200, schedule.text)
        workers = {row["id"]: row for row in schedule.json()["unassigned_workers"]}
        self.assertIs(workers[self.worker.id]["is_on_line"], False)

    def test_repeated_updates_are_idempotent_and_return_does_not_restore_work(self):
        first = self.update_line_status(False)
        repeated_offline = self.update_line_status(False)
        returned = self.update_line_status(True)
        repeated_online = self.update_line_status(True)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(repeated_offline.status_code, 200, repeated_offline.text)
        self.assertEqual(repeated_offline.json()["released_ticket_ids"], [])
        self.assertEqual(
            returned.json(),
            {"worker_id": self.worker.id, "is_on_line": True, "released_ticket_ids": []},
        )
        self.assertEqual(repeated_online.status_code, 200, repeated_online.text)
        self.assertEqual(repeated_online.json()["released_ticket_ids"], [])
        self.assertEqual(self.assigned_workers(self.planned_ticket), [])
        self.assertEqual(
            self.session.execute(
                text("SELECT is_on_line FROM workers WHERE user_id=:worker_id"),
                {"worker_id": self.worker.id},
            ).scalar_one(),
            True,
        )

    def test_only_observer_can_change_line_status_and_target_must_be_worker(self):
        url = f"/api/v1/workers/{self.worker.id}/line-status"
        self.assertEqual(
            self.client.put(url, json={"is_on_line": False}).status_code,
            401,
        )
        self.assertEqual(
            self.update_line_status(False, user=self.worker).status_code,
            403,
        )
        self.assertEqual(
            self.update_line_status(False, user=self.foreman).status_code,
            403,
        )
        for worker_id in (self.observer.id, 2_147_483_647):
            with self.subTest(worker_id=worker_id):
                response = self.update_line_status(False, worker_id=worker_id)
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(response.json(), {"detail": "Исполнитель не найден"})

        invalid_type = self.client.put(
            url,
            json={"is_on_line": "false"},
            headers=self.auth(self.observer),
        )
        extra_field = self.client.put(
            url,
            json={"is_on_line": False, "reason": "test"},
            headers=self.auth(self.observer),
        )
        self.assertEqual(invalid_type.status_code, 422)
        self.assertEqual(extra_field.status_code, 422)

    def test_offline_worker_cannot_be_assigned_until_returned(self):
        self.assertEqual(self.update_line_status(False).status_code, 200)
        assignment_url = f"/api/v1/tickets/{self.shared_planned_ticket}/assignees"

        blocked = self.client.put(
            assignment_url,
            json={"worker_ids": [self.other_worker.id, self.worker.id]},
            headers=self.auth(self.observer),
        )
        self.assertEqual(blocked.status_code, 422, blocked.text)
        self.assertEqual(
            blocked.json(),
            {"detail": "Один или несколько исполнителей сняты с линии"},
        )
        self.assertEqual(self.assigned_workers(self.shared_planned_ticket), [self.other_worker.id])

        self.assertEqual(self.update_line_status(True).status_code, 200)
        assigned = self.client.put(
            assignment_url,
            json={"worker_ids": [self.other_worker.id, self.worker.id]},
            headers=self.auth(self.observer),
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)
        self.assertEqual(
            assigned.json()["assignee_ids"],
            sorted([self.worker.id, self.other_worker.id]),
        )

    def test_failure_rolls_back_status_and_released_assignments(self):
        with patch(
            "app.modules.users.repository.clear_planned_times_without_assignees",
            side_effect=RuntimeError("cannot clear plan"),
            create=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "cannot clear plan"):
                self.update_line_status(False)

        self.assertEqual(
            self.session.execute(
                text("SELECT is_on_line FROM workers WHERE user_id=:worker_id"),
                {"worker_id": self.worker.id},
            ).scalar_one(),
            True,
        )
        self.assertEqual(self.assigned_workers(self.planned_ticket), [self.worker.id])


class WorkerLineStatusMigrationTests(DatabaseTestCase):
    def test_upgrade_defaults_existing_workers_online_and_downgrade_keeps_profile(self):
        with migrated_schema(self.admin_engine, "0014") as (engine, config):
            with engine.begin() as connection:
                user_id = connection.execute(
                    text(
                        "INSERT INTO users (name,surname,username,password_hash,role) "
                        "VALUES ('Test','Worker','line_migration','hash','worker') RETURNING id"
                    )
                ).scalar_one()
                connection.execute(
                    text(
                        "INSERT INTO workers "
                        "(user_id,workshift_start,workshift_end,transport_type) "
                        "VALUES (:id,'09:00','18:00','walking')"
                    ),
                    {"id": user_id},
                )

            with engine.connect() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
                self.assertIs(
                    connection.execute(
                        text("SELECT is_on_line FROM workers WHERE user_id=:id"),
                        {"id": user_id},
                    ).scalar_one(),
                    True,
                )
                command.downgrade(config, "0014")
                self.assertNotIn(
                    "is_on_line",
                    {column["name"] for column in inspect(connection).get_columns("workers")},
                )
                self.assertEqual(
                    connection.execute(
                        text("SELECT user_id FROM workers WHERE user_id=:id"), {"id": user_id}
                    ).scalar_one(),
                    user_id,
                )


class WorkerLinePlanningEligibilityTests(unittest.TestCase):
    def test_offline_worker_is_excluded_before_other_eligibility_checks(self):
        snapshot = {
            "request": {
                "route_date": "2026-09-17",
                "ticket_ids": [],
                "worker_ids": [7],
                "allow_partial": True,
            },
            "tickets": [],
            "workers": [
                {
                    "user_id": 7,
                    "workshift_start": "09:00:00",
                    "workshift_end": "18:00:00",
                    "transport_type": "walking",
                    "is_on_line": False,
                }
            ],
            "roles": [{"id": 7, "role": "worker"}],
            "locations": [],
            "offices": [],
            "brigades": [],
            "members": [],
            "busy_tickets": [],
            "assignments": [],
            "skills": [],
            "work_types": [],
            "rules": [],
            "stocks": [],
            "reservations": [],
            "allocations": [],
            "required_appliances": [],
            "required_skills": [],
            "appliances": [],
        }

        prepared = prepare(
            snapshot,
            datetime(2026, 9, 16, 12, tzinfo=ZoneInfo("Europe/Moscow")),
        )

        self.assertEqual(prepared["workers"], [])
        self.assertEqual(
            prepared["excluded_workers"],
            [{"worker_id": 7, "reason": "worker_offline"}],
        )

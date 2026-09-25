"""T14/A29: role change, archive and deletion never lose history or end in a 500."""

from unittest.mock import patch
from uuid import uuid4

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import create_access_token
from app.db.models import (
    PlanningPlanRoute,
    Route,
    Ticket,
    TicketAssignment,
    User,
    Worker,
    WorkerAppliance,
)
from app.db.session import get_session
from app.main import app
from app.modules.data_exchange.formats import parse_file, serialize
from app.modules.data_exchange.service import import_data
from app.modules.planning import router as api
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from planning_scenarios import NOW, ROUTE_DATE, generate_planning_dataset, preview_request
from testing.database import migrated_schema
from tests.planning_fakes import FeasiblePlanner, provider_factory
from tests.support import CommittedDatabaseTestCase, DatabaseTestCase


class AppliedPlanHistoryTests(CommittedDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.data = generate_planning_dataset()
        with (
            Session(self.engine) as session,
            patch(
                "app.modules.data_exchange.service.hash_password",
                return_value="fixture-unused-hash",
            ),
        ):
            self.receipt = import_data(session, parse_file(serialize(self.data, "csv"), "data.zip"))
        self.ids = self.receipt["id_map"]
        self.payload = preview_request(self.receipt, self.data)
        self.settings = Settings(planning_enabled=True)

        def session_dependency():
            with Session(self.engine) as session:
                yield session

        overrides = {
            get_session: session_dependency,
            api.get_planning_engine: lambda: self.engine,
            api.planning_settings: lambda: self.settings,
            api.get_provider_factory: lambda: provider_factory,
            api.get_planner_client: FeasiblePlanner,
            api.get_clock: lambda: lambda: NOW,
        }
        app.dependency_overrides.update(overrides)
        self.addCleanup(lambda: [app.dependency_overrides.pop(k, None) for k in overrides])
        self.client = self.enterContext(TestClient(app))
        self.observer = self.auth(self.ids["users"]["1"])

        response = self.client.post(
            "/api/v1/planning/preview", json=self.payload, headers=self.observer
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.plan = response.json()
        applied = self.client.post(
            f"/api/v1/planning/plans/{self.plan['plan_id']}/apply", headers=self.observer
        )
        self.assertEqual(applied.status_code, 200, applied.text)
        route = self.plan["routes"][0]
        self.worker_id = route["worker_id"]
        self.worker_tickets = sorted(stop["ticket_id"] for stop in route["stops"])
        with Session(self.engine) as session:
            self.brigade_id = session.scalar(
                text("SELECT brigade_id FROM brigade_members WHERE worker_id = :id"),
                {"id": self.worker_id},
            )

    @staticmethod
    def auth(user_id):
        return {"Authorization": f"Bearer {create_access_token({'sub': str(user_id)})}"}

    def history(self):
        with Session(self.engine) as session:
            return tuple(
                session.scalar(
                    select(func.count()).select_from(model).where(column == self.worker_id)
                )
                for model, column in (
                    (Route, Route.worker_id),
                    (PlanningPlanRoute, PlanningPlanRoute.worker_id),
                    (TicketAssignment, TicketAssignment.worker_id),
                    (Worker, Worker.user_id),
                )
            )

    def finish_worker_tickets(self):
        with self.engine.begin() as connection:
            connection.execute(
                update(Ticket).where(Ticket.id.in_(self.worker_tickets)).values(status="completed")
            )

    def plan_worker(self):
        response = self.client.get(
            f"/api/v1/planning/plans/{self.plan['plan_id']}", headers=self.observer
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        [worker] = [w for w in body["workers"] if w["worker_id"] == self.worker_id]
        self.assertIn(self.worker_id, [r["worker_id"] for r in body["routes"]])
        return body, worker

    def assert_no_new_work(self):
        new_ticket = self.payload["ticket_ids"][0]
        assign = self.client.put(
            f"/api/v1/tickets/{new_ticket}/assignees",
            json={"worker_ids": [self.worker_id]},
            headers=self.observer,
        )
        self.assertEqual(assign.status_code, 422, assign.text)
        route = self.client.get(
            "/api/v1/routes", params={"worker_id": self.worker_id}, headers=self.observer
        )
        self.assertEqual(route.status_code, 200, route.text)
        self.assertEqual(len(route.json()), 1)
        line = self.client.put(
            f"/api/v1/workers/{self.worker_id}/line-status",
            json={"is_on_line": False},
            headers=self.observer,
        )
        self.assertEqual(line.status_code, 404, line.text)
        kit = self.client.post(
            f"/api/v1/workers/{self.worker_id}/equipment/issue",
            json={"operation_key": "t14-" + uuid4().hex, "date": ROUTE_DATE.isoformat()},
            headers=self.observer,
        )
        self.assertEqual(kit.status_code, 409, kit.text)
        self.assertEqual(kit.json()["detail"]["code"], "worker_inactive")
        schedule = self.client.get(
            "/api/v1/schedule", params={"date": ROUTE_DATE.isoformat()}, headers=self.observer
        )
        self.assertEqual(schedule.status_code, 200, schedule.text)
        body = schedule.json()
        scheduled = [w["id"] for b in body["brigades"] for w in b["workers"]]
        scheduled += [w["id"] for w in body["unassigned_workers"]]
        self.assertTrue(scheduled)
        self.assertNotIn(self.worker_id, scheduled)

    def test_role_change_after_apply_keeps_history_and_stops_new_work(self):
        before = self.history()
        self.assertEqual(before[0], 1)

        blocked = self.client.patch(
            f"/api/v1/users/{self.worker_id}", json={"role": "observer"}, headers=self.observer
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        detail = blocked.json()["detail"]
        self.assertEqual(detail["code"], "worker_has_active_work")
        self.assertEqual(detail["ticket_ids"], self.worker_tickets)

        self.finish_worker_tickets()
        changed = self.client.patch(
            f"/api/v1/users/{self.worker_id}", json={"role": "observer"}, headers=self.observer
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["role"], "observer")
        self.assertIsNone(changed.json()["worker_profile"])
        self.assertEqual(self.history(), before)

        body, worker = self.plan_worker()
        self.assertEqual(worker["role"], "observer")
        self.assertEqual(worker["brigade_id"], self.brigade_id)
        self.assertIsNotNone(worker["brigade_name"])
        self.assertIsNone(worker["archived_at"])
        self.assertIs(body["is_current"], False)
        brigade = self.client.get(f"/api/v1/brigades/{self.brigade_id}", headers=self.observer)
        self.assertNotIn(self.worker_id, brigade.json()["worker_ids"])
        self.assert_no_new_work()

        again = self.client.post(
            "/api/v1/planning/preview", json=self.payload, headers=self.observer
        )
        self.assertEqual(again.status_code, 201, again.text)
        excluded = {w["worker_id"]: w["reason"]["code"] for w in again.json()["excluded_workers"]}
        self.assertEqual(excluded[self.worker_id], "invalid_worker_role")

    def test_archive_keeps_history_hides_account_and_blocks_new_work(self):
        before = self.history()
        refused = self.client.post(f"/api/v1/users/{self.worker_id}/archive", headers=self.observer)
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertEqual(refused.json()["detail"]["ticket_ids"], self.worker_tickets)

        self.finish_worker_tickets()
        worker_token = self.auth(self.worker_id)
        self.assertEqual(self.client.get("/api/v1/users/me", headers=worker_token).status_code, 200)
        archived = self.client.post(
            f"/api/v1/users/{self.worker_id}/archive", headers=self.observer
        )
        self.assertEqual(archived.status_code, 200, archived.text)
        archived_at = archived.json()["archived_at"]
        self.assertIsNotNone(archived_at)
        repeated = self.client.post(
            f"/api/v1/users/{self.worker_id}/archive", headers=self.observer
        )
        self.assertEqual(repeated.json()["archived_at"], archived_at)
        self.assertEqual(self.history(), before)

        # The still valid access token opens nothing; the account is hidden from lists.
        self.assertEqual(self.client.get("/api/v1/users/me", headers=worker_token).status_code, 401)
        listed = self.client.get("/api/v1/users", headers=self.observer).json()
        self.assertNotIn(self.worker_id, [user["id"] for user in listed])
        everyone = self.client.get(
            "/api/v1/users", params={"include_archived": True}, headers=self.observer
        ).json()
        [shown] = [user for user in everyone if user["id"] == self.worker_id]
        self.assertEqual(shown["archived_at"], archived_at)
        self.assertEqual(shown["role"], "worker")
        self.assertIsNone(shown["brigade_id"])

        _, worker = self.plan_worker()
        self.assertEqual(worker["archived_at"], archived_at)
        self.assertEqual(worker["brigade_id"], self.brigade_id)
        self.assertTrue(worker["full_name"])
        self.assert_no_new_work()
        again = self.client.post(
            "/api/v1/planning/preview", json=self.payload, headers=self.observer
        )
        self.assertEqual(again.status_code, 201, again.text)
        [reason] = [
            w["reason"]
            for w in again.json()["excluded_workers"]
            if w["worker_id"] == self.worker_id
        ]
        self.assertEqual(reason["code"], "worker_archived")
        self.assertEqual(reason["category"], "availability")

        deleted = self.client.delete(f"/api/v1/users/{self.worker_id}", headers=self.observer)
        self.assertEqual(deleted.status_code, 409, deleted.text)
        detail = deleted.json()["detail"]
        self.assertEqual(detail["code"], "user_has_history")
        self.assertEqual(detail["links"]["routes"], 1)
        self.assertEqual(detail["links"]["planning_plan_routes"], 1)
        self.assertEqual(detail["links"]["ticket_assignments"], len(self.worker_tickets))
        self.assertIn("маршруты", detail["message"])
        self.assertIn(f"/api/v1/users/{self.worker_id}/archive", detail["message"])
        self.assertEqual(self.history(), before)

        restored = self.client.post(
            f"/api/v1/users/{self.worker_id}/restore", headers=self.observer
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertIsNone(restored.json()["archived_at"])
        self.assertEqual(self.client.get("/api/v1/users/me", headers=worker_token).status_code, 200)

    def test_equipment_on_hand_and_active_foreman_block_archive(self):
        self.finish_worker_tickets()
        appliance_id = self.ids["appliances"]["1"]
        with self.engine.begin() as connection:
            connection.execute(
                WorkerAppliance.__table__.insert().values(
                    worker_id=self.worker_id, appliance_id=appliance_id, quantity=2
                )
            )
        for request in (
            lambda: self.client.post(
                f"/api/v1/users/{self.worker_id}/archive", headers=self.observer
            ),
            lambda: self.client.patch(
                f"/api/v1/users/{self.worker_id}", json={"role": "foreman"}, headers=self.observer
            ),
        ):
            response = request()
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(
                response.json()["detail"]["equipment_on_hand"],
                [{"appliance_id": appliance_id, "quantity": 2}],
            )
        with Session(self.engine) as session:
            foreman_id = session.scalar(
                text("SELECT foreman_id FROM brigades WHERE id = :id"), {"id": self.brigade_id}
            )
            self.assertIsNone(session.get(User, self.worker_id).archived_at)
        response = self.client.post(f"/api/v1/users/{foreman_id}/archive", headers=self.observer)
        self.assertEqual(response.status_code, 409, response.text)
        own = self.ids["users"]["1"]
        response = self.client.post(f"/api/v1/users/{own}/archive", headers=self.observer)
        self.assertEqual(response.status_code, 400, response.text)
        missing = self.client.post("/api/v1/users/2147483647/archive", headers=self.observer)
        self.assertEqual(missing.status_code, 404, missing.text)
        worker_call = self.client.post(
            f"/api/v1/users/{self.worker_id}/archive", headers=self.auth(self.worker_id)
        )
        self.assertEqual(worker_call.status_code, 403, worker_call.text)

    def test_database_refuses_to_cascade_route_and_assignment_history(self):
        for statement in (
            "DELETE FROM workers WHERE user_id = :id",
            "DELETE FROM users WHERE id = :id",
        ):
            with self.subTest(statement=statement), self.assertRaises(IntegrityError):
                with self.engine.begin() as connection:
                    connection.execute(text(statement), {"id": self.worker_id})
        self.assertEqual(self.history()[0], 1)


class ArchivedAccountAuthTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))
        self.observer = create_user(
            self.session,
            UserCreate(
                name="Ольга",
                surname="Диспетчер",
                username="t14_observer",
                password="Password123!",
                role=UserRole.OBSERVER,
            ),
        )
        self.worker = create_user(
            self.session,
            UserCreate(
                name="Пётр",
                surname="Новиков",
                username="t14_worker",
                password="Password123!",
                role=UserRole.WORKER,
                worker_profile=WorkerProfileCreate(
                    workshift_start="09:00", workshift_end="18:00", skills=["Монтаж"]
                ),
            ),
        )
        self.session.commit()
        self.headers = {
            "Authorization": f"Bearer {create_access_token({'sub': str(self.observer.id)})}"
        }

    def login(self):
        return self.client.post(
            "/api/v1/auth/login", json={"username": "t14_worker", "password": "Password123!"}
        )

    def test_archived_account_cannot_sign_in_or_refresh_and_can_return(self):
        signed_in = self.login()
        self.assertEqual(signed_in.status_code, 200, signed_in.text)
        refresh_cookie = signed_in.cookies.get("refresh_token")
        self.assertTrue(refresh_cookie)

        archived = self.client.post(f"/api/v1/users/{self.worker.id}/archive", headers=self.headers)
        self.assertEqual(archived.status_code, 200, archived.text)

        refused = self.login()
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertEqual(refused.json()["detail"], "Учётная запись в архиве")
        wrong = self.client.post(
            "/api/v1/auth/login", json={"username": "t14_worker", "password": "Wrong123!"}
        )
        self.assertEqual(wrong.status_code, 401, wrong.text)
        self.client.cookies.set("refresh_token", refresh_cookie)
        self.assertEqual(self.client.post("/api/v1/auth/refresh").status_code, 401)
        self.client.cookies.clear()

        restored = self.client.post(f"/api/v1/users/{self.worker.id}/restore", headers=self.headers)
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(self.login().status_code, 200)

    def test_user_without_history_is_still_deleted(self):
        response = self.client.delete(f"/api/v1/users/{self.worker.id}", headers=self.headers)
        self.assertEqual(response.status_code, 204, response.text)
        missing = self.client.delete(f"/api/v1/users/{self.worker.id}", headers=self.headers)
        self.assertEqual(missing.status_code, 404, missing.text)


class MigrationKeepsRowsTests(DatabaseTestCase):
    def test_0023_keeps_rows_and_switches_history_keys_both_ways(self):
        with migrated_schema(self.admin_engine, "0022") as (engine, config):
            with engine.begin() as c:
                worker = c.execute(
                    text("""
                        INSERT INTO users (name, surname, username, password_hash, role)
                        VALUES ('Иван', 'Старый', 'legacy_worker', 'hash', 'worker')
                        RETURNING id
                    """)
                ).scalar_one()
                c.execute(
                    text("""
                        INSERT INTO workers (user_id, workshift_start, workshift_end)
                        VALUES (:w, '09:00', '18:00')
                    """),
                    {"w": worker},
                )
                c.execute(
                    text("""
                        INSERT INTO routes (worker_id, route_date, route_number, geojson)
                        VALUES (:w, '2026-09-25', 1,
                                '{"type": "FeatureCollection", "features": []}')
                    """),
                    {"w": worker},
                )

            def delete_rules(connection):
                return connection.execute(
                    text("""
                        SELECT conname, confdeltype FROM pg_constraint
                        WHERE conname IN (
                            'fk_routes_worker_id_workers',
                            'fk_ticket_assignments_worker_id_workers'
                        ) AND connamespace = to_regnamespace(current_schema())
                        ORDER BY conname
                    """)
                ).all()

            with engine.connect() as c:
                config.attributes["connection"] = c
                command.upgrade(config, "0023")
                self.assertEqual({rule for _, rule in delete_rules(c)}, {"r"})
                self.assertEqual(
                    c.execute(
                        text("SELECT archived_at FROM users WHERE id = :w"), {"w": worker}
                    ).scalar_one(),
                    None,
                )
                self.assertEqual(c.execute(text("SELECT count(*) FROM routes")).scalar_one(), 1)
                command.downgrade(config, "0022")
                self.assertEqual({rule for _, rule in delete_rules(c)}, {"c"})
                self.assertEqual(c.execute(text("SELECT count(*) FROM routes")).scalar_one(), 1)

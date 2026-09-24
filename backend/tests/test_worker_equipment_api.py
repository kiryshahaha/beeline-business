"""Equipment as an engineer's physical resource: kit, write-off once, explicit moves (T08)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.planning_guard import lock_planning_mutation
from app.core.security import create_access_token
from app.db.session import get_session
from app.main import app
from app.modules.appliances import inventory
from app.modules.planning.repository import load_snapshot
from app.modules.planning.schemas import PreviewRequest
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from testing.database import migrated_schema
from tests.support import CommittedDatabaseTestCase, DatabaseTestCase

MOSCOW = inventory.MOSCOW


def new_user(session, username, role):
    profile = (
        WorkerProfileCreate(workshift_start="09:00:00", workshift_end="18:00:00", skills=["Монтаж"])
        if role == UserRole.WORKER
        else None
    )
    return create_user(
        session,
        UserCreate(
            name="Имя",
            surname=username,
            username=username,
            password="Password123!",
            role=role,
            worker_profile=profile,
        ),
    )


def insert(connection, sql, **params):
    return connection.execute(text(sql), params).scalar_one()


def place(connection):
    city = insert(connection, "INSERT INTO cities (name) VALUES ('Город') RETURNING id")
    street = insert(
        connection, "INSERT INTO streets (name, city_id) VALUES ('Улица', :c) RETURNING id", c=city
    )
    district = insert(
        connection,
        "INSERT INTO districts (name, city_id) VALUES ('Район', :c) RETURNING id",
        c=city,
    )
    building = insert(
        connection,
        "INSERT INTO buildings (city_id, street_id, district_id, number)"
        " VALUES (:c, :s, :d, '1') RETURNING id",
        c=city,
        s=street,
        d=district,
    )
    return insert(
        connection, "INSERT INTO locations (building_id) VALUES (:b) RETURNING id", b=building
    )


class WorkerEquipmentApiTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))

        self.observer = new_user(self.session, "kit_observer", UserRole.OBSERVER)
        self.foreman = new_user(self.session, "kit_foreman", UserRole.FOREMAN)
        self.first = new_user(self.session, "kit_first", UserRole.WORKER)
        self.second = new_user(self.session, "kit_second", UserRole.WORKER)
        c = self.connection
        self.location = place(c)
        self.office = insert(
            c,
            "INSERT INTO offices (name, location_id) VALUES ('Склад', :l) RETURNING id",
            l=self.location,
        )
        brigade = insert(
            c,
            "INSERT INTO brigades (name, foreman_id, office_id) VALUES ('Альфа', :f, :o)"
            " RETURNING id",
            f=self.foreman.id,
            o=self.office,
        )
        for worker in (self.first, self.second):
            c.execute(
                text("INSERT INTO brigade_members (brigade_id, worker_id) VALUES (:b, :w)"),
                {"b": brigade, "w": worker.id},
            )
        self.router = self.appliance("Роутер", "CLIENT_ROUTER", stock=10)
        self.tv_box = self.appliance("Приставка", "TV_BOX", stock=5)
        self.tool = self.appliance("Сварочный аппарат", "TOOL", stock=3)
        self.day = inventory.today() + timedelta(days=1)
        # A13: the route needs 2 routers and 1 TV box.
        self.install = self.ticket(self.day, self.first, {self.router: 2, self.tool: 1})
        self.tv = self.ticket(self.day, self.first, {self.tv_box: 1})
        self.session.commit()

    def appliance(self, name, kind, stock):
        appliance_id = insert(
            self.connection,
            "INSERT INTO appliances (name, type) VALUES (:n, :t) RETURNING id",
            n=name,
            t=kind,
        )
        self.connection.execute(
            text(
                "INSERT INTO appliance_stocks (office_id, appliance_id, stock) VALUES (:o, :a, :s)"
            ),
            {"o": self.office, "a": appliance_id, "s": stock},
        )
        return appliance_id

    def ticket(self, day, worker, equipment):
        start = datetime.combine(day, time(10), MOSCOW)
        ticket_id = insert(
            self.connection,
            "INSERT INTO tickets (location_id, title, work_type, status, visit_window_start,"
            " visit_window_end, planned_start_at, planned_end_at, estimated_duration_minutes)"
            " VALUES (:l, 'Визит', 'Подключение', 'planned', :s, :e, :s, :pe, 60) RETURNING id",
            l=self.location,
            s=start,
            e=start + timedelta(hours=6),
            pe=start + timedelta(hours=1),
        )
        if worker is not None:
            self.connection.execute(
                text("UPDATE tickets SET assigned_worker_id = :w WHERE id = :t"),
                {"t": ticket_id, "w": worker.id},
            )
        for appliance_id, quantity in equipment.items():
            self.connection.execute(
                text(
                    "INSERT INTO ticket_appliances (ticket_id, appliance_id, office_id, quantity)"
                    " VALUES (:t, :a, :o, :q)"
                ),
                {"t": ticket_id, "a": appliance_id, "o": self.office, "q": quantity},
            )
        return ticket_id

    def headers(self, user=None):
        user = user or self.observer
        return {"Authorization": "Bearer " + create_access_token({"sub": str(user.id)})}

    def call(self, method, url, user=None, **kwargs):
        return self.client.request(method, url, headers=self.headers(user), **kwargs)

    def issue(self, worker, key, day=None, expected=200):
        response = self.call(
            "POST",
            f"/api/v1/workers/{worker.id}/equipment/issue",
            json={"operation_key": key, "date": (day or self.day).isoformat()},
        )
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def equipment(self, worker, day=None):
        response = self.call(
            "GET", f"/api/v1/workers/{worker.id}/equipment", params={"date": str(day or self.day)}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def hands(self, worker):
        return {
            i["appliance_id"]: (i["on_hand"], i["committed"], i["free"])
            for i in self.equipment(worker)["items"]
        }

    def stock(self, appliance_id):
        rows = self.call("GET", f"/api/v1/offices/{self.office}/stock").json()
        row = next(x for x in rows if x["appliance_id"] == appliance_id)
        return row["stock"], row["reserved"]

    def status(self, ticket_id, value, expected=200):
        response = self.call("PATCH", f"/api/v1/tickets/{ticket_id}/status", json={"status": value})
        self.assertEqual(response.status_code, expected, response.text)
        return response

    def execution_command(
        self, ticket_id, action, key, reason=None, worker_id=None, location_id=None
    ):
        revision = self.connection.execute(
            text("SELECT revision FROM tickets WHERE id = :ticket_id"),
            {"ticket_id": ticket_id},
        ).scalar_one()
        body = {
            "expected_revision": revision,
            "occurred_at": datetime.combine(self.day, time(12), MOSCOW).isoformat(),
            "payload": {},
        }
        if reason is not None:
            body["reason"] = reason
        if worker_id is not None:
            body["worker_id"] = worker_id
        if location_id is not None:
            body["location_id"] = location_id
        return self.client.post(
            f"/api/v1/tickets/{ticket_id}/{action}",
            json=body,
            headers=self.headers() | {"Idempotency-Key": key},
        )

    def operations(self, **params):
        response = self.call("GET", "/api/v1/equipment/operations", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def reserve(self, appliance_id, quantity):
        response = self.call(
            "PUT",
            f"/api/v1/offices/{self.office}/kit-reserve/{appliance_id}",
            json={"quantity": quantity},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_morning_kit_covers_assigned_tickets_and_declared_reserve(self):
        self.reserve(self.router, 1)
        kit = self.equipment(self.first)
        self.assertEqual(
            [
                (x["ticket_id"], x["appliance_id"], x["quantity"], x["purpose"])
                for x in kit["to_issue"]
            ],
            [
                (self.install, self.router, 2, "ticket"),
                (self.install, self.tool, 1, "ticket"),
                (self.tv, self.tv_box, 1, "ticket"),
                (None, self.router, 1, "reserve"),
            ],
        )
        self.assertEqual((kit["items"], kit["shortages"]), ([], []))
        self.assertEqual(self.stock(self.router), (10, 2))

        receipt = self.issue(self.first, "morning-1")
        self.assertFalse(receipt["already_applied"])
        self.assertEqual(receipt["kind"], "issue")
        self.assertEqual(len(receipt["movements"]), 4)
        self.assertTrue(
            all(
                m["from_office_id"] == self.office and m["to_worker_id"] == self.first.id
                for m in receipt["movements"]
            )
        )
        self.assertEqual(self.stock(self.router), (7, 0))
        self.assertEqual(self.stock(self.tv_box), (4, 0))
        self.assertEqual(
            self.hands(self.first),
            {self.router: (3, 2, 1), self.tool: (1, 1, 0), self.tv_box: (1, 1, 0)},
        )
        self.assertEqual(self.equipment(self.first)["to_issue"], [])

        retry = self.issue(self.first, "morning-1")
        self.assertEqual((retry["id"], retry["already_applied"]), (receipt["id"], True))
        self.assertEqual(self.stock(self.router), (7, 0))
        other_day = self.issue(
            self.first, "morning-1", day=self.day + timedelta(days=1), expected=409
        )
        self.assertEqual(other_day["detail"]["code"], "operation_key_conflict")
        again = self.issue(self.first, "morning-2", expected=409)
        self.assertEqual(again["detail"]["code"], "nothing_to_issue")

    def test_kit_is_not_issued_when_the_office_cannot_cover_the_reserve(self):
        self.reserve(self.router, 9)
        kit = self.equipment(self.first)
        self.assertEqual(
            kit["shortages"],
            [
                {
                    "office_id": self.office,
                    "appliance_id": self.router,
                    "stock": 10,
                    "reserved": 2,
                    "requested": 11,
                }
            ],
        )
        error = self.issue(self.first, "short", expected=409)["detail"]
        self.assertEqual(error["code"], "insufficient_stock")
        self.assertEqual(self.stock(self.router), (10, 2))
        self.assertEqual(self.hands(self.first), {})

    def test_write_off_happens_once_and_reopen_needs_an_explicit_restore(self):
        self.reserve(self.router, 1)
        self.issue(self.first, "morning")
        self.status(self.install, "completed")
        self.assertEqual(self.hands(self.first)[self.router], (1, 0, 1))
        self.assertEqual(self.hands(self.first)[self.tool], (1, 0, 1))
        self.assertEqual(self.stock(self.router), (7, 0))

        self.status(self.install, "planned", expected=403)
        self.status(self.install, "completed")
        self.assertEqual(self.hands(self.first)[self.router], (1, 0, 1))
        consumed = self.operations(ticket_id=self.install)
        self.assertEqual([op["kind"] for op in consumed], ["consume"])
        self.assertEqual(
            consumed[0]["movements"],
            [
                {
                    "appliance_id": self.router,
                    "quantity": 2,
                    "ticket_id": self.install,
                    "from_office_id": None,
                    "from_worker_id": self.first.id,
                    "to_office_id": None,
                    "to_worker_id": None,
                }
            ],
        )

        url = f"/api/v1/tickets/{self.install}/equipment/restore"
        body = {"operation_key": "restore-1", "reason": "Роутер снят у клиента"}
        response = self.call("POST", url, json=body)
        self.assertEqual(response.json()["detail"]["code"], "ticket_completed")
        self.status(self.install, "planned", expected=403)
        response = self.call("POST", url, json=body)
        self.assertEqual(response.json()["detail"]["code"], "ticket_completed")
        reopened = self.execution_command(
            self.install, "reopen", "reopen-install", "Повторный выезд"
        )
        self.assertEqual(reopened.status_code, 200, reopened.text)
        response = self.call("POST", url, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["movements"][0]["to_worker_id"], self.first.id)
        self.assertEqual(self.hands(self.first)[self.router], (3, 2, 1))

        assigned = self.call(
            "PUT",
            f"/api/v1/tickets/{self.install}/assignees",
            json={"worker_id": self.first.id},
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)
        for action, key in (
            ("dispatch", "dispatch-install-cycle-2"),
            ("start-route", "route-install-cycle-2"),
            ("start", "start-install-cycle-2"),
            ("complete", "complete-install-cycle-2"),
        ):
            response = self.execution_command(
                self.install,
                action,
                key,
                worker_id=self.first.id if action in {"start-route", "start", "complete"} else None,
                location_id=(
                    self.location if action in {"start-route", "start", "complete"} else None
                ),
            )
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.hands(self.first)[self.router], (1, 0, 1))
        self.assertEqual(
            [op["kind"] for op in self.operations(ticket_id=self.install)],
            ["consume", "restore", "consume"],
        )
        nothing = self.call("POST", url, json=body | {"operation_key": "restore-2"})
        self.assertEqual(nothing.json()["detail"]["code"], "ticket_completed")

    def test_completion_without_kit_writes_off_from_the_office_and_never_hides_a_shortage(self):
        self.status(self.install, "completed")
        self.assertEqual(self.stock(self.router), (8, 0))
        self.assertEqual(self.stock(self.tool), (3, 0))
        movement = self.operations(ticket_id=self.install)[0]["movements"][0]
        self.assertEqual(
            (movement["from_office_id"], movement["from_worker_id"]), (self.office, None)
        )
        self.status(self.install, "planned", expected=403)
        self.status(self.install, "completed")
        self.assertEqual(self.stock(self.router), (8, 0))

        self.connection.execute(
            text("UPDATE appliance_stocks SET stock = 0 WHERE appliance_id = :a"),
            {"a": self.tv_box},
        )
        error = self.status(self.tv, "completed", expected=409).json()["detail"]
        self.assertEqual(error["code"], "inventory_inconsistent")
        self.assertEqual((error["stock"], error["required"]), (0, 1))
        ticket = self.call("GET", f"/api/v1/tickets/{self.tv}").json()
        self.assertEqual(ticket["status"], "planned")
        self.assertEqual(self.stock(self.tv_box)[0], 0)

    def test_cancel_keeps_units_on_hand_and_return_is_explicit(self):
        self.issue(self.first, "morning")
        cancelled = self.execution_command(self.tv, "cancel", "cancel-tv", "Клиент отказался")
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(self.hands(self.first)[self.tv_box], (1, 0, 1))
        self.assertEqual(self.stock(self.tv_box), (4, 0))

        url = f"/api/v1/workers/{self.first.id}/equipment/return"
        response = self.call(
            "POST",
            url,
            json={"operation_key": "r1", "items": [{"appliance_id": self.tv_box, "quantity": 1}]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.stock(self.tv_box), (5, 0))
        self.assertNotIn(self.tv_box, self.hands(self.first))

        committed = self.call(
            "POST",
            url,
            json={"operation_key": "r2", "items": [{"appliance_id": self.router, "quantity": 2}]},
        )
        self.assertEqual(committed.status_code, 409, committed.text)
        self.assertEqual(
            {k: committed.json()["detail"][k] for k in ("code", "requested", "free")},
            {"code": "equipment_committed", "requested": 2, "free": 0},
        )
        released = self.call(
            "POST", url, json={"operation_key": "r3", "ticket_ids": [self.install]}
        )
        self.assertEqual(released.status_code, 200, released.text)
        self.assertEqual(self.stock(self.router), (10, 2))
        self.assertEqual(self.hands(self.first), {})
        foreign = self.call("POST", url, json={"operation_key": "r4", "ticket_ids": [self.install]})
        self.assertEqual(foreign.json()["detail"]["code"], "ticket_equipment_not_held")

    def test_issued_allocation_cannot_be_edited_silently(self):
        self.issue(self.first, "morning")
        base = f"/api/v1/tickets/{self.tv}/appliances/{self.tv_box}"
        self.assertEqual(self.call("PATCH", base, json={"quantity": 2}).status_code, 409)
        self.assertEqual(self.call("DELETE", base).status_code, 409)

    def test_reassignment_keeps_units_where_they_physically_are(self):
        self.issue(self.first, "morning")
        url = f"/api/v1/tickets/{self.install}/assignees"
        held = self.call("PUT", url, json={"worker_id": self.second.id})
        self.assertEqual(held.status_code, 409, held.text)
        self.assertEqual(held.json()["detail"]["code"], "equipment_held_by_worker")
        self.assertEqual(held.json()["detail"]["holder_worker_id"], self.first.id)

        self.reserve(self.router, 2)
        self.reserve(self.tool, 1)
        self.issue(self.second, "second-morning")
        moved = self.call("PUT", url, json={"worker_id": self.second.id})
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(self.hands(self.first)[self.router], (2, 0, 2))
        self.assertEqual(self.hands(self.second)[self.router], (2, 2, 0))

    def test_engineer_on_shift_gets_a_new_visit_only_with_units_on_hand(self):
        yesterday = self.day - timedelta(days=2)
        urgent = self.ticket(yesterday, None, {self.tv_box: 1})
        self.session.commit()
        response = self.call(
            "PUT", f"/api/v1/tickets/{urgent}/assignees", json={"worker_id": self.first.id}
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "equipment_not_on_hand")
        self.assertEqual(self.stock(self.tv_box), (5, 2))

        self.reserve(self.tv_box, 1)
        self.issue(self.first, "top-up", day=yesterday)
        response = self.call(
            "PUT", f"/api/v1/tickets/{urgent}/assignees", json={"worker_id": self.first.id}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.stock(self.tv_box), (4, 1))

        later = self.ticket(self.day, None, {self.tv_box: 1})
        self.session.commit()
        response = self.call(
            "PUT", f"/api/v1/tickets/{later}/assignees", json={"worker_id": self.second.id}
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_engineer_with_units_on_hand_keeps_the_worker_role(self):
        self.issue(self.first, "morning")
        response = self.call("PATCH", f"/api/v1/users/{self.first.id}", json={"role": "observer"})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.hands(self.first)[self.router], (2, 2, 0))

    def test_planning_snapshot_counts_only_units_still_in_the_office(self):
        spare = self.ticket(self.day, None, {self.router: 1})
        self.session.commit()
        request = PreviewRequest(
            route_date=self.day, ticket_ids=[spare], worker_ids=[self.second.id]
        )

        def reserved():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as s:
                rows = load_snapshot(s, request)["reservations"]
            return {(r["office_id"], r["appliance_id"]): r["quantity"] for r in rows}

        self.assertEqual(reserved()[(self.office, self.router)], 3)
        self.issue(self.first, "morning")
        self.assertEqual(reserved()[(self.office, self.router)], 1)

    def test_access_and_validation(self):
        url = f"/api/v1/workers/{self.first.id}/equipment"
        self.assertEqual(self.call("GET", url, user=self.first).status_code, 200)
        self.assertEqual(self.call("GET", url, user=self.foreman).status_code, 200)
        self.assertEqual(self.call("GET", url, user=self.second).status_code, 403)
        self.assertEqual(self.client.get(url).status_code, 401)
        issue = {"operation_key": "k", "date": self.day.isoformat()}
        self.assertEqual(
            self.call("POST", url + "/issue", user=self.first, json=issue).status_code, 403
        )
        self.assertEqual(
            self.call("GET", "/api/v1/equipment/operations", user=self.foreman).status_code, 403
        )
        self.assertEqual(
            self.call(
                "PUT",
                f"/api/v1/offices/{self.office}/kit-reserve/{self.router}",
                user=self.foreman,
                json={"quantity": 1},
            ).status_code,
            403,
        )
        missing = self.call("GET", "/api/v1/workers/2147483647/equipment")
        self.assertEqual(missing.json()["detail"]["code"], "worker_not_found")
        for body in ({"operation_key": "x"}, {"operation_key": "x", "items": [], "ticket_ids": []}):
            response = self.call("POST", url + "/return", json=body)
            self.assertEqual(response.status_code, 422, response.text)
        self.reserve(self.router, 2)
        self.reserve(self.router, 0)
        self.assertEqual(self.call("GET", f"/api/v1/offices/{self.office}/kit-reserve").json(), [])


class ConcurrentIssueTests(CommittedDatabaseTestCase):
    def test_last_free_unit_is_issued_once(self):
        with Session(self.engine) as session:
            observer = new_user(session, "race_observer", UserRole.OBSERVER)
            workers = [new_user(session, f"race_{i}", UserRole.WORKER) for i in range(2)]
            foremen = [new_user(session, f"race_foreman_{i}", UserRole.FOREMAN) for i in range(2)]
        with self.engine.begin() as c:
            location = place(c)
            office = insert(
                c,
                "INSERT INTO offices (name, location_id) VALUES ('Склад', :l) RETURNING id",
                l=location,
            )
            for i, (worker, foreman) in enumerate(zip(workers, foremen, strict=True)):
                brigade = insert(
                    c,
                    "INSERT INTO brigades (name, foreman_id, office_id) VALUES (:n, :f, :o)"
                    " RETURNING id",
                    n=f"Бригада {i}",
                    f=foreman.id,
                    o=office,
                )
                c.execute(
                    text("INSERT INTO brigade_members (brigade_id, worker_id) VALUES (:b, :w)"),
                    {"b": brigade, "w": worker.id},
                )
            router = insert(
                c,
                "INSERT INTO appliances (name, type) VALUES ('Роутер', 'CLIENT_ROUTER')"
                " RETURNING id",
            )
            for table, column in (
                ("appliance_stocks", "stock"),
                ("office_kit_reserves", "quantity"),
            ):
                c.execute(
                    text(
                        f"INSERT INTO {table} (office_id, appliance_id, {column})"
                        " VALUES (:o, :a, 1)"
                    ),
                    {"o": office, "a": router},
                )
        observer_id, worker_ids = observer.id, [w.id for w in workers]
        day = inventory.today()

        def issue(worker_id):
            try:
                with Session(self.engine) as session, session.begin():
                    lock_planning_mutation(session)
                    inventory.issue_kit(session, worker_id, day, f"race-{worker_id}", observer_id)
                return "issued"
            except inventory.InventoryError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = sorted(pool.map(issue, worker_ids))
        self.assertEqual(results, ["insufficient_stock", "issued"])
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(text("SELECT stock FROM appliance_stocks")).scalar_one(), 0
            )
            self.assertEqual(
                connection.execute(
                    text("SELECT sum(quantity) FROM worker_appliances")
                ).scalar_one(),
                1,
            )


class LegacyWriteOffMigrationTests(DatabaseTestCase):
    def test_tickets_completed_before_the_journal_are_not_written_off_again(self):
        with migrated_schema(self.admin_engine, "0015") as (engine, config):
            with engine.begin() as c:
                office, router, tickets = self.legacy_rows(c)
            with engine.connect() as c:
                config.attributes["connection"] = c
                command.upgrade(config, "0016")
                states = c.execute(
                    text("SELECT ticket_id, appliance_id FROM ticket_appliance_states")
                ).all()
                self.assertEqual(states, [(tickets["completed"], router)])
                movement = c.execute(
                    text(
                        "SELECT m.quantity, m.from_office_id, o.kind, o.actor_id"
                        " FROM appliance_movements m"
                        " JOIN appliance_operations o ON o.id = m.operation_id"
                    )
                ).one()
                self.assertEqual(tuple(movement), (2, office, "consume", None))

    def legacy_rows(self, c):
        location = place(c)
        office = insert(
            c,
            "INSERT INTO offices (name, location_id) VALUES ('Склад', :l) RETURNING id",
            l=location,
        )
        router = insert(
            c, "INSERT INTO appliances (name, type) VALUES ('Роутер', 'CLIENT_ROUTER') RETURNING id"
        )
        tool = insert(c, "INSERT INTO appliances (name, type) VALUES ('Ключ', 'TOOL') RETURNING id")
        tickets = {}
        for status in ("completed", "planned"):
            tickets[status] = insert(
                c,
                "INSERT INTO tickets (location_id, title, work_type, status, visit_window_start,"
                " visit_window_end, estimated_duration_minutes)"
                " VALUES (:l, 'Визит', 'Подключение', :s, now(), now() + interval '1 hour', 30)"
                " RETURNING id",
                l=location,
                s=status,
            )
            for appliance_id in (router, tool):
                c.execute(
                    text(
                        "INSERT INTO ticket_appliances (ticket_id, appliance_id, office_id,"
                        " quantity) VALUES (:t, :a, :o, 2)"
                    ),
                    {"t": tickets[status], "a": appliance_id, "o": office},
                )
        return office, router, tickets

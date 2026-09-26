"""T23: structured logs without secrets, bounded planning lock, WebSocket recovery in the
supported single-process mode, and retention that keeps applied history (A20/A25/A38)."""

import asyncio
import json
import logging
import time
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker
from starlette.websockets import WebSocketDisconnect

from app.core import oplog
from app.core.planning_guard import PlanningLockTimeout, lock_planning_mutation
from app.core.security import create_access_token
from app.db.models import Building, City, District, Location, ServiceArea, Street, Ticket
from app.db.session import get_session
from app.main import app
from app.modules.maintenance import retention
from app.modules.notifications.connections import ConnectionManager
from app.modules.notifications.topology import DeliveryLease, delivery_state
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate
from app.modules.users.service import create_user
from tests.support import CommittedDatabaseTestCase, DatabaseTestCase

JWT_LIKE = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI0MiJ9.Sig_Nature-Value"


class OperationLogTests(unittest.TestCase):
    def test_only_identifiers_and_numbers_survive(self):
        cleaned = oplog.safe_fields(
            {
                "plan_id": uuid4(),
                "route_date": datetime(2030, 1, 15, tzinfo=UTC).date(),
                "assigned_tickets": 7,
                "duration_ms": 12.34567,
                "outcome": "plan_stale",
                "access_token": "anything",
                "authorization": "Bearer abc",
                "address": "Тверская, 4",
                "title": "Монтаж у клиента",
                "reason": "Клиент попросил перезвонить после обеда",
                "note": JWT_LIKE,
                "stages": {"snapshot": {"calls": 2, "duration_ms": 1.5}},
            }
        )
        self.assertEqual(
            set(cleaned),
            {"plan_id", "route_date", "assigned_tickets", "duration_ms", "outcome", "stages"},
        )
        self.assertEqual(cleaned["duration_ms"], 12.346)
        self.assertEqual(cleaned["stages"], {"snapshot": {"calls": 2, "duration_ms": 1.5}})

    def test_operation_writes_one_json_line_with_stages_and_outcome(self):
        oplog.configure("INFO")
        with self.assertLogs(oplog.LOGGER_NAME, level="INFO") as captured:
            oplog.bind_request_id("req-12345678")
            with self.assertRaises(PlanningLockTimeout):
                with oplog.operation("planning.apply", plan_id="p-1") as fields:
                    oplog.record_stage("lock_wait", 0.25)
                    fields.update(routes=3)
                    raise PlanningLockTimeout(250, 200)
        (record,) = captured.records
        self.assertEqual(record.levelno, logging.WARNING)
        line = json.loads(oplog.JsonFormatter().format(record))
        self.assertEqual(line["event"], "planning.apply")
        self.assertEqual(line["request_id"], "req-12345678")
        self.assertEqual(line["outcome"], "planning_lock_timeout")
        self.assertEqual(line["routes"], 3)
        self.assertEqual(line["stages"]["lock_wait"], {"calls": 1, "duration_ms": 250.0})

    def test_stage_outside_an_operation_is_ignored(self):
        oplog.record_stage("snapshot", 1.0)  # no trace: nothing to record, nothing raised


class ConnectionReplayTests(unittest.TestCase):
    class Socket:
        def __init__(self):
            self.messages = []

        async def send_json(self, payload):
            self.messages.append(payload)

    def test_an_event_replayed_and_then_published_reaches_the_socket_once(self):
        manager, socket = ConnectionManager(), self.Socket()

        async def scenario():
            await manager.connect(5, socket)
            replayed = await manager.send(5, socket, {"id": 41, "kind": "ticket_assigned"})
            delivered = await manager.publish(5, {"id": 41, "kind": "ticket_assigned"})
            fresh = await manager.publish(5, {"id": 42, "kind": "ticket_assigned"})
            return replayed, delivered, fresh

        replayed, delivered, fresh = asyncio.run(scenario())
        self.assertTrue(replayed)
        self.assertEqual((delivered, fresh), (1, 1))
        self.assertEqual([message["id"] for message in socket.messages], [41, 42])


class RequestIdTests(unittest.TestCase):
    def setUp(self):
        self.client = self.enterContext(TestClient(app))

    def test_generated_when_absent_echoed_when_valid_replaced_when_malformed(self):
        generated = self.client.get("/health").headers["x-request-id"]
        self.assertRegex(generated, r"^[0-9a-f]{32}$")
        echoed = self.client.get("/health", headers={"X-Request-ID": "client-req-0001"})
        self.assertEqual(echoed.headers["x-request-id"], "client-req-0001")
        replaced = self.client.get("/health", headers={"X-Request-ID": "bad id\\n<script>"})
        self.assertRegex(replaced.headers["x-request-id"], r"^[0-9a-f]{32}$")


class AddressFixture(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        city = self.save(City(name="Москва"))
        district = self.save(District(city_id=city.id, name="Район"))
        street = self.save(Street(city_id=city.id, name="Улица"))
        building = self.save(
            Building(
                city_id=city.id,
                street_id=street.id,
                service_area_id=self.service_area_for_district(district.id),
                number="1",
            )
        )
        self.location_id = self.save(Location(building_id=building.id)).id
        self.user = create_user(
            self.session,
            UserCreate(
                name="Тест",
                surname="Диспетчер",
                username="t23_observer",
                password="Password123!",
                role=UserRole.OBSERVER,
            ),
        )
        self.session.commit()

        def session_dependency():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as s:
                yield s

        app.dependency_overrides[get_session] = session_dependency
        self.addCleanup(app.dependency_overrides.pop, get_session)

    def save(self, instance):
        self.session.add(instance)
        self.session.flush()
        return instance

    def headers(self):
        return {"Authorization": "Bearer " + create_access_token({"sub": str(self.user.id)})}


def hold_planning_lock(test) -> None:
    """Another transaction holds the shared lock until the test ends."""
    holder = test.engine.connect()
    test.addCleanup(holder.close)
    holder.begin()
    # A mistake in a test must fail, not hang the whole run.
    holder.execute(text("SET LOCAL lock_timeout = '5s'"))
    holder.execute(text("SELECT pg_advisory_xact_lock(17321, 1)"))


class PlanningLockTests(CommittedDatabaseTestCase):
    """Committed transactions: an outer test transaction would itself hold the lock."""

    def setUp(self):
        super().setUp()
        with Session(self.engine) as session:
            city = City(name="Москва")
            session.add(city)
            session.flush()
            street = Street(city_id=city.id, name="Улица")
            area = ServiceArea(code="t23_area", name="Участок")
            session.add_all([street, area])
            session.flush()
            building = Building(
                city_id=city.id, street_id=street.id, service_area_id=area.id, number="1"
            )
            session.add(building)
            session.flush()
            location = Location(building_id=building.id)
            session.add(location)
            session.commit()
            self.location_id = location.id
            self.user = create_user(
                session,
                UserCreate(
                    name="Тест",
                    surname="Диспетчер",
                    username="t23_lock_observer",
                    password="Password123!",
                    role=UserRole.OBSERVER,
                ),
            )
            session.commit()

        def session_dependency():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = session_dependency
        self.addCleanup(app.dependency_overrides.pop, get_session)

    def test_wait_is_bounded_and_measured(self):
        hold_planning_lock(self)
        with Session(self.engine) as session, session.begin():
            started = time.perf_counter()
            with self.assertLogs(oplog.LOGGER_NAME, level="WARNING") as captured:
                with self.assertRaises(PlanningLockTimeout) as raised:
                    lock_planning_mutation(session, timeout_seconds=0.2)
            elapsed = time.perf_counter() - started
        self.assertGreaterEqual(raised.exception.waited_ms, 150)
        self.assertEqual(raised.exception.timeout_ms, 200)
        self.assertLess(elapsed, 2)
        self.assertIn("planning.lock_timeout", captured.output[0])

    def test_contention_is_a_retryable_503_and_nothing_is_written(self):
        hold_planning_lock(self)
        client = self.enterContext(TestClient(app))
        headers = {"Authorization": "Bearer " + create_access_token({"sub": str(self.user.id)})}
        with patch("app.core.planning_guard._timeout_seconds", return_value=0.2):
            response = client.post(
                "/api/v1/offices/",
                json={"name": "Офис под замком", "location_id": self.location_id},
                headers=headers,
            )
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.headers["retry-after"], "2")
        detail = response.json()["detail"]
        self.assertEqual((detail["code"], detail["retryable"]), ("planning_lock_timeout", True))
        with Session(self.engine) as session:
            self.assertEqual(
                session.execute(
                    text("SELECT count(*) FROM offices WHERE name = 'Офис под замком'")
                ).scalar_one(),
                0,
            )

    def test_free_lock_records_its_wait_in_the_trace(self):
        with oplog.operation("test.lock"):
            with Session(self.engine) as session, session.begin():
                lock_planning_mutation(session)
                trace = oplog._trace.get()
                self.assertEqual(trace["stages"]["lock_wait"]["calls"], 1)


class WebSocketRecoveryTests(AddressFixture):
    def setUp(self):
        super().setUp()
        ticket = self.save(
            Ticket(
                location_id=self.location_id,
                title="Заявка",
                work_type="Настройка сети",
                visit_window_start=datetime.now(UTC),
                visit_window_end=datetime.now(UTC) + timedelta(hours=2),
                estimated_duration_minutes=60,
            )
        )
        self.event_ids = [
            self.session.execute(
                text(
                    "INSERT INTO notification_events (recipient_id, ticket_id, kind, data) "
                    "VALUES (:user, :ticket, 'ticket_assigned', CAST(:data AS JSONB)) "
                    "RETURNING id"
                ),
                {"user": self.user.id, "ticket": ticket.id, "data": json.dumps({"n": n})},
            ).scalar_one()
            for n in range(3)
        ]
        self.session.commit()
        self.client = self.enterContext(TestClient(app))

    def connect(self, **extra):
        websocket = self.enterContext(self.client.websocket_connect("/api/v1/notifications/ws"))
        websocket.send_json(
            {
                "type": "authenticate",
                "token": create_access_token({"sub": str(self.user.id)}),
                **extra,
            }
        )
        return websocket

    def test_reconnect_replays_what_was_missed_in_order(self):
        websocket = self.connect(last_event_id=self.event_ids[0])
        self.assertEqual(websocket.receive_json()["type"], "authenticated")
        replayed = [websocket.receive_json(), websocket.receive_json()]
        self.assertEqual([item["id"] for item in replayed], self.event_ids[1:])
        self.assertEqual(
            set(replayed[0]), {"id", "recipient_id", "ticket_id", "kind", "data", "created_at"}
        )
        websocket.send_json({"type": "ping"})
        self.assertEqual(websocket.receive_json(), {"type": "pong"})

    def test_http_history_pages_forward_without_gaps(self):
        response = self.client.get(
            "/api/v1/notifications",
            params={"after_id": self.event_ids[0], "limit": 1},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["id"] for item in response.json()], [self.event_ids[1]])

    def test_invalid_resume_cursor_is_rejected(self):
        websocket = self.connect(last_event_id="yesterday")
        with self.assertRaises(WebSocketDisconnect) as closed:
            websocket.receive_json()
        self.assertEqual(closed.exception.code, 1008)

    def test_process_without_the_delivery_role_refuses_live_sockets(self):
        previous = delivery_state.lease
        delivery_state.lease = DeliveryLease(self.engine)  # never acquired: not held
        self.addCleanup(setattr, delivery_state, "lease", previous)
        websocket = self.connect()
        with self.assertRaises(WebSocketDisconnect) as closed:
            websocket.receive_json()
        self.assertEqual(closed.exception.code, 1013)


class DeliveryLeaseTests(DatabaseTestCase):
    def test_only_one_process_holds_the_delivery_role(self):
        first, second = DeliveryLease(self.engine), DeliveryLease(self.engine)
        self.addCleanup(first.release)
        self.addCleanup(second.release)
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        self.assertTrue(first.alive())
        first.release()
        self.assertTrue(second.acquire(), "the role moves once the holder lets it go")


class RetentionTests(AddressFixture):
    def plan(self, *, state, expires_at):
        applied = state == "applied"
        plan_id = uuid4()
        self.session.execute(
            text(
                "INSERT INTO planning_plans (id, route_date, created_by, expires_at, state, "
                "input_fingerprint, input_snapshot, result_snapshot, applied_at, "
                "applied_fingerprint, apply_result) VALUES (:id, :day, :user, :expires, :state, "
                "'f', '{}'::jsonb, '{}'::jsonb, :applied_at, :applied_fp, "
                "CAST(:apply_result AS JSONB))"
            ),
            {
                "id": plan_id,
                "day": expires_at.date(),
                "user": self.user.id,
                "expires": expires_at,
                "state": state,
                "applied_at": expires_at if applied else None,
                "applied_fp": "f" if applied else None,
                "apply_result": "{}" if applied else None,
            },
        )
        return plan_id

    def test_expired_unapplied_previews_go_and_applied_history_stays(self):
        now = datetime(2030, 1, 20, 12, tzinfo=UTC)
        old_ready = self.plan(state="ready", expires_at=now - timedelta(days=3))
        old_stale = self.plan(state="stale", expires_at=now - timedelta(days=2))
        recent = self.plan(state="expired", expires_at=now - timedelta(hours=1))
        applied = self.plan(state="applied", expires_at=now - timedelta(days=30))
        self.session.commit()
        windows = {"preview_retention": timedelta(hours=24), "notification_retention": None}

        self.assertEqual(
            retention.count_candidates(self.session, now=now, **windows),
            {"expired_previews": 2, "settled_notifications": 0},
        )
        factory = sessionmaker(bind=self.connection, join_transaction_mode="create_savepoint")
        deleted = retention.purge(factory, now=now, batch=1, **windows)

        self.assertEqual(deleted["expired_previews"], 2)
        left = set(self.session.execute(text("SELECT id FROM planning_plans")).scalars())
        self.assertEqual(left, {recent, applied})
        self.assertFalse({old_ready, old_stale} & left)

    def test_a_pass_already_running_elsewhere_is_skipped(self):
        holder = self.engine.connect()
        self.addCleanup(holder.close)
        holder.execute(text("SELECT pg_advisory_lock(17321, 3)"))
        holder.commit()
        self.assertIsNone(
            retention.run_cleanup(
                self.engine,
                now=datetime.now(UTC),
                preview_retention=timedelta(hours=24),
                notification_retention=None,
            )
        )

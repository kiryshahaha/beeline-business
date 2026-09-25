"""Durable event delivery at real PostgreSQL boundaries with a fake FCM gateway."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db.models import Building, City, District, Location, Street, Ticket
from app.modules.notifications.dispatcher import NotificationDispatcher
from app.modules.notifications.firebase import PushResult
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate
from app.modules.users.service import create_user
from tests.support import DatabaseTestCase


class FakeConnectionManager:
    def __init__(self):
        self.messages = []

    async def publish(self, user_id, payload):
        self.messages.append((user_id, payload))
        return 1


class FakePushGateway:
    enabled = True

    def __init__(self, *, invalid_tokens=(), error=None):
        self.invalid_tokens = set(invalid_tokens)
        self.error = error
        self.calls = []

    def send(self, tokens, *, title, body, data):
        self.calls.append({"tokens": tokens, "title": title, "body": body, "data": data})
        if self.error is not None:
            raise self.error
        return PushResult(invalid_tokens=self.invalid_tokens)


class NotificationsDeliveryTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        city = self.save(City(name="Санкт-Петербург"))
        district = self.save(District(city_id=city.id, name="Невский район"))
        street = self.save(Street(city_id=city.id, name="Тестовая улица"))
        building = self.save(
            Building(
                city_id=city.id,
                street_id=street.id,
                service_area_id=self.service_area_for_district(district.id),
                number="13",
            )
        )
        location = self.save(Location(building_id=building.id))
        self.ticket = self.save(
            Ticket(
                location_id=location.id,
                title="Настроить Wi-Fi",
                work_type="Настройка сети",
                visit_window_start=datetime.now(UTC),
                visit_window_end=datetime.now(UTC) + timedelta(hours=2),
                estimated_duration_minutes=60,
            )
        )
        self.session.commit()
        self.user = create_user(
            self.session,
            UserCreate(
                name="Тест",
                surname="Наблюдатель",
                username="delivery_observer",
                password="Password123!",
                role=UserRole.OBSERVER,
            ),
        )
        self.session.commit()
        self.session_factory = sessionmaker(
            bind=self.connection,
            join_transaction_mode="create_savepoint",
        )

    def save(self, instance):
        self.session.add(instance)
        self.session.flush()
        return instance

    def add_subscription(self, token_value="firebase-token"):
        self.session.execute(
            text("""
                INSERT INTO push_subscriptions (user_id, token)
                VALUES (:user_id, :token)
            """),
            {"user_id": self.user.id, "token": token_value},
        )
        self.session.commit()
        return token_value

    def add_event(self, kind="ticket_status_changed"):
        event_id = self.session.execute(
            text("""
                INSERT INTO notification_events (recipient_id, ticket_id, kind, data)
                VALUES (:recipient_id, :ticket_id, :kind, CAST(:data AS JSONB))
                RETURNING id
            """),
            {
                "recipient_id": self.user.id,
                "ticket_id": self.ticket.id,
                "kind": kind,
                "data": json.dumps(
                    {
                        "title": self.ticket.title,
                        "previous_status": "planned",
                        "status": "in_progress",
                        "actor_id": self.user.id,
                    }
                ),
            },
        ).scalar_one()
        self.session.commit()
        return event_id

    def read_event(self, event_id):
        self.session.expire_all()
        return (
            self.session.execute(
                text("""
                SELECT websocket_delivered_at, push_delivered_at, attempt_count,
                       next_attempt_at, last_error
                FROM notification_events
                WHERE id = :event_id
            """),
                {"event_id": event_id},
            )
            .mappings()
            .one()
        )

    def dispatch(self, gateway):
        manager = FakeConnectionManager()
        dispatcher = NotificationDispatcher(
            self.session_factory,
            connection_manager=manager,
            push_gateway=gateway,
        )
        processed = asyncio.run(dispatcher.dispatch_once())
        return processed, manager

    def test_successful_event_reaches_websocket_and_firebase_once(self):
        token_value = self.add_subscription()
        event_id = self.add_event()
        gateway = FakePushGateway()

        processed, manager = self.dispatch(gateway)

        self.assertEqual(processed, 1)
        self.assertEqual(manager.messages[0][0], self.user.id)
        payload = manager.messages[0][1]
        self.assertEqual(payload["id"], event_id)
        self.assertEqual(payload["kind"], "ticket_status_changed")
        self.assertEqual(payload["data"]["status"], "in_progress")
        self.assertEqual(gateway.calls[0]["tokens"], [token_value])
        self.assertEqual(gateway.calls[0]["title"], "Статус заявки изменён")
        self.assertIn("Настроить Wi-Fi", gateway.calls[0]["body"])
        self.assertTrue(all(isinstance(value, str) for value in gateway.calls[0]["data"].values()))
        stored = self.read_event(event_id)
        self.assertIsNotNone(stored["websocket_delivered_at"])
        self.assertIsNotNone(stored["push_delivered_at"])
        self.assertEqual(stored["attempt_count"], 0)
        self.assertIsNone(stored["last_error"])

    def test_invalid_firebase_token_is_removed_after_delivery(self):
        token_value = self.add_subscription("invalid-token")
        event_id = self.add_event()
        gateway = FakePushGateway(invalid_tokens={token_value})

        processed, _manager = self.dispatch(gateway)

        self.assertEqual(processed, 1)
        tokens = self.session.execute(text("SELECT token FROM push_subscriptions")).scalars().all()
        self.assertEqual(tokens, [])
        self.assertIsNotNone(self.read_event(event_id)["push_delivered_at"])

    def test_event_without_browser_subscription_remains_in_history(self):
        event_id = self.add_event()
        gateway = FakePushGateway()

        processed, manager = self.dispatch(gateway)

        self.assertEqual(processed, 1)
        self.assertEqual(len(manager.messages), 1)
        self.assertEqual(gateway.calls, [])
        stored = self.read_event(event_id)
        self.assertIsNotNone(stored["websocket_delivered_at"])
        self.assertIsNotNone(stored["push_delivered_at"])

    def test_transient_push_error_keeps_event_for_delayed_retry(self):
        self.add_subscription()
        event_id = self.add_event()
        gateway = FakePushGateway(error=RuntimeError("firebase unavailable"))
        before = datetime.now(UTC)

        processed, manager = self.dispatch(gateway)

        self.assertEqual(processed, 1)
        self.assertEqual(len(manager.messages), 1)
        stored = self.read_event(event_id)
        self.assertIsNotNone(stored["websocket_delivered_at"])
        self.assertIsNone(stored["push_delivered_at"])
        self.assertEqual(stored["attempt_count"], 1)
        self.assertGreaterEqual(stored["next_attempt_at"], before + timedelta(seconds=1))
        self.assertEqual(stored["last_error"], "firebase unavailable")

        second_processed, second_manager = self.dispatch(gateway)
        self.assertEqual(second_processed, 0)
        self.assertEqual(second_manager.messages, [])

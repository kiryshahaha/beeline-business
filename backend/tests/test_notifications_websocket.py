"""WebSocket authentication and recipient isolation."""

import asyncio
import unittest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.security import create_access_token, create_refresh_token
from app.db.session import get_session
from app.main import app
from app.modules.notifications.connections import ConnectionManager
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate
from app.modules.users.service import create_user
from tests.support import DatabaseTestCase


class RecordingWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, payload):
        self.messages.append(payload)


class ConnectionManagerTests(unittest.TestCase):
    def test_publish_reaches_only_connections_of_the_recipient(self):
        manager = ConnectionManager()
        recipient_browser = RecordingWebSocket()
        second_recipient_browser = RecordingWebSocket()
        unrelated_browser = RecordingWebSocket()

        async def scenario():
            await manager.connect(10, recipient_browser)
            await manager.connect(10, second_recipient_browser)
            await manager.connect(20, unrelated_browser)
            return await manager.publish(10, {"kind": "ticket_assigned", "ticket_id": 7})

        delivered = asyncio.run(scenario())

        expected = [{"kind": "ticket_assigned", "ticket_id": 7}]
        self.assertEqual(delivered, 2)
        self.assertEqual(recipient_browser.messages, expected)
        self.assertEqual(second_recipient_browser.messages, expected)
        self.assertEqual(unrelated_browser.messages, [])


class NotificationsWebSocketTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = create_user(
            self.session,
            UserCreate(
                name="Тест",
                surname="Наблюдатель",
                username="websocket_observer",
                password="Password123!",
                role=UserRole.OBSERVER,
            ),
        )
        self.session.commit()

        def override_session():
            yield self.session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))

    def test_access_token_in_first_message_authenticates_and_ping_keeps_connection_alive(self):
        token = create_access_token({"sub": str(self.user.id), "role": self.user.role.value})
        with self.client.websocket_connect("/api/v1/notifications/ws") as websocket:
            websocket.send_json({"type": "authenticate", "token": token})
            self.assertEqual(
                websocket.receive_json(),
                {"type": "authenticated", "user_id": self.user.id},
            )
            websocket.send_json({"type": "ping"})
            self.assertEqual(websocket.receive_json(), {"type": "pong"})

    def test_invalid_or_refresh_token_closes_connection_with_policy_error(self):
        refresh, _expires_at = create_refresh_token({"sub": str(self.user.id)})
        for payload in (
            {"type": "authenticate", "token": "invalid"},
            {"type": "authenticate", "token": refresh},
            {"type": "ping"},
        ):
            with self.subTest(payload_type=payload["type"]):
                with self.client.websocket_connect("/api/v1/notifications/ws") as websocket:
                    websocket.send_json(payload)
                    with self.assertRaises(WebSocketDisconnect) as raised:
                        websocket.receive_json()
                    self.assertEqual(raised.exception.code, 1008)

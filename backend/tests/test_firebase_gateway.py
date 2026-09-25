"""Firebase adapter behavior at the Admin SDK boundary."""

import builtins
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.modules.notifications.firebase import (
    DisabledPushGateway,
    FirebasePushGateway,
    create_push_gateway,
)


class FirebasePushGatewayTests(unittest.TestCase):
    def test_missing_optional_credentials_use_disabled_gateway_without_loading_sdk(self):
        real_import = builtins.__import__

        def import_without_firebase(name, *args, **kwargs):
            if name == "firebase_admin":
                raise AssertionError("Firebase SDK must stay optional when push is disabled")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_firebase):
            gateway = create_push_gateway(SimpleNamespace(firebase_enabled=False))

        self.assertIsInstance(gateway, DisabledPushGateway)
        self.assertFalse(gateway.enabled)

    def test_enabled_gateway_initializes_admin_sdk_with_optional_project_id(self):
        firebase_app = object()
        settings = SimpleNamespace(firebase_enabled=True, firebase_project_id="demo-project")

        with (
            patch("firebase_admin.get_app", side_effect=ValueError("not initialized")),
            patch("firebase_admin.initialize_app", return_value=firebase_app) as initialize,
        ):
            gateway = create_push_gateway(settings)

        initialize.assert_called_once_with(options={"projectId": "demo-project"})
        self.assertIsInstance(gateway, FirebasePushGateway)
        self.assertIs(gateway._app, firebase_app)

    def test_more_than_five_hundred_tokens_are_split_into_supported_batches(self):
        tokens = [f"token-{index}" for index in range(501)]
        messages = []

        def successful_batch(message, *, app):
            self.assertIs(app, firebase_app)
            messages.append(message)
            return SimpleNamespace(
                responses=[
                    SimpleNamespace(success=True, exception=None) for _token in message.tokens
                ]
            )

        firebase_app = object()
        gateway = FirebasePushGateway(firebase_app)
        with (
            patch(
                "firebase_admin.messaging.send_each_for_multicast", side_effect=successful_batch
            ) as send_batch,
        ):
            result = gateway.send(
                tokens,
                title="Новая заявка",
                body="Назначена заявка",
                data={"ticket_id": "7"},
            )

        self.assertEqual([len(call.args[0].tokens) for call in send_batch.call_args_list], [500, 1])
        self.assertEqual(messages[0].tokens, tokens[:500])
        self.assertEqual(messages[0].notification.title, "Новая заявка")
        self.assertEqual(messages[0].notification.body, "Назначена заявка")
        self.assertEqual(messages[0].data, {"ticket_id": "7"})
        self.assertEqual(result.invalid_tokens, set())

    def test_unregistered_tokens_are_reported_for_removal(self):
        from firebase_admin import messaging

        gateway = FirebasePushGateway(object())
        expired = messaging.UnregisteredError("expired")
        response = SimpleNamespace(
            responses=[
                SimpleNamespace(success=False, exception=expired),
                SimpleNamespace(success=True, exception=None),
            ]
        )
        with patch("firebase_admin.messaging.send_each_for_multicast", return_value=response):
            result = gateway.send(["expired-token", "live-token"], title="t", body="b", data={})

        self.assertEqual(result.invalid_tokens, {"expired-token"})

    def test_retryable_sdk_errors_are_returned_to_dispatcher(self):
        gateway = FirebasePushGateway(object())
        response = SimpleNamespace(
            responses=[SimpleNamespace(success=False, exception=RuntimeError("temporary failure"))]
        )
        with patch("firebase_admin.messaging.send_each_for_multicast", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "temporary failure"):
                gateway.send(["token"], title="t", body="b", data={})


if __name__ == "__main__":
    unittest.main()

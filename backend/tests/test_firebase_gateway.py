"""Firebase adapter behavior at the Admin SDK boundary."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.modules.notifications.firebase import FirebasePushGateway


class FirebasePushGatewayTests(unittest.TestCase):
    def test_more_than_five_hundred_tokens_are_split_into_supported_batches(self):
        tokens = [f"token-{index}" for index in range(501)]

        def build_message(**values):
            return SimpleNamespace(**values)

        def successful_batch(message, *, app):
            self.assertIs(app, firebase_app)
            return SimpleNamespace(
                responses=[
                    SimpleNamespace(success=True, exception=None) for _token in message.tokens
                ]
            )

        firebase_app = object()
        gateway = FirebasePushGateway(firebase_app)
        with (
            patch("firebase_admin.messaging.MulticastMessage", side_effect=build_message),
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
        self.assertEqual(result.invalid_tokens, set())


if __name__ == "__main__":
    unittest.main()

"""Tests for finite API and notification types."""

import unittest

from app.main import app
from app.modules.auth.enums import TokenType
from app.modules.auth.schemas import TokenResponse
from app.modules.notifications.enums import NotificationKind


class EnumTypesTests(unittest.TestCase):
    def test_token_response_uses_bearer_token_type_enum(self):
        response = TokenResponse(
            access_token="access",
            refresh_token="refresh",
            expires_in=900,
        )

        self.assertEqual(response.token_type, TokenType.BEARER)
        self.assertIs(TokenResponse.model_fields["token_type"].annotation, TokenType)

    def test_notification_kinds_are_str_enums(self):
        self.assertEqual(NotificationKind.TICKET_ASSIGNED, "ticket_assigned")
        self.assertEqual(NotificationKind.TICKET_STATUS_CHANGED, "ticket_status_changed")

    def test_openapi_exposes_finite_types_as_enums(self):
        schemas = app.openapi()["components"]["schemas"]

        self.assertEqual(schemas["TokenType"]["enum"], ["bearer"])
        self.assertEqual(
            schemas["NotificationKind"]["enum"],
            ["ticket_assigned", "ticket_status_changed"],
        )
        self.assertIn("ApplianceType", schemas)
        self.assertEqual(
            schemas["ApplianceType"]["enum"],
            [
                "CLIENT_ROUTER",
                "RACK_ROUTER",
                "CABLE",
                "FIBER",
                "TOOL",
                "TV_BOX",
                "SPEAKER",
                "IP_CAMERA",
                "OTHER",
            ],
        )

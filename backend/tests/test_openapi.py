"""Tests for OpenAPI schema generation and example restoration."""

import unittest

from app.main import app


class OpenApiTests(unittest.TestCase):
    def test_openapi_schema_contains_all_auth_and_user_endpoints(self):
        schema = app.openapi()
        paths = schema.get("paths", {})

        expected_paths = [
            "/health",
            "/api/v1/tickets",
            "/api/v1/tickets/{id}",
            "/api/v1/tickets/{id}/assignees",
            "/api/v1/tickets/{id}/status",
            "/api/v1/tickets/{id}/comments",
            "/api/v1/notifications",
            "/api/v1/notifications/push-subscriptions",
            "/api/v1/auth/login",
            "/api/v1/auth/refresh",
            "/api/v1/auth/logout",
            "/api/v1/users",
            "/api/v1/users/me",
            "/api/v1/users/{id}",
            "/api/v1/worker/skills",
            "/api/v1/brigades",
            "/api/v1/brigades/{id}",
            "/api/v1/brigades/{id}/members",
            "/api/v1/schedule",
            "/api/v1/work-types",
            "/api/v1/work-types/{id}",
            "/api/v1/analytics/tickets-summary",
            "/api/v1/analytics/brigades-workload",
        ]
        for path in expected_paths:
            self.assertIn(path, paths, f"Path {path} missing in OpenAPI schema")

        user_by_id_ops = paths["/api/v1/users/{id}"]
        self.assertIn("get", user_by_id_ops)
        self.assertIn("patch", user_by_id_ops)
        self.assertIn("delete", user_by_id_ops)

        self.assertIn("post", paths["/api/v1/brigades"])
        self.assertIn("get", paths["/api/v1/brigades"])
        self.assertIn("get", paths["/api/v1/brigades/{id}"])
        self.assertIn("put", paths["/api/v1/brigades/{id}/members"])

        self.assertIn({"BearerAuth": []}, paths["/api/v1/brigades"]["post"]["security"])
        self.assertIn(
            {"BearerAuth": []},
            paths["/api/v1/brigades/{id}/members"]["put"]["security"],
        )

        protected_operations = (
            paths["/api/v1/tickets/{id}/assignees"]["put"],
            paths["/api/v1/tickets/{id}/status"]["patch"],
            paths["/api/v1/tickets/{id}/comments"]["get"],
            paths["/api/v1/tickets/{id}/comments"]["post"],
            paths["/api/v1/notifications"]["get"],
            paths["/api/v1/notifications/push-subscriptions"]["post"],
            paths["/api/v1/notifications/push-subscriptions"]["delete"],
        )
        self.assertTrue(all(operation.get("security") for operation in protected_operations))
        workload_operation = paths["/api/v1/analytics/brigades-workload"]["get"]
        self.assertIn({"BearerAuth": []}, workload_operation["security"])
        self.assertEqual(
            workload_operation["responses"]["200"]["content"]["application/json"]["schema"]["type"],
            "array",
        )

    def test_openapi_exposes_brigade_filter_and_foreman_example(self):
        schema = app.openapi()
        ticket_parameters = schema["paths"]["/api/v1/tickets"]["get"]["parameters"]
        user_parameters = schema["paths"]["/api/v1/users"]["get"]["parameters"]

        self.assertIn("brigade_id", {parameter["name"] for parameter in ticket_parameters})
        self.assertIn("brigade_id", {parameter["name"] for parameter in user_parameters})
        examples = schema["components"]["schemas"]["UserRead"]["examples"]
        self.assertTrue(any(example["role"] == "foreman" for example in examples))

    def test_openapi_uses_http_bearer_for_access_tokens(self):
        schema = app.openapi()
        security_schemes = schema["components"]["securitySchemes"]

        self.assertEqual(
            security_schemes["BearerAuth"],
            {"type": "http", "scheme": "bearer"},
        )
        self.assertIn(
            {"BearerAuth": []},
            schema["paths"]["/api/v1/users"]["get"]["security"],
        )

    def test_openapi_schema_contains_custom_examples(self):
        schema = app.openapi()
        schemas = schema["components"]["schemas"]

        for schema_name in (
            "TicketCreate",
            "TicketRead",
            "UserCreate",
            "UserUpdate",
            "UserRead",
            "WorkerSkillCreate",
            "WorkerSkillRead",
            "LoginRequest",
            "RefreshTokenRequest",
            "TokenResponse",
        ):
            self.assertIn(schema_name, schemas)
            self.assertIn("examples", schemas[schema_name])
            self.assertGreater(len(schemas[schema_name]["examples"]), 0)

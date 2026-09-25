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
            "/api/v1/tickets/{id}/dispatch",
            "/api/v1/tickets/{id}/start-route",
            "/api/v1/tickets/{id}/start",
            "/api/v1/tickets/{id}/complete",
            "/api/v1/tickets/{id}/cancel",
            "/api/v1/tickets/{id}/delay",
            "/api/v1/tickets/{id}/reopen",
            "/api/v1/tickets/{id}/window-change",
            "/api/v1/tickets/{id}/comments",
            "/api/v1/notifications",
            "/api/v1/notifications/push-subscriptions",
            "/api/v1/auth/login",
            "/api/v1/auth/refresh",
            "/api/v1/auth/logout",
            "/api/v1/users",
            "/api/v1/users/me",
            "/api/v1/users/{id}",
            "/api/v1/users/{id}/archive",
            "/api/v1/users/{id}/restore",
            "/api/v1/workers/{worker_id}/line-status",
            "/api/v1/workers/{worker_id}/unavailable",
            "/api/v1/workers/{worker_id}/day-state",
            "/api/v1/worker/skills",
            "/api/v1/brigades",
            "/api/v1/brigades/{id}",
            "/api/v1/brigades/{id}/members",
            "/api/v1/schedule",
            "/api/v1/work-types",
            "/api/v1/work-types/{id}",
            "/api/v1/analytics/tickets-summary",
            "/api/v1/analytics/brigades-workload",
            "/api/v1/analytics/recent-activity",
            "/api/v1/reports/tickets/export",
            "/api/v1/reports/plans/{plan_id}/export",
            "/api/v1/planning/policy",
            "/api/v1/planning/days/{service_area_id}/{route_date}/redirect",
        ]
        for path in expected_paths:
            self.assertIn(path, paths, f"Path {path} missing in OpenAPI schema")

        user_by_id_ops = paths["/api/v1/users/{id}"]
        self.assertIn("get", user_by_id_ops)
        self.assertIn("patch", user_by_id_ops)
        self.assertIn("delete", user_by_id_ops)
        for action in ("archive", "restore"):
            operation = paths[f"/api/v1/users/{{id}}/{action}"]["post"]
            self.assertIn({"BearerAuth": []}, operation["security"])
        self.assertIn("409", user_by_id_ops["delete"]["responses"])
        self.assertIn(
            "include_archived",
            {parameter["name"] for parameter in paths["/api/v1/users"]["get"]["parameters"]},
        )

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
            paths["/api/v1/workers/{worker_id}/line-status"]["put"],
            paths["/api/v1/workers/{worker_id}/unavailable"]["post"],
            paths["/api/v1/workers/{worker_id}/day-state"]["get"],
            paths["/api/v1/tickets/{id}/assignees"]["put"],
            paths["/api/v1/tickets/{id}/status"]["patch"],
            paths["/api/v1/tickets/{id}/comments"]["get"],
            paths["/api/v1/tickets/{id}/comments"]["post"],
            paths["/api/v1/notifications"]["get"],
            paths["/api/v1/notifications/push-subscriptions"]["post"],
            paths["/api/v1/notifications/push-subscriptions"]["delete"],
        )
        self.assertTrue(all(operation.get("security") for operation in protected_operations))
        execution_operations = (
            paths["/api/v1/tickets/{id}/dispatch"]["post"],
            paths["/api/v1/tickets/{id}/start-route"]["post"],
            paths["/api/v1/tickets/{id}/start"]["post"],
            paths["/api/v1/tickets/{id}/complete"]["post"],
            paths["/api/v1/tickets/{id}/cancel"]["post"],
            paths["/api/v1/tickets/{id}/delay"]["post"],
            paths["/api/v1/tickets/{id}/reopen"]["post"],
            paths["/api/v1/tickets/{id}/window-change"]["post"],
            paths["/api/v1/planning/days/{service_area_id}/{route_date}/redirect"]["post"],
        )
        self.assertTrue(all(operation.get("security") for operation in execution_operations))
        activity_operation = paths["/api/v1/analytics/recent-activity"]["get"]
        self.assertIn({"BearerAuth": []}, activity_operation["security"])
        self.assertEqual(
            {parameter["name"] for parameter in activity_operation["parameters"]},
            {"limit", "offset"},
        )
        self.assertIn(
            {"BearerAuth": []},
            paths["/api/v1/reports/tickets/export"]["get"]["security"],
        )
        report_content = paths["/api/v1/reports/tickets/export"]["get"]["responses"]["200"][
            "content"
        ]
        self.assertIn("text/csv", report_content)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", report_content
        )
        plan_report = paths["/api/v1/reports/plans/{plan_id}/export"]["get"]
        self.assertIn({"BearerAuth": []}, plan_report["security"])
        self.assertEqual(
            set(plan_report["responses"]["200"]["content"]),
            {
                "application/zip",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
        )
        self.assertIn("404", plan_report["responses"])
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

    def test_area_filters_replace_district_query_parameters(self):
        schema = app.openapi()
        ticket_parameters = {
            parameter["name"]
            for parameter in schema["paths"]["/api/v1/tickets"]["get"]["parameters"]
        }
        report_parameters = {
            parameter["name"]
            for parameter in schema["paths"]["/api/v1/reports/tickets/export"]["get"]["parameters"]
        }

        self.assertIn("service_area_id", ticket_parameters)
        self.assertNotIn("district_id", ticket_parameters)
        self.assertIn("service_area_id", report_parameters)
        self.assertNotIn("district_id", report_parameters)

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
        ):
            self.assertIn(schema_name, schemas)
            self.assertIn("examples", schemas[schema_name])
            self.assertGreater(len(schemas[schema_name]["examples"]), 0)

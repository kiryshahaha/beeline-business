import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


class HealthTests(unittest.TestCase):
    def test_liveness_returns_ok(self):
        with (
            patch(
                "app.db.session.get_engine", side_effect=RuntimeError("database unavailable")
            ) as get_engine,
            TestClient(app) as client,
        ):
            response = client.get("/health")
        get_engine.assert_not_called()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_readiness_requires_database_migrations_and_planner(self):
        with (
            patch("app.main.check_database_readiness", return_value=(True, True)),
            patch("app.main.check_planner_readiness", new_callable=AsyncMock, return_value=True),
            TestClient(app) as client,
        ):
            response = client.get("/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ready",
                "checks": {"database": "ok", "migrations": "ok", "planner": "ok"},
            },
        )

    def test_readiness_returns_service_unavailable_when_dependency_is_missing(self):
        with (
            patch("app.main.check_database_readiness", return_value=(True, False)),
            patch("app.main.check_planner_readiness", new_callable=AsyncMock, return_value=False),
            TestClient(app) as client,
        ):
            response = client.get("/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "status": "not_ready",
                "checks": {
                    "database": "ok",
                    "migrations": "pending",
                    "planner": "unavailable",
                },
            },
        )

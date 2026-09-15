import unittest
from unittest.mock import patch

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

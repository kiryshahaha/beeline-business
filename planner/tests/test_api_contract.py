"""Exercise the single authenticated API with real OR-Tools."""

import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from fixtures import problem

from app.main import app


class PlannerApiTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, PLANNER_SERVICE_TOKEN="test-internal-token"))
        self.client = self.enterContext(TestClient(app))
        self.headers = {"X-Planner-Token": "test-internal-token"}

    def test_health_and_single_endpoint(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertNotIn("/api/v2/solve", self.client.get("/openapi.json").json()["paths"])

    def test_service_token_is_required(self):
        for headers in ({}, {"X-Planner-Token": "wrong"}):
            self.assertEqual(
                self.client.post("/api/v1/solve", json=problem(), headers=headers).status_code,
                401,
            )

    def test_complete_schedule_and_response_contract(self):
        response = self.client.post("/api/v1/solve", json=problem(), headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertIn(result["status"], ("FEASIBLE", "OPTIMAL"))
        self.assertEqual(result["contract_version"], 2)
        self.assertEqual(result["dropped_nodes"], [])
        self.assertEqual(len(result["routes"][0]["steps"]), 5)

    def test_rejects_incomplete_or_unsafe_problem(self):
        mutations = [
            lambda d: d.update(vehicle_fixed_cost=5000),
            lambda d: d.update(num_vehicles=True),
            lambda d: d.update(contract_version=1),
            lambda d: d.update(policy_version=2),
            lambda d: d.update(allowed_vehicles={}),
            lambda d: d.update(time_capacity=-1),
            lambda d: d.update(service_times=[0]),
            lambda d: d.update(search_time_limit_s=100),
            lambda d: d.update(vehicle_profiles=["unknown"]),
            lambda d: d["matrices"]["drive"]["time_minutes"][1].pop(),
            lambda d: d["matrices"]["drive"]["time_minutes"][1].__setitem__(2, None),
        ]
        for mutate in mutations:
            data = copy.deepcopy(problem())
            mutate(data)
            with self.subTest(data=data):
                self.assertEqual(
                    self.client.post("/api/v1/solve", json=data, headers=self.headers).status_code,
                    422,
                )

    def test_backend_and_planner_share_exact_contract(self):
        root = Path(__file__).resolve().parents[2]
        self.assertEqual(
            (root / "planner/app/modules/solver/schemas.py").read_text(encoding="utf-8"),
            (root / "backend/app/modules/planning/solver_contract.py").read_text(encoding="utf-8"),
        )

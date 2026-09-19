"""Assertions for existing solver behavior; demo scripts remain available separately."""

import unittest

from fastapi.testclient import TestClient

from app.main import app


class PlannerApiTests(unittest.TestCase):
    def setUp(self):
        self.client = self.enterContext(TestClient(app))
        self.payload = {
            "num_vehicles": 1,
            "starts": [0],
            "ends": [0],
            "time_matrix": [[0, 10, 20], [10, 0, 10], [20, 10, 0]],
            "distance_matrix": [[0, 3, 7], [3, 0, 4], [7, 4, 0]],
            "time_windows": [[540, 1080], [540, 1080], [540, 1080]],
            "service_times": [0, 30, 30],
            "penalties": [0, 100000, 100000],
            "vehicle_fixed_cost": 0,
            "search_time_limit_s": 1,
        }

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_complete_plan_has_ordered_arrivals_and_actual_distance(self):
        response = self.client.post("/api/v1/solve", json=self.payload)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["dropped_nodes"], [])
        route = result["routes"][0]
        steps = route["steps"]
        self.assertEqual([step["node"] for step in steps][:: len(steps) - 1], [0, 0])
        self.assertEqual({step["node"] for step in steps[1:-1]}, {1, 2})
        for before, after in zip(steps, steps[1:]):
            travel = self.payload["time_matrix"][before["node"]][after["node"]]
            service = self.payload["service_times"][before["node"]]
            self.assertGreaterEqual(
                after["arrival_time"], before["arrival_time"] + travel + service
            )
        expected = sum(
            self.payload["distance_matrix"][a["node"]][b["node"]]
            for a, b in zip(steps, steps[1:])
        )
        self.assertEqual(route["distance"], expected)
        self.assertEqual(result["total_distance"], expected)

    def test_visit_without_eligible_engineers_is_dropped(self):
        self.payload["allowed_vehicles"] = {"1": []}
        response = self.client.post("/api/v1/solve", json=self.payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(1, response.json()["dropped_nodes"])
        self.assertNotIn(
            1,
            [
                step["node"]
                for route in response.json()["routes"]
                for step in route["steps"]
            ],
        )

    def test_nonsquare_matrix_and_vehicle_count_are_rejected(self):
        self.payload["time_matrix"][0] = [0]
        self.assertEqual(
            self.client.post("/api/v1/solve", json=self.payload).status_code, 422
        )
        self.payload["num_vehicles"] = 0
        self.assertEqual(
            self.client.post("/api/v1/solve", json=self.payload).status_code, 422
        )

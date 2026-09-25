"""Transport profiles, eligibility, null arcs and waiting constraints."""

import copy
import unittest

from fixtures import problem

from app.modules.solver.schemas import SolveRequest
from app.modules.solver.service import solve


class SolverConstraintTests(unittest.TestCase):
    def test_mixed_transport_uses_correct_matrix(self):
        data = problem(n=4, vehicles=2)
        data["vehicle_profiles"] = ["drive", "walk"]
        data["matrices"]["walk"] = copy.deepcopy(data["matrices"]["drive"])
        for i in range(4):
            for j in range(4):
                if i != j:
                    data["matrices"]["walk"]["time_minutes"][i][j] = 20
        data["allowed_vehicles"] = {"2": [0], "3": [1]}
        result = solve(SolveRequest.model_validate(data))
        self.assertEqual(result.dropped_nodes, [])
        self.assertEqual([r.travel_minutes for r in result.routes], [10, 40])

    def test_native_solver_handles_directed_profile_matrices_and_unreachable_arc(self):
        data = problem(n=4, vehicles=2, horizon=100)
        data["vehicle_profiles"] = ["drive", "walk"]
        data["matrices"]["walk"] = copy.deepcopy(data["matrices"]["drive"])
        for source in range(4):
            for target in range(4):
                if source != target:
                    data["matrices"]["drive"]["time_minutes"][source][target] = (
                        4 if target > source else 11
                    )
                    data["matrices"]["walk"]["time_minutes"][source][target] = (
                        6 if target > source else 13
                    )
        data["matrices"]["drive"]["time_minutes"][0][2] = None
        data["matrices"]["drive"]["distance_meters"][0][2] = None
        data["allowed_vehicles"] = {"2": [0, 1], "3": [0, 1]}

        result = solve(SolveRequest.model_validate(data))

        self.assertEqual(result.dropped_nodes, [])
        self.assertTrue(all(route.steps[-1].node == route.steps[0].node for route in result.routes))
        self.assertNotIn(
            (0, 2),
            {
                (route.steps[i].node, route.steps[i + 1].node)
                for route in result.routes
                for i in range(len(route.steps) - 1)
                if route.vehicle_id == 0
            },
        )

    def test_empty_eligibility_and_unreachable_return_drop_jobs(self):
        data = problem(n=4)
        data["allowed_vehicles"]["1"] = []
        for matrix in data["matrices"]["drive"].values():
            for j in range(4):
                if j != 2:
                    matrix[2][j] = None
        result = solve(SolveRequest.model_validate(data))
        self.assertEqual(result.dropped_nodes, [1, 2])

    def test_zero_waiting_can_delay_departure(self):
        data = problem(n=2)
        data["slack_max"] = 0
        data["time_windows"][1] = [50, 50]
        result = solve(SolveRequest.model_validate(data))
        self.assertEqual(result.dropped_nodes, [])
        self.assertEqual(result.routes[0].steps[0].arrival_time, 45)
        self.assertEqual(result.routes[0].waiting_minutes, 0)

    def test_night_shift_extends_beyond_midnight(self):
        data = problem(n=2, horizon=1800)
        data["vehicle_time_windows"] = [[1320, 1800]]
        data["time_windows"][1] = [1500, 1600]
        result = solve(SolveRequest.model_validate(data))
        self.assertEqual(result.dropped_nodes, [])
        self.assertGreaterEqual(result.routes[0].steps[1].arrival_time, 1500)

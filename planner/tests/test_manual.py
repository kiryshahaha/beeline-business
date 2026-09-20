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

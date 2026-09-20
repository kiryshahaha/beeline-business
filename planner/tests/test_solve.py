"""Compare the actual solver with brute-force optima on small problems."""

import itertools
import unittest

from fixtures import problem

from app.modules.solver.schemas import SolveRequest
from app.modules.solver.service import solve


def oracle(data):
    matrix = data["matrices"]["drive"]["time_minutes"]
    tasks = list(range(1, len(matrix)))
    feasible = []
    for size in range(len(tasks) + 1):
        for order in itertools.permutations(tasks, size):
            clock = travel = previous = 0
            for node in (*order, 0):
                clock += data["service_times"][previous] + matrix[previous][node]
                clock = max(clock, data["time_windows"][node][0])
                if clock > data["time_windows"][node][1] or clock > data["time_capacity"]:
                    break
                travel += matrix[previous][node]
                previous = node
            else:
                feasible.append((-size, travel))
    return min(feasible)


class SolverObjectiveTests(unittest.TestCase):
    def test_maximum_jobs_precedes_saving_travel(self):
        data = problem(n=4, horizon=100)
        data["matrices"]["drive"]["time_minutes"] = [
            [0, 1, 10, 12],
            [1, 0, 10, 12],
            [10, 10, 0, 2],
            [12, 12, 2, 0],
        ]
        result = solve(SolveRequest.model_validate(data))
        selected = 3 - len(result.dropped_nodes)
        self.assertEqual((-selected, sum(r.travel_minutes for r in result.routes)), oracle(data))
        self.assertEqual(selected, 3)

    def test_overload_serves_maximum_and_returns_before_shift_end(self):
        data = problem(n=6, horizon=50)
        result = solve(SolveRequest.model_validate(data))
        self.assertEqual(
            (
                -(5 - len(result.dropped_nodes)),
                sum(r.travel_minutes for r in result.routes),
            ),
            oracle(data),
        )
        self.assertLessEqual(result.routes[0].steps[-1].arrival_time, 50)

    def test_service_time_is_not_part_of_travel_cost(self):
        data = problem(n=3)
        data["service_times"] = [0, 30, 40]
        result = solve(SolveRequest.model_validate(data))
        self.assertEqual(result.routes[0].service_minutes, 70)
        self.assertEqual(result.total_cost, 15)

    def test_no_fixed_cost_for_using_two_workers(self):
        data = problem(n=4, vehicles=2, horizon=30)
        data["service_times"] = [0, 0, 20, 20]
        result = solve(SolveRequest.model_validate(data))
        self.assertEqual(result.dropped_nodes, [])
        self.assertEqual(sum(len(r.steps) > 2 for r in result.routes), 2)

    def test_tight_visit_window_and_service(self):
        data = problem(n=3, horizon=60)
        data["time_windows"][1] = [20, 20]
        result = solve(SolveRequest.model_validate(data))
        self.assertEqual(result.dropped_nodes, [])
        self.assertEqual(next(s for s in result.routes[0].steps if s.node == 1).arrival_time, 20)

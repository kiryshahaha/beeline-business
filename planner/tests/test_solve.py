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

    def test_open_end_finish_node_is_not_round_trip(self):
        """F05: with open_end=True starts != ends; finish node != start depot."""
        # n=4: node 0 = depot(start), node 1 = finish, nodes 2-3 = tasks
        data = problem(n=4, vehicles=1, horizon=100)
        # Rearrange: depot=node0, finish=node1 (separate), tasks=2,3
        data["starts"] = [0]
        data["ends"] = [1]
        data["open_end"] = True
        data["time_windows"] = [[0, 100]] * 2 + [[0, 100]] * 2
        data["service_times"] = [0, 0, 10, 10]
        data["penalties"] = [0, 0, 201, 201]
        data["allowed_vehicles"] = {"2": [0], "3": [0]}
        data["ticket_policies"] = data["ticket_policies"][1:]
        result = solve(SolveRequest.model_validate(data))
        self.assertIn(result.status, ("FEASIBLE", "OPTIMAL"))
        self.assertEqual(result.dropped_nodes, [])
        route = result.routes[0]
        # first step must be depot (0), last step must be finish (1)
        self.assertEqual(route.steps[0].node, 0)
        self.assertEqual(route.steps[-1].node, 1)

    def test_received_at_and_sla_deadline_bound_service_start_and_completion(self):
        data = problem(n=2, horizon=100)
        data["time_windows"][1] = [0, 80]
        data["ticket_policies"][0]["received_at"] = 30
        data["ticket_policies"][0]["sla_deadline_at"] = 40
        result = solve(SolveRequest.model_validate(data))
        self.assertEqual(result.dropped_nodes, [])
        self.assertEqual(result.routes[0].steps[1].arrival_time, 30)

        data["ticket_policies"][0]["sla_deadline_at"] = 39
        result = solve(SolveRequest.model_validate(data))
        self.assertEqual(result.dropped_nodes, [1])

    def test_waiting_minutes_matches_gap_between_arrival_and_window_open(self):
        """F10: when a vehicle arrives early the gap is reflected in waiting_minutes."""
        # n=2: depot(0) + single task(1). travel depot→task = 5 min; window opens at 30.
        # Vehicle departs at 0, arrives at 5, waits 25 min, service starts at 30.
        data = problem(n=2, horizon=100)
        data["time_windows"][1] = [30, 50]
        result = solve(SolveRequest.model_validate(data))
        self.assertEqual(result.dropped_nodes, [])
        route = result.routes[0]
        step1 = next(s for s in route.steps if s.node == 1)
        # arrival_time recorded by solver = service_start (max of travel+svc, window_lower)
        self.assertEqual(step1.arrival_time, 30)
        # gap = arrival_time - prev_arrival_time - service[prev] - travel = 30 - 0 - 0 - 5 = 25
        self.assertEqual(route.waiting_minutes, 25)

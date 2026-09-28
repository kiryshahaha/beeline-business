"""Policy objective: exhaustive oracle on small problems, trade-offs and weight bounds."""

import copy
import itertools
import random
import unittest

from fixtures import problem

from app.modules.solver.schemas import (
    OBJECTIVE_COST_LIMIT,
    OBJECTIVE_ORDER,
    OBJECTIVE_RANGE_ERROR,
    SolveRequest,
)
from app.modules.solver.service import solve


def schedule(request, vehicle, order):
    """Earliest start of every visit in this order, or None when the order is infeasible."""
    matrix = request.matrices[request.vehicle_profiles[vehicle]].time_minutes
    policies = dict(zip(request.task_nodes(), request.ticket_policies, strict=True))
    clock, shift_end = request.vehicle_time_windows[vehicle]
    previous, travel, starts = request.starts[vehicle], 0, []
    for node in (*order, request.ends[vehicle]):
        arc = matrix[previous][node]
        if arc is None:
            return None
        clock += request.service_times[previous] + arc
        travel += arc
        if node == request.ends[vehicle]:
            return (travel, starts) if clock <= shift_end else None
        policy = policies[node]
        lower, upper = request.time_windows[node]
        lower = max(lower, policy.received_at)
        if policy.sla_deadline_at is not None:
            upper = min(upper, policy.sla_deadline_at - request.service_times[node])
        clock = max(clock, lower)
        if clock > upper:
            return None
        starts.append(clock)
        previous = node


def oracle(request):
    """Lexicographically smallest objective over every assignment, order and drop."""
    tasks = request.task_nodes()
    policies = dict(zip(tasks, request.ticket_policies, strict=True))
    choices = [[None, *request.allowed_vehicles[str(node)]] for node in tasks]
    best = None
    for assignment in itertools.product(*choices):
        per_vehicle = {v: [n for n, a in zip(tasks, assignment) if a == v] for v in set(assignment)}
        per_vehicle.pop(None, None)
        options = []
        for vehicle, assigned in per_vehicle.items():
            feasible = []
            for order in itertools.permutations(assigned):
                result = schedule(request, vehicle, order)
                if result is not None:
                    response = sum(
                        start - policies[node].received_at
                        for node, start in zip(order, result[1])
                        if policies[node].category == "emergency"
                    )
                    feasible.append((response, result[0]))
            if not feasible:
                break
            options.append(feasible)
        else:
            for combination in itertools.product(*options) if options else [()]:
                dropped = [policies[n].category for n, a in zip(tasks, assignment) if a is None]
                key = (
                    dropped.count("emergency"),
                    sum(response for response, _ in combination),
                    dropped.count("connection"),
                    len(dropped),
                    len(per_vehicle),
                    sum(travel for _, travel in combination),
                    sum(
                        policies[n].previous_vehicle_id not in (None, a)
                        for n, a in zip(tasks, assignment)
                        if a is not None
                    ),
                )
                best = key if best is None or key < best else best
    return best


def key(result):
    return tuple(getattr(result.objective_components, name) for name in OBJECTIVE_ORDER)


def symmetric(data, values):
    """Fill the drive matrix from {(a, b): minutes}; unspecified arcs cost 50."""
    n = len(data["time_windows"])
    matrix = [[0 if i == j else 50 for j in range(n)] for i in range(n)]
    for (a, b), minutes in values.items():
        matrix[a][b] = matrix[b][a] = minutes
    data["matrices"]["drive"] = {
        "time_minutes": matrix,
        "distance_meters": [[v * 100 for v in row] for row in matrix],
    }


def categories(data, *names):
    for policy, name in zip(data["ticket_policies"], names, strict=True):
        policy["category"] = name
        policy["priority"] = {"emergency": 1, "connection": 2}.get(name, 3)


class ObjectiveTradeoffTests(unittest.TestCase):
    def test_emergency_wins_a_conflict_with_ordinary_visits(self):
        # One visit fits the 30-minute shift; the emergency is chosen whatever its position.
        data = problem(n=4, horizon=30)
        categories(data, "connection", "repair", "emergency")
        result = solve(SolveRequest.model_validate(data))
        served = [step.node for step in result.routes[0].steps[1:-1]]
        self.assertEqual(served, [3])
        self.assertEqual(result.objective_components.unassigned_emergencies, 0)
        self.assertEqual(result.objective_components.unassigned_connections, 1)
        self.assertEqual(key(result), oracle(SolveRequest.model_validate(data)))

    def test_connection_wins_over_repair_and_additional(self):
        data = problem(n=4, horizon=30)
        categories(data, "repair", "connection", "additional")
        result = solve(SolveRequest.model_validate(data))
        self.assertEqual([step.node for step in result.routes[0].steps[1:-1]], [2])

    def test_shorter_travel_does_not_postpone_an_emergency(self):
        # Visiting the repair first saves 5 travel minutes but starts the emergency 11 later.
        data = problem(n=3, horizon=100)
        categories(data, "emergency", "repair")
        matrix = [[0, 10, 1], [5, 0, 10], [1, 10, 0]]
        data["matrices"]["drive"] = {
            "time_minutes": matrix,
            "distance_meters": [[v * 100 for v in row] for row in matrix],
        }
        result = solve(SolveRequest.model_validate(data))
        self.assertEqual([step.node for step in result.routes[0].steps[1:-1]], [1, 2])
        self.assertEqual(result.objective_components.emergency_response_minutes, 10)
        self.assertEqual(key(result), oracle(SolveRequest.model_validate(data)))

    def test_emergency_starts_after_receipt_and_as_early_as_possible(self):
        data = problem(n=3, horizon=100)
        categories(data, "emergency", "repair")
        data["ticket_policies"][0]["received_at"] = 37
        result = solve(SolveRequest.model_validate(data))
        start = next(s.arrival_time for s in result.routes[0].steps if s.node == 1)
        self.assertEqual(start, 37)
        self.assertEqual(result.objective_components.emergency_response_minutes, 0)

    def test_earlier_emergency_start_may_displace_several_ordinary_visits(self):
        # Team decision T01: one response minute outweighs any number of ordinary visits.
        data = problem(n=5, horizon=60)
        categories(data, "emergency", "repair", "repair", "repair")
        matrix = [[0 if i == j else 5 for j in range(5)] for i in range(5)]
        for a, b in itertools.permutations((2, 3, 4), 2):
            matrix[a][b] = 0
        data["matrices"]["drive"] = {
            "time_minutes": matrix,
            "distance_meters": [[v * 100 for v in row] for row in matrix],
        }
        data["ticket_policies"][0]["received_at"] = 10
        for node in (2, 3, 4):
            data["time_windows"][node] = [0, 8]
            data["service_times"][node] = 1
        request = SolveRequest.model_validate(data)
        result = solve(request)
        components = result.objective_components
        self.assertEqual(components.emergency_response_minutes, 0)
        self.assertEqual(components.unassigned_total, 3)
        self.assertEqual(key(result), oracle(request))
        # Serving the three repairs first would delay the emergency by three minutes.
        self.assertEqual(schedule(request, 0, (2, 3, 4, 1)), (15, [5, 6, 7, 13]))

    def test_fewer_workers_win_over_shorter_travel(self):
        data = problem(n=4, vehicles=2, horizon=200)
        symmetric(data, {(0, 1): 50, (0, 2): 1, (1, 3): 1, (2, 3): 20, (0, 3): 21, (1, 2): 21})
        request = SolveRequest.model_validate(data)
        result = solve(request)
        self.assertEqual(result.objective_components.active_workers, 1)
        self.assertEqual(result.objective_components.travel_minutes, 42)
        self.assertEqual(key(result), oracle(request))

    def test_empty_routes_are_not_active_workers(self):
        data = problem(n=5, vehicles=3, horizon=200)
        result = solve(SolveRequest.model_validate(data))
        self.assertEqual(len(result.routes), 3)
        self.assertEqual(sum(len(route.steps) > 2 for route in result.routes), 1)
        self.assertEqual(result.objective_components.active_workers, 1)

    def test_extra_ordinary_visit_is_worth_any_travel(self):
        data = problem(n=3, horizon=300)
        categories(data, "repair", "additional")
        symmetric(data, {(0, 1): 1, (0, 2): 90, (1, 2): 90})
        result = solve(SolveRequest.model_validate(data))
        self.assertEqual(result.dropped_nodes, [])
        self.assertEqual(result.objective_components.travel_minutes, 181)

    def test_equal_objective_keeps_previous_assignments(self):
        # Both engineers start at the same place: only the reassignment count differs.
        data = problem(n=4, vehicles=2, horizon=300)
        symmetric(data, {(0, 1): 0})
        for policy in data["ticket_policies"]:
            policy["previous_vehicle_id"] = 1
        request = SolveRequest.model_validate(data)
        result = solve(request)
        used = [route.vehicle_id for route in result.routes if len(route.steps) > 2]
        self.assertEqual(used, [1])
        self.assertEqual(result.objective_components.reassigned_visits, 0)
        self.assertEqual(key(result), oracle(request))

    def test_one_travel_minute_outweighs_every_reassignment(self):
        data = problem(n=4, vehicles=2, horizon=100)
        symmetric(data, {(0, 1): 1, (0, 2): 5, (0, 3): 5, (2, 3): 5, (1, 2): 6, (1, 3): 6})
        for policy in data["ticket_policies"]:
            policy["previous_vehicle_id"] = 1
        request = SolveRequest.model_validate(data)
        result = solve(request)
        self.assertEqual(result.objective_components.reassigned_visits, 2)
        self.assertEqual(key(result), oracle(request))

    def test_total_cost_is_the_weighted_breakdown(self):
        request = SolveRequest.model_validate(problem(n=6, vehicles=2, horizon=60))
        result = solve(request)
        self.assertEqual(result.objective_weights, request.objective_weights())
        self.assertEqual(
            result.total_cost, request.objective_weights().cost(result.objective_components)
        )


class ObjectiveOracleTests(unittest.TestCase):
    def test_random_small_problems_match_exhaustive_policy_optimum(self):
        rng = random.Random(5)
        for case in range(8):
            data = problem(n=6, vehicles=2, horizon=120)
            n = len(data["time_windows"])
            matrix = [[0 if i == j else rng.randint(1, 30) for j in range(n)] for i in range(n)]
            data["matrices"]["drive"] = {
                "time_minutes": matrix,
                "distance_meters": [[v * 100 for v in row] for row in matrix],
            }
            for node, policy in zip(range(2, n), data["ticket_policies"], strict=True):
                policy["category"] = rng.choice(["emergency", "connection", "repair", "additional"])
                policy["received_at"] = rng.choice([-30, 0, 20, 45])
                policy["previous_vehicle_id"] = rng.choice([None, 0, 1])
                start = rng.randint(0, 80)
                data["time_windows"][node] = [start, min(120, start + rng.randint(5, 60))]
                data["service_times"][node] = rng.randint(5, 25)
                data["allowed_vehicles"][str(node)] = rng.choice([[0], [1], [0, 1], [0, 1]])
            request = SolveRequest.model_validate(data)
            with self.subTest(case=case):
                self.assertEqual(key(solve(request)), oracle(request))


class ObjectiveWeightTests(unittest.TestCase):
    def assert_lexicographic(self, request):
        weights, bounds = request.objective_weights(), request.objective_bounds()
        for level, name in enumerate(OBJECTIVE_ORDER):
            below = sum(
                getattr(weights, lower) * bounds[lower] for lower in OBJECTIVE_ORDER[level + 1 :]
            )
            self.assertGreater(getattr(weights, name), below, name)
        self.assertLessEqual(
            sum(getattr(weights, name) * bounds[name] for name in OBJECTIVE_ORDER),
            OBJECTIVE_COST_LIMIT,
        )

    def test_each_weight_exceeds_the_largest_sum_below_it(self):
        data = problem(n=8, vehicles=2, horizon=480)
        categories(data, "emergency", "emergency", "connection", "repair", "additional", "repair")
        data["ticket_policies"][0]["received_at"] = -120
        data["ticket_policies"][1]["sla_deadline_at"] = 300
        data["ticket_policies"][2]["previous_vehicle_id"] = 1
        request = SolveRequest.model_validate(data)
        bounds = request.objective_bounds()
        self.assertEqual(bounds["emergency_response_minutes"], (480 + 120) + (300 - 10))
        self.assertEqual(bounds["travel_minutes"], 2 * 480)
        self.assertEqual(bounds["reassigned_visits"], 1)
        self.assertEqual(request.objective_weights().reassigned_visits, 1)
        self.assertEqual(request.objective_weights().travel_minutes, 2)
        self.assert_lexicographic(request)

    def test_largest_backend_problem_with_day_shifts_fits_the_cost_range(self):
        # 100 visits, 20 engineers with 12-hour shifts, every visit previously planned.
        data = problem(n=120, vehicles=20, horizon=1440)
        data["vehicle_time_windows"] = [[480, 1200]] * 20
        data["matrices"]["drive"]["time_minutes"] = [
            [0 if i == j else 1 for j in range(120)] for i in range(120)
        ]
        data["matrices"]["drive"]["distance_meters"] = copy.deepcopy(
            data["matrices"]["drive"]["time_minutes"]
        )
        names = ["emergency"] * 10 + ["connection"] * 40 + ["repair"] * 50
        for vehicle, (policy, name) in enumerate(zip(data["ticket_policies"], names)):
            policy["category"] = name
            policy["received_at"] = -1440 if name == "emergency" else 0
            policy["previous_vehicle_id"] = vehicle % 20
        self.assert_lexicographic(SolveRequest.model_validate(data))

    def test_overflowing_weights_are_rejected_instead_of_wrapping(self):
        data = problem(n=80, vehicles=20, horizon=2880)
        data["matrices"]["drive"]["time_minutes"] = [
            [0 if i == j else 1 for j in range(80)] for i in range(80)
        ]
        data["matrices"]["drive"]["distance_meters"] = copy.deepcopy(
            data["matrices"]["drive"]["time_minutes"]
        )
        for policy in data["ticket_policies"]:
            policy["category"] = "emergency"
            policy["received_at"] = -2_000_000_000
        with self.assertRaisesRegex(ValueError, OBJECTIVE_RANGE_ERROR):
            SolveRequest.model_validate(data)


if __name__ == "__main__":
    unittest.main()

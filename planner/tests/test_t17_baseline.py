import unittest

from fixtures import problem

from app.modules.solver.baseline import solve_baseline
from app.modules.solver.metrics import calculate_metrics
from app.modules.solver.schemas import SolveRequest
from app.modules.solver.service import solve


class BaselineAndMetricsTests(unittest.TestCase):
    def test_a11_single_worker_suffices(self):
        # A11: "Все заявки выполнимы одним worker" -> При равном покрытии выбирается один
        data = problem(n=4, vehicles=2, horizon=100)

        # 2 vehicles, 2 tasks.
        # Depot for v0 is 0, v1 is 1. Tasks are 2, 3.
        # Setup matrix so v0 can do both with travel 10+10 = 20.
        # v0 doing both: 0 -> 2 (10) -> 3 (10) -> 0 (10) = 30 travel
        # v0 doing 2, v1 doing 3:
        # v0: 0 -> 2 (10) -> 0 (10) = 20
        # v1: 1 -> 3 (10) -> 1 (10) = 20 (Total 40, worse travel, 2 vehicles)
        # 2 vehicles give LESS travel, but 1 is chosen because W_VEHICLE is large.

        # Matrix:
        # v0 doing both: 0 -> 2 (10) -> 3 (10) -> 0 (10) = 30 total
        # v0 doing 2, v1 doing 3:
        # v0: 0 -> 2 (10) -> 0 (10) = 20
        # v1: 1 -> 3 (2) -> 1 (2) = 4
        # Total travel = 24.

        matrix = [[0] * 4 for _ in range(4)]
        matrix[0][2] = 10
        matrix[2][0] = 10
        matrix[2][3] = 10
        matrix[3][2] = 10
        matrix[3][0] = 10
        matrix[0][3] = 10

        matrix[1][2] = 5
        matrix[2][1] = 5
        matrix[1][3] = 2
        matrix[3][1] = 2

        data["matrices"]["drive"]["time_minutes"] = matrix
        data["matrices"]["drive"]["distance_meters"] = matrix
        data["allowed_vehicles"]["2"] = [0, 1]
        data["allowed_vehicles"]["3"] = [0, 1]

        req = SolveRequest.model_validate(data)

        res_solver = solve(req)
        res_baseline = solve_baseline(req)

        # Solver should use 1 vehicle because W_VEHICLE (100_000) > saving travel (30 - 24 = 6)
        metrics_s = calculate_metrics(req, res_solver)
        self.assertEqual(metrics_s["active_vehicles"], 1)
        self.assertEqual(sum(metrics_s["assigned_tasks"].values()), 2)

        # Baseline assigns to first eligible, let's see what it does.
        # Sort order: 2, 3.
        # task 2: vehicle 0 is eligible, it takes it.
        # task 3: vehicle 0 is eligible, it takes it.
        # So baseline also uses 1 vehicle!
        metrics_b = calculate_metrics(req, res_baseline)
        self.assertEqual(metrics_b["active_vehicles"], 1)

    def test_a12_tradeoff_active_vehicles(self):
        # A12: "Те же условия, но добавляются обязательные соединения или срочные: нужно 2 воркера"
        # Make SLA very tight so 1 worker cannot do both in time.
        data = problem(n=4, vehicles=2, horizon=100)
        matrix = [[10] * 4 for _ in range(4)]
        for i in range(4):
            matrix[i][i] = 0
        data["matrices"]["drive"]["time_minutes"] = matrix
        data["matrices"]["drive"]["distance_meters"] = matrix
        data["allowed_vehicles"]["2"] = [0, 1]
        data["allowed_vehicles"]["3"] = [0, 1]

        # tasks are 2, 3.
        data["ticket_policies"][0]["sla_deadline_at"] = 25  # task 2
        data["ticket_policies"][1]["sla_deadline_at"] = 25  # task 3
        # travel to 2 is 10, service 10 = 20.
        # travel from 2 to 3 is 10, service 10 = 40 > 25 (fails SLA)

        req = SolveRequest.model_validate(data)
        res_solver = solve(req)

        # Solver should use 2 vehicles.
        metrics_s = calculate_metrics(req, res_solver)
        self.assertEqual(metrics_s["active_vehicles"], 2)
        self.assertEqual(metrics_s["unassigned_tasks"], {})

    def test_a24_greedy_trap(self):
        # A24: Greedy-trap case.
        # Baseline gets stuck on first eligible, preventing global optimal assignment.
        data = problem(n=4, vehicles=2, horizon=100)
        # Vehicles 0, 1. Tasks 2, 3.
        # Vehicle 0 can do ONLY 2.
        # Vehicle 1 can do 2 and 3.
        # Task 2 arrives at 0. Task 3 arrives at 10.
        # Baseline sorts by received_at, so it tries Task 2 first.
        # Baseline tries vehicle 0, but what if vehicle 0 is busy or something?
        # Let's say baseline checks vehicles in order (0 then 1).
        # Actually, let's make Task 2 allowed for 0 and 1. Task 3 allowed ONLY for 1.
        data["allowed_vehicles"]["2"] = [0, 1]
        data["allowed_vehicles"]["3"] = [1]

        data["ticket_policies"][0]["received_at"] = 0  # Task 2
        data["ticket_policies"][1]["received_at"] = 0  # Task 3
        data["ticket_policies"][0]["ticket_id"] = 100
        data["ticket_policies"][1]["ticket_id"] = 101

        # Baseline sorts 2 then 3.
        # For task 2, baseline checks vehicle 0 first. Assings it to 0.
        # For task 3, baseline checks vehicle 1. Assigns it to 1.
        # Wait, that works perfectly.

        # To make a trap, let's say Task 2 is very far for Vehicle 0 but very close for Vehicle 1.
        # If Vehicle 1 takes Task 2, it won't have time for Task 3.
        # Vehicle 0 can ONLY do Task 2, and has just enough time.
        # If baseline checks vehicles in order: it will try v0 for task 2.
        # Let's say Task 2 allowed for [1, 0] so it checks v1 first!
        # In baseline we do `for v in range(data.num_vehicles)`. So it checks v0, then v1.
        # To trap baseline:
        # Task 2: v0 and v1 can do it.
        # Task 3: ONLY v0 can do it.
        data["allowed_vehicles"]["2"] = [0, 1]
        data["allowed_vehicles"]["3"] = [0]

        # Task 2 is evaluated first (ticket 100).
        # Baseline evaluates v0 for Task 2. It fits! So v0 takes Task 2.
        # Now Task 3 (ticket 101). Evaluates v0.
        # But v0 doesn't have time for both!
        # Result: Task 3 is dropped by baseline.

        matrix = [[10] * 4 for _ in range(4)]
        for i in range(4):
            matrix[i][i] = 0
        data["matrices"]["drive"]["time_minutes"] = matrix
        data["matrices"]["drive"]["distance_meters"] = matrix

        data["time_windows"][2] = [0, 20]  # tight window
        data["time_windows"][3] = [0, 20]  # tight window
        # v0 takes Task 2: arrives at 10, service 10, ends at 20.
        # v0 then tries Task 3: starts at 20 + travel 10 = 30 > 20 window. Fails.
        # So baseline drops Task 3.

        req = SolveRequest.model_validate(data)
        res_baseline = solve_baseline(req)
        metrics_b = calculate_metrics(req, res_baseline)
        self.assertEqual(sum(metrics_b["unassigned_tasks"].values()), 1)

        # Solver will see that v0 MUST do Task 3, so it gives Task 2 to v1.
        res_solver = solve(req)
        metrics_s = calculate_metrics(req, res_solver)
        self.assertEqual(sum(metrics_s["unassigned_tasks"].values()), 0)
        self.assertEqual(metrics_s["active_vehicles"], 2)

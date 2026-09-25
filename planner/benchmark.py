import json
import random
import time

from app.modules.solver.baseline import solve_baseline
from app.modules.solver.metrics import calculate_metrics
from app.modules.solver.schemas import SolveRequest, TicketPolicy
from app.modules.solver.service import solve


def generate_synthetic_problem(
    seed: int, n_tasks: int, n_vehicles: int, time_limit_s: int = 5
) -> dict:
    random.seed(seed)
    n = n_tasks + n_vehicles
    horizon = 1000

    matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                matrix[i][j] = random.randint(10, 50)

    time_windows = []
    service_times = []
    ticket_policies = []
    allowed_vehicles = {}

    # Depots
    for i in range(n_vehicles):
        time_windows.append([0, horizon])
        service_times.append(0)

    # Tasks
    for i in range(n_vehicles, n):
        w_start = random.randint(0, horizon - 100)
        w_end = w_start + random.randint(50, 200)
        time_windows.append([w_start, w_end])
        service_times.append(random.randint(20, 60))

        is_emerg = random.random() < 0.2
        cat = "emergency" if is_emerg else "repair"
        priority = 1 if is_emerg else 3
        received_at = random.randint(0, w_start)
        sla = received_at + 120 if is_emerg else None

        ticket_policies.append(
            TicketPolicy(
                ticket_id=1000 + i,
                category=cat,
                priority=priority,
                received_at=received_at,
                sla_deadline_at=sla,
                previous_vehicle_id=None,
            ).model_dump()
        )

        # Allow all vehicles
        allowed_vehicles[str(i)] = list(range(n_vehicles))

    return {
        "contract_version": 2,
        "policy_version": 1,
        "num_vehicles": n_vehicles,
        "starts": list(range(n_vehicles)),
        "ends": list(range(n_vehicles)),
        "vehicle_profiles": ["drive"] * n_vehicles,
        "vehicle_time_windows": [[0, horizon]] * n_vehicles,
        "matrices": {
            "drive": {
                "time_minutes": matrix,
                "distance_meters": [[v * 10 for v in row] for row in matrix],
            }
        },
        "time_windows": time_windows,
        "service_times": service_times,
        "allowed_vehicles": allowed_vehicles,
        "ticket_policies": ticket_policies,
        "time_capacity": horizon,
        "slack_max": 120,
        "vehicle_fixed_cost": 0,
        "search_time_limit_s": time_limit_s,
        "open_end": False,
    }


def run_benchmark():
    seed = 42
    print(f"Generating synthetic dataset with seed {seed}")
    data = generate_synthetic_problem(seed=seed, n_tasks=20, n_vehicles=3, time_limit_s=2)
    req = SolveRequest.model_validate(data)

    print("\n--- Running Baseline ---")
    start = time.time()
    res_baseline = solve_baseline(req)
    t_baseline = time.time() - start
    metrics_baseline = calculate_metrics(req, res_baseline)
    print(f"Runtime: {t_baseline:.3f}s")
    print(f"Status: {res_baseline.status}")
    print(f"Total Cost: {res_baseline.total_cost}")
    print("Metrics:", json.dumps(metrics_baseline, indent=2))

    print("\n--- Running OR-Tools Solver ---")
    start = time.time()
    res_solver = solve(req)
    t_solver = time.time() - start
    metrics_solver = calculate_metrics(req, res_solver)
    print(f"Runtime: {t_solver:.3f}s")
    print(f"Status: {res_solver.status}")
    print(f"Total Cost: {res_solver.total_cost}")
    print("Metrics:", json.dumps(metrics_solver, indent=2))

    # Save comparison to file
    with open("benchmark_report.json", "w") as f:
        json.dump(
            {
                "seed": seed,
                "tasks": 20,
                "vehicles": 3,
                "search_time_limit_s": 2,
                "baseline": {
                    "runtime_s": t_baseline,
                    "status": res_baseline.status,
                    "total_cost": res_baseline.total_cost,
                    "metrics": metrics_baseline,
                    "objective_components": res_baseline.objective_components.model_dump(),
                },
                "solver": {
                    "runtime_s": t_solver,
                    "status": res_solver.status,
                    "total_cost": res_solver.total_cost,
                    "metrics": metrics_solver,
                    "objective_components": res_solver.objective_components.model_dump()
                    if res_solver.objective_components
                    else None,
                },
            },
            f,
            indent=2,
        )
    print("\nReport saved to benchmark_report.json")


if __name__ == "__main__":
    run_benchmark()

"""Run native solver smoke scenarios and compare the solver with a greedy baseline."""

import argparse
import json
import random
import subprocess
import sys
import time
from pathlib import Path

from ortools import __version__ as ortools_version

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
from fixtures import problem  # noqa: E402

from app.modules.solver.baseline import solve_baseline  # noqa: E402
from app.modules.solver.metrics import calculate_metrics  # noqa: E402
from app.modules.solver.schemas import SolveRequest  # noqa: E402
from app.modules.solver.service import solve  # noqa: E402


def generate_synthetic_problem(
    seed: int, n_tasks: int, n_vehicles: int, time_limit_s: int = 2
) -> dict:
    rng = random.Random(seed)
    node_count = n_tasks + n_vehicles
    horizon = 1000

    matrix = [[0] * node_count for _ in range(node_count)]
    for source in range(node_count):
        for target in range(node_count):
            if source != target:
                matrix[source][target] = rng.randint(10, 50)

    time_windows = [[0, horizon] for _ in range(n_vehicles)]
    service_times = [0 for _ in range(n_vehicles)]
    ticket_policies = []
    allowed_vehicles = {}

    for node in range(n_vehicles, node_count):
        window_start = rng.randint(0, horizon - 200)
        window_end = min(horizon, window_start + rng.randint(50, 200))
        time_windows.append([window_start, window_end])
        service_times.append(rng.randint(20, 60))

        emergency = rng.random() < 0.2
        received_at = rng.randint(0, window_start)
        ticket_policies.append(
            {
                "ticket_id": 1000 + node,
                "category": "emergency" if emergency else "repair",
                "priority": 1 if emergency else 3,
                "received_at": received_at,
                "sla_deadline_at": received_at + 120 if emergency else None,
                "previous_vehicle_id": None,
            }
        )
        allowed_vehicles[str(node)] = list(range(n_vehicles))

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
                "distance_meters": [[value * 10 for value in row] for row in matrix],
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


def _result_summary(request: SolveRequest, result, elapsed_ms: float) -> dict:
    return {
        "status": result.status,
        "total_cost": result.total_cost,
        "objective_components": (
            result.objective_components.model_dump() if result.objective_components else None
        ),
        "metrics": calculate_metrics(request, result),
        "elapsed_ms": round(elapsed_ms, 2),
    }


def _run_baseline_comparison() -> dict:
    seed = 42
    request = SolveRequest.model_validate(
        generate_synthetic_problem(seed=seed, n_tasks=20, n_vehicles=3, time_limit_s=2)
    )

    started = time.perf_counter()
    baseline_result = solve_baseline(request)
    baseline = _result_summary(request, baseline_result, (time.perf_counter() - started) * 1000)

    started = time.perf_counter()
    solver_result = solve(request)
    solver = _result_summary(request, solver_result, (time.perf_counter() - started) * 1000)

    return {
        "seed": seed,
        "tasks": 20,
        "vehicles": 3,
        "search_time_limit_s": 2,
        "baseline": baseline,
        "native_solver": solver,
    }


def _run_native_smoke_scenarios() -> list[dict]:
    scenarios = []
    for tickets in (8, 16):
        request = SolveRequest.model_validate(problem(n=tickets + 2, vehicles=2, horizon=480))
        request_data = request.model_dump()
        request_data["search_time_limit_s"] = 1
        request = SolveRequest.model_validate(request_data)

        started = time.perf_counter()
        result = solve(request)
        scenarios.append(
            {
                "tickets": tickets,
                "vehicles": 2,
                "status": result.status,
                "assigned": tickets - len(result.dropped_nodes),
                "dropped": len(result.dropped_nodes),
                "objective": result.total_cost,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        )
    return scenarios


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    commit_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True
    ).stdout.strip()
    report = {
        "commit_sha": commit_sha,
        "python": sys.version.split()[0],
        "ortools": ortools_version,
        "scenarios": _run_native_smoke_scenarios(),
        "baseline_comparison": _run_baseline_comparison(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Native solver benchmark summary written to {args.output}")


if __name__ == "__main__":
    main()

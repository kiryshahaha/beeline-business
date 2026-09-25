"""Run repeatable native OR-Tools smoke benchmarks and write a safe JSON summary."""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from ortools import __version__ as ortools_version

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
from fixtures import problem  # noqa: E402

from app.modules.solver.schemas import SolveRequest  # noqa: E402
from app.modules.solver.service import solve  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    commit_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True
    ).stdout.strip()
    scenarios = []
    for tickets in (8, 16):
        data = problem(n=tickets + 2, vehicles=2, horizon=480)
        data["search_time_limit_s"] = 1
        started = time.perf_counter()
        result = solve(SolveRequest.model_validate(data))
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
    report = {
        "commit_sha": commit_sha,
        "python": sys.version.split()[0],
        "ortools": ortools_version,
        "scenarios": scenarios,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Native solver benchmark summary written to {args.output}")


if __name__ == "__main__":
    main()

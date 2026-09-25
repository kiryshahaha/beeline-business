"""Run real backend, PostgreSQL and OR-Tools HTTP processes with a fixture road provider."""

import argparse
import os
import shlex
import socket
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path

import httpx
from sqlalchemy import create_engine

from planning_scenarios import ROUTE_DATE
from seed_demo import run_seed
from seed_synthetic import validate_database_url
from testing.database import migrated_schema

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--planner-python", default=sys.executable)
    parser.add_argument("--bruno-command", default="npx --yes @usebruno/cli@4.1.0")
    parser.add_argument("--report-dir", type=Path, default=ROOT / ".local/planning-e2e")
    args = parser.parse_args()
    args.report_dir = args.report_dir.resolve()
    url = validate_database_url(os.environ["TEST_DATABASE_URL"])
    engine = create_engine(url)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    ports = {key: free_port() for key in ("backend", "planner", "provider")}
    with ExitStack() as stack:
        stack.callback(engine.dispose)
        isolated, _ = stack.enter_context(migrated_schema(engine))
        with isolated.connect() as connection:
            schema = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
        run_seed(isolated, ROUTE_DATE)
        env = {
            **os.environ,
            "APP_ENV": "test",
            "PYTHONUTF8": "1",
            "DATABASE_URL": url.update_query_dict(
                {"options": f"-csearch_path={schema}"}
            ).render_as_string(hide_password=False),
            "JWT_SECRET_KEY": "temporary-e2e-secret-at-least-thirty-two-characters",
            "NOTIFICATION_DISPATCHER_ENABLED": "false",
            "FIREBASE_ENABLED": "false",
            "PLANNING_ENABLED": "true",
            "PLANNER_SERVICE_TOKEN": "temporary-e2e-internal-token",
            "PLANNING_SOLVE_TIME_LIMIT_SECONDS": "1",
            "PLANNER_BASE_URL": f"http://127.0.0.1:{ports['planner']}",
            "TEST_GEOAPIFY_URL": f"http://127.0.0.1:{ports['provider']}/v1",
        }
        for key, cwd, module, python in (
            ("planner", ROOT / "planner", "app.main:app", args.planner_python),
            ("provider", ROOT / "backend", "testing.geoapify_app:app", sys.executable),
            ("backend", ROOT / "backend", "testing.backend_app:app", sys.executable),
        ):
            log = stack.enter_context((args.report_dir / f"{key}.log").open("w", encoding="utf-8"))
            process = subprocess.Popen(
                [python, "-m", "uvicorn", module, "--host", "127.0.0.1", "--port", str(ports[key])],
                cwd=cwd,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            stack.callback(stop, process)
            deadline = time.monotonic() + 30
            health_path = "/ready" if key == "backend" else "/health"
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"{key} exited; see {args.report_dir / (key + '.log')}")
                try:
                    if (
                        httpx.get(
                            f"http://127.0.0.1:{ports[key]}{health_path}", timeout=1
                        ).status_code
                        == 200
                    ):
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError(f"{key} did not become ready")
        command = shlex.split(args.bruno_command, posix=os.name != "nt")
        command = [
            arg[1:-1] if len(arg) > 1 and arg[0] == arg[-1] == '"' else arg for arg in command
        ]
        if os.name == "nt" and command[0] == "npx":
            command[0] = "npx.cmd"
        subprocess.run(
            [
                *command,
                "run",
                "-r",
                "--env",
                "Local",
                "--env-var",
                f"base_url=http://127.0.0.1:{ports['backend']}",
                "--reporter-skip-all-headers",
                "--reporter-skip-request-body",
                "--reporter-skip-response-body",
                "--reporter-junit",
                str(args.report_dir / "bruno.xml"),
            ],
            cwd=ROOT / "backend/bruno",
            env=env,
            check=True,
        )
    print(f"E2E passed; reports: {args.report_dir}")


if __name__ == "__main__":
    main()

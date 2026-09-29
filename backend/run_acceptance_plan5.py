"""Run the Plan 5 synthetic package through backend, PostgreSQL and native planner."""

import argparse
import json
import os
import subprocess
import sys
import time
from contextlib import ExitStack
from datetime import datetime, timedelta
from datetime import time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.modules.data_exchange.formats import parse_file
from app.modules.data_exchange.service import import_data
from run_planning_e2e import free_port, stop
from seed_synthetic import validate_database_url
from testing.database import migrated_schema

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "AcceptanceOnly123!"
MOSCOW = ZoneInfo("Europe/Moscow")


def _start(name, cwd, module, port, env, report_dir, stack):
    log = stack.enter_context((report_dir / f"{name}.log").open("w", encoding="utf-8"))
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", module, "--host", "127.0.0.1", "--port", str(port)],
        cwd=cwd,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    stack.callback(stop, process)
    health = "/ready" if name == "backend" else "/health"
    for _ in range(150):
        if process.poll() is not None:
            raise RuntimeError(f"{name} exited; see {report_dir / (name + '.log')}")
        try:
            if httpx.get(f"http://127.0.0.1:{port}{health}", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"{name} did not become ready")


def _request(client, method, path, expected, **kwargs):
    response = client.request(method, path, **kwargs)
    body = response.json()
    if response.status_code != expected:
        raise AssertionError(f"{method} {path}: {response.status_code} {body}")
    return body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "backend/.local/acceptance-plan5")
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    database_url = validate_database_url(os.environ["TEST_DATABASE_URL"])
    engine = create_engine(database_url)
    package = ROOT / "data/synthetic/acceptance/dataset.zip"
    tables = parse_file(package.read_bytes(), package.name)
    scenarios = json.loads(
        (ROOT / "data/synthetic/acceptance/scenarios.json").read_text(encoding="utf-8")
    )
    report = {"package": str(package.relative_to(ROOT)), "steps": []}
    with ExitStack() as stack:
        stack.callback(engine.dispose)
        isolated, _ = stack.enter_context(migrated_schema(engine))
        with isolated.connect() as connection:
            schema = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
        with Session(isolated) as session:
            receipt = import_data(session, tables)
        report["import"] = {"counts": receipt["counts"], "duplicate": receipt["duplicate"]}
        ids = receipt["id_map"]
        with isolated.begin() as connection:
            connection.execute(
                text("UPDATE users SET password_hash=:password WHERE id=:id"),
                {"password": hash_password(PASSWORD), "id": ids["users"]["1"]},
            )
        ports = {name: free_port() for name in ("planner", "provider", "backend")}
        env = {
            **os.environ,
            "APP_ENV": "test",
            "DATABASE_URL": database_url.update_query_dict(
                {"options": f"-csearch_path={schema}"}
            ).render_as_string(hide_password=False),
            "JWT_SECRET_KEY": "temporary-plan5-key-at-least-thirty-two-characters",
            "NOTIFICATION_DISPATCHER_ENABLED": "false",
            "FIREBASE_ENABLED": "false",
            "PLANNING_ENABLED": "true",
            "PLANNER_SERVICE_TOKEN": "temporary-plan5-internal-token",
            "PLANNING_SOLVE_TIME_LIMIT_SECONDS": "1",
            "PLANNER_BASE_URL": f"http://127.0.0.1:{ports['planner']}",
            "TEST_GEOAPIFY_URL": f"http://127.0.0.1:{ports['provider']}/v1",
        }
        for name, cwd, module in (
            ("planner", ROOT / "planner", "app.main:app"),
            ("provider", ROOT / "backend", "testing.geoapify_app:app"),
            ("backend", ROOT / "backend", "testing.acceptance_backend_app:app"),
        ):
            _start(name, cwd, module, ports[name], env, args.report_dir, stack)
        base = f"http://127.0.0.1:{ports['backend']}"
        with httpx.Client(base_url=base, timeout=45) as client:
            login = _request(
                client,
                "POST",
                "/api/v1/auth/login",
                200,
                json={"username": "synthetic_5025_observer_1", "password": PASSWORD},
            )
            client.headers.update({"Authorization": f"Bearer {login['access_token']}"})
            areas = {source: ids["service_areas"][str(source)] for source in (101, 102, 103)}
            initial = {}
            for source, area_id in areas.items():
                current = _request(
                    client, "GET", f"/api/v1/planning/areas/{area_id}/2030-01-15/current", 200
                )
                initial[source] = current
                report["steps"].append(
                    {
                        "id": f"initial_{source}",
                        "revision": current["revision"],
                        "visits": len(current["visits"]),
                        "roster": len(current["roster"]),
                    }
                )
            route_day = datetime.fromisoformat(f"{scenarios['route_date']}T00:00:00+03:00").date()
            for source, current in initial.items():
                shifts = {}
                lengths = []
                for member in current["roster"]:
                    start = datetime.combine(
                        route_day, clock_time.fromisoformat(member["workshift_start"]), MOSCOW
                    )
                    end = datetime.combine(
                        route_day, clock_time.fromisoformat(member["workshift_end"]), MOSCOW
                    )
                    if end <= start:
                        end += timedelta(days=1)
                    shifts[member["worker_id"]] = (start, end)
                    lengths.append(int((end - start).total_seconds() // 60))
                if sorted(lengths) != [480, 480, 720, 720]:
                    raise AssertionError(f"Area {source} has unexpected shift profiles: {lengths}")
                for visit in current["visits"]:
                    shift = shifts.get(visit["worker_id"])
                    start = datetime.fromisoformat(visit["service_start_at"])
                    end = datetime.fromisoformat(visit["service_end_at"])
                    if (
                        shift is None
                        or start.date() != route_day
                        or start < shift[0]
                        or end > shift[1]
                    ):
                        raise AssertionError(
                            f"Area {source} visit {visit['ticket_id']} exceeds its day shift"
                        )
                report["steps"].append(
                    {
                        "id": f"S02_daily_shifts_{source}",
                        "shift_minutes": sorted(lengths),
                        "visits_inside_shift": len(current["visits"]),
                    }
                )
            territory = scenarios["territory_cases"]
            nearby_ticket_id = ids["tickets"][str(territory["nearby_cross_area_ticket_id"])]
            nearby_worker_id = ids["users"][str(territory["nearby_worker_id"])]
            cross_area = _request(
                client,
                "POST",
                "/api/v1/planning/preview",
                422,
                json={
                    "route_date": scenarios["route_date"],
                    "service_area_id": areas[101],
                    "base_day_revision": 1,
                    "ticket_ids": [nearby_ticket_id],
                    "worker_ids": [nearby_worker_id],
                    "allow_partial": True,
                },
            )
            if (
                cross_area["detail"]["code"] != "worker_service_area_mismatch"
                or nearby_worker_id not in cross_area["detail"]["worker_ids"]
            ):
                raise AssertionError(f"Nearby cross-area worker was not refused: {cross_area}")
            after_cross_area = _request(
                client,
                "GET",
                f"/api/v1/planning/areas/{areas[101]}/{scenarios['route_date']}/current",
                200,
            )
            if after_cross_area != initial[101]:
                raise AssertionError("Cross-area preview changed the published day")
            report["steps"].append(
                {
                    "id": "S03_nearby_cross_area_rejected",
                    "worker_id": nearby_worker_id,
                    "reason": cross_area["detail"]["code"],
                }
            )
            remote_ticket_id = ids["tickets"][str(territory["same_area_remote_ticket_id"])]
            remote = _request(
                client,
                "POST",
                f"/api/v1/planning/areas/{areas[102]}/{scenarios['route_date']}/tickets/{remote_ticket_id}/preview",
                201,
                json={"base_day_revision": 1},
            )
            remote_event = remote["event"]
            remote_case = next(
                case
                for case in scenarios["tickets"]
                if case["ticket_id"] == territory["same_area_remote_ticket_id"]
            )
            remote_slot = remote_event["selected_slot"]
            if (
                remote_event["outcome"] != "insertion_ready"
                or remote_slot is None
                or not remote["plan"]
            ):
                raise AssertionError(f"Same-area remote ticket was not insertable: {remote_event}")
            if datetime.fromisoformat(remote_slot["service_start_at"]) < datetime.fromisoformat(
                remote_case["visit_window_start"]
            ) or datetime.fromisoformat(remote_slot["service_end_at"]) > datetime.fromisoformat(
                remote_case["visit_window_end"]
            ):
                raise AssertionError("Same-area remote ticket exceeds its customer window")
            report["steps"].append(
                {
                    "id": "S03_same_area_remote_city",
                    "outcome": remote_event["outcome"],
                    "worker_id": remote_slot["worker_id"],
                }
            )
            regular_id = ids["tickets"]["37"]
            regular = _request(
                client,
                "POST",
                f"/api/v1/planning/areas/{areas[101]}/2030-01-15/tickets/{regular_id}/preview",
                201,
                json={"base_day_revision": 1},
            )
            report["steps"].append(
                {
                    "id": "regular_preview",
                    "event": regular["event"],
                    "plan_id": regular["plan"]["plan_id"] if regular["plan"] else None,
                }
            )
            if regular["event"]["outcome"] != "insertion_ready" or regular["plan"] is None:
                raise AssertionError(f"Regular insertion unavailable: {regular['event']}")
            plan_id = regular["plan"]["plan_id"]
            _request(client, "POST", f"/api/v1/planning/plans/{plan_id}/apply", 200)
            current = _request(
                client, "GET", f"/api/v1/planning/areas/{areas[101]}/2030-01-15/current", 200
            )
            old = {visit["ticket_id"]: visit for visit in initial[101]["visits"]}
            updated = {visit["ticket_id"]: visit for visit in current["visits"]}
            if set(updated) != set(old) | {regular_id}:
                raise AssertionError("Regular apply changed the set of published tickets")
            altered = [
                ticket_id
                for ticket_id, previous in old.items()
                if updated[ticket_id]["worker_id"] != previous["worker_id"]
                or updated[ticket_id]["service_start_at"] != previous["service_start_at"]
            ]
            if altered:
                raise AssertionError(f"Regular apply moved published visits: {altered}")
            for worker_id in {visit["worker_id"] for visit in old.values()}:
                before = [
                    v["ticket_id"]
                    for v in sorted(old.values(), key=lambda v: v["sequence"])
                    if v["worker_id"] == worker_id
                ]
                after = [
                    v["ticket_id"]
                    for v in sorted(updated.values(), key=lambda v: v["sequence"])
                    if v["worker_id"] == worker_id and v["ticket_id"] in old
                ]
                if before != after:
                    raise AssertionError(f"Regular apply changed worker {worker_id} stop order")
            if current["roster"] != initial[101]["roster"] or current["revision"] != 2:
                raise AssertionError("Regular apply changed roster or revision count")
            replay = _request(client, "POST", f"/api/v1/planning/plans/{plan_id}/apply", 200)
            if not replay["already_applied"]:
                raise AssertionError("Repeated apply created another logical result")
            report["steps"].append(
                {
                    "id": "regular_apply",
                    "revision": current["revision"],
                    "published_visits": len(current["visits"]),
                    "old_visits_preserved": len(old),
                    "already_applied_on_replay": replay["already_applied"],
                }
            )
            no_slot_id = ids["tickets"]["42"]
            no_slot = _request(
                client,
                "POST",
                f"/api/v1/planning/areas/{areas[103]}/2030-01-15/tickets/{no_slot_id}/preview",
                201,
                json={"base_day_revision": 1},
            )
            if no_slot["event"]["outcome"] != "not_insertable" or no_slot["plan"] is not None:
                raise AssertionError(
                    f"Impossible ticket received a plan: {no_slot['event']}, "
                    f"plan={no_slot['plan'] is not None}"
                )
            if not no_slot["event"]["candidate_reasons"]:
                raise AssertionError("No-slot preview omitted candidate rejection reasons")
            unchanged = _request(
                client, "GET", f"/api/v1/planning/areas/{areas[103]}/2030-01-15/current", 200
            )
            if unchanged != initial[103]:
                raise AssertionError("No-slot preview changed the published day")
            report["steps"].append(
                {
                    "id": "no_slot",
                    "outcome": no_slot["event"]["outcome"],
                    "reason_count": len(no_slot["event"]["candidate_reasons"]),
                    "revision": unchanged["revision"],
                }
            )
            window_cases = scenarios["window_cases"]
            tight_window_id = ids["tickets"][str(window_cases["no_slot_ticket_id"])]
            before_tight_window = _request(
                client,
                "GET",
                f"/api/v1/planning/areas/{areas[101]}/{scenarios['route_date']}/current",
                200,
            )
            with isolated.connect() as connection:
                tight_window_before = connection.execute(
                    text("SELECT visit_window_start, visit_window_end FROM tickets WHERE id=:id"),
                    {"id": tight_window_id},
                ).one()
            tight_window = _request(
                client,
                "POST",
                f"/api/v1/planning/areas/{areas[101]}/{scenarios['route_date']}/tickets/{tight_window_id}/preview",
                201,
                json={"base_day_revision": before_tight_window["revision"]},
            )
            if (
                tight_window["event"]["can_apply"]
                or tight_window["event"]["outcome"] != "emergency_unassigned"
            ):
                raise AssertionError(
                    f"Emergency exceeded its original 10:00-12:00 window: {tight_window['event']}"
                )
            if tight_window["plan"] and any(
                stop["ticket_id"] == tight_window_id
                for route in tight_window["plan"]["routes"]
                for stop in route["stops"]
            ):
                raise AssertionError("Emergency outside its original window entered the route")
            preserved = _request(
                client,
                "GET",
                f"/api/v1/planning/areas/{areas[101]}/{scenarios['route_date']}/current",
                200,
            )
            if preserved != before_tight_window:
                raise AssertionError("Rejected emergency preview changed the published day")
            report["steps"].append(
                {
                    "id": "S14_original_10_12_window",
                    "outcome": tight_window["event"]["outcome"],
                    "can_apply": tight_window["event"]["can_apply"],
                    "published_revision_unchanged": True,
                }
            )
            with isolated.connect() as connection:
                tight_window_after = connection.execute(
                    text("SELECT visit_window_start, visit_window_end FROM tickets WHERE id=:id"),
                    {"id": tight_window_id},
                ).one()
            if tight_window_after != tight_window_before:
                raise AssertionError("Preview changed the emergency's original customer window")
            emergency_id = ids["tickets"]["45"]
            with isolated.connect() as connection:
                later_window_before = connection.execute(
                    text("SELECT visit_window_start, visit_window_end FROM tickets WHERE id=:id"),
                    {"id": emergency_id},
                ).one()
            emergency = _request(
                client,
                "POST",
                f"/api/v1/planning/areas/{areas[103]}/2030-01-15/tickets/{emergency_id}/preview",
                201,
                json={"base_day_revision": 1},
            )
            event = emergency["event"]
            if event["category"] != "emergency" or not event["can_apply"] or not emergency["plan"]:
                raise AssertionError(f"Emergency preview cannot apply: {event}")
            emergency_plan = emergency["plan"]
            diff = emergency_plan["replan_diff"]
            if not any(item["ticket_id"] == emergency_id for item in diff["added"]):
                raise AssertionError("Emergency is absent from replan diff")
            if not event["sla_forecast"]:
                raise AssertionError("Emergency forecast is missing")
            _request(
                client, "POST", f"/api/v1/planning/plans/{emergency_plan['plan_id']}/apply", 200
            )
            emergency_current = _request(
                client, "GET", f"/api/v1/planning/areas/{areas[103]}/2030-01-15/current", 200
            )
            if (emergency_current["revision"], emergency_current["reason"]) != (
                2,
                "emergency_replan",
            ):
                raise AssertionError("Emergency apply did not publish exactly one revision")
            if emergency_current["roster"] != initial[103]["roster"]:
                raise AssertionError("Emergency replan changed the published roster")
            if emergency_id not in {v["ticket_id"] for v in emergency_current["visits"]}:
                raise AssertionError("Emergency is absent from the published route")
            emergency_visit = next(
                visit for visit in emergency_current["visits"] if visit["ticket_id"] == emergency_id
            )
            original_start = datetime.fromisoformat("2030-01-15T12:00:00+03:00")
            original_end = datetime.fromisoformat("2030-01-15T14:00:00+03:00")
            if not (
                original_start <= datetime.fromisoformat(emergency_visit["service_start_at"])
                and datetime.fromisoformat(emergency_visit["service_end_at"]) <= original_end
            ):
                raise AssertionError("Emergency service is outside its original 12:00-14:00 window")
            with isolated.connect() as connection:
                later_window_after = connection.execute(
                    text("SELECT visit_window_start, visit_window_end FROM tickets WHERE id=:id"),
                    {"id": emergency_id},
                ).one()
            if later_window_after != later_window_before:
                raise AssertionError("Apply changed the emergency's original customer window")
            emergency_replay = _request(
                client, "POST", f"/api/v1/planning/plans/{emergency_plan['plan_id']}/apply", 200
            )
            if not emergency_replay["already_applied"]:
                raise AssertionError("Emergency replay published a second revision")
            with isolated.connect() as connection:
                linkage = connection.execute(
                    text(
                        "SELECT r.event_id, e.ticket_id, r.is_current FROM day_plan_revisions r "
                        "JOIN work_events e ON e.id=r.event_id "
                        "WHERE r.service_area_id=:area AND r.route_date='2030-01-15' "
                        "AND r.revision=2"
                    ),
                    {"area": areas[103]},
                ).one()
                if (linkage[0], linkage[1], linkage[2]) != (
                    event["source_event_id"],
                    emergency_id,
                    True,
                ):
                    raise AssertionError("Emergency revision lost its source event linkage")
            report["steps"].append(
                {
                    "id": "emergency_apply",
                    "outcome": event["outcome"],
                    "revision": emergency_current["revision"],
                    "published_visits": len(emergency_current["visits"]),
                    "event_id": linkage[0],
                    "already_applied_on_replay": True,
                    "forecast": event["sla_forecast"],
                }
            )
    (args.report_dir / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

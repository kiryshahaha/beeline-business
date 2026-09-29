"""Run the Plan 5 synthetic package through backend, PostgreSQL and native planner."""

import argparse
import json
import os
import subprocess
import sys
import time
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from datetime import time as time_of_day
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from acceptance_intraday import run as run_intraday
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


def assert_visits_within_shifts(day):
    """Verify published visits against the admitted roster, including overnight shifts."""
    route_date = date.fromisoformat(day["route_date"])
    moscow = timezone(timedelta(hours=3))
    shifts = {}
    for worker in day["roster"]:
        if not worker["workshift_start"] or not worker["workshift_end"]:
            raise AssertionError(f"Worker {worker['worker_id']} has no published shift")
        start = datetime.combine(
            route_date, time_of_day.fromisoformat(worker["workshift_start"]), moscow
        )
        end = datetime.combine(
            route_date, time_of_day.fromisoformat(worker["workshift_end"]), moscow
        )
        if end <= start:
            end += timedelta(days=1)
        shifts[worker["worker_id"]] = start, end
    for visit in day["visits"]:
        if visit["worker_id"] not in shifts:
            raise AssertionError(f"Ticket {visit['ticket_id']} is assigned outside the roster")
        start, end = shifts[visit["worker_id"]]
        arrival = datetime.fromisoformat(visit["arrival_at"])
        service_start = datetime.fromisoformat(visit["service_start_at"])
        service_end = datetime.fromisoformat(visit["service_end_at"])
        if not start <= arrival <= service_start < service_end <= end:
            raise AssertionError(f"Visit of ticket {visit['ticket_id']} left its worker shift")


def _route_snapshots(client, database, day, historical_route_ids=frozenset()):
    """Check every published stop against the route GeoJSON and ticket address."""
    visits_by_route = {}
    for visit in day["visits"]:
        visits_by_route.setdefault(visit["route_id"], []).append(visit)
    with database.connect() as connection:
        coordinates = {
            ticket_id: [float(longitude), float(latitude)]
            for ticket_id, longitude, latitude in connection.execute(
                text(
                    "SELECT t.id, l.longitude, l.latitude FROM tickets t "
                    "JOIN locations l ON l.id=t.location_id"
                )
            )
        }
    snapshots = {}
    for route_id, visits in visits_by_route.items():
        if route_id is None:
            raise AssertionError("Published visit has no saved route")
        route = _request(client, "GET", f"/api/v1/routes/{route_id}", 200)
        geojson = _request(client, "GET", f"/api/v1/routes/{route_id}/geojson", 200)
        historical = route_id in historical_route_ids
        if day["revision"] > 1 and not historical and route["day_revision"] != day["revision"]:
            raise AssertionError(f"Route {route_id} points to another revision")
        if geojson != route["geojson"]:
            raise AssertionError(f"Route {route_id} GeoJSON download differs from saved route")
        stops = [
            feature
            for feature in geojson["features"]
            if feature["geometry"]["type"] == "Point"
            and feature["properties"].get("ticket_id") is not None
        ]
        expected = sorted(visits, key=lambda visit: visit["sequence"])
        actual_ids = [point["properties"]["ticket_id"] for point in stops]
        expected_ids = [visit["ticket_id"] for visit in expected]
        if historical:
            actual_ids = [ticket_id for ticket_id in actual_ids if ticket_id in expected_ids]
        if actual_ids != expected_ids:
            raise AssertionError(f"Route {route_id} GeoJSON stop order differs from revision")
        for point in stops:
            ticket_id = point["properties"]["ticket_id"]
            if (
                ticket_id in expected_ids
                and point["geometry"]["coordinates"] != coordinates[ticket_id]
            ):
                raise AssertionError(f"Route {route_id} has stale coordinates for {ticket_id}")
        snapshots[route_id] = geojson
    return snapshots


def _assert_historical_geometry(client, snapshots):
    for route_id, before in snapshots.items():
        after = _request(client, "GET", f"/api/v1/routes/{route_id}/geojson", 200)
        if after != before:
            raise AssertionError(f"Historical route {route_id} changed")


def _execution_event(
    client, ticket_id, event, revision, occurred_at, *, worker_id=None, location_id=None
):
    payload = {"expected_revision": revision, "occurred_at": occurred_at, "payload": {}}
    if worker_id is not None:
        payload["worker_id"] = worker_id
    if location_id is not None:
        payload["location_id"] = location_id
    return _request(
        client,
        "POST",
        f"/api/v1/tickets/{ticket_id}/{event}",
        200,
        headers={"Idempotency-Key": f"plan5-s10-{ticket_id}-{event}"},
        json=payload,
    )


def _complete_s10_route_prefix(client, database, current, office_location_id, received_at):
    received = datetime.fromisoformat(received_at)
    cutoff = received - timedelta(minutes=5)
    grouped = {}
    for visit in current["visits"]:
        grouped.setdefault(visit["worker_id"], []).append(visit)

    candidates = []
    for worker_id, visits in grouped.items():
        visits.sort(key=lambda visit: visit["sequence"])
        for index, visit in enumerate(visits):
            start = datetime.fromisoformat(visit["service_start_at"])
            future = any(
                datetime.fromisoformat(item["service_start_at"]) > received
                for item in visits[index + 1 :]
            )
            if start < cutoff - timedelta(minutes=30) and future:
                candidates.append((start, worker_id, visits[: index + 1]))
    if not candidates:
        raise AssertionError("S10 fixture has no worker with completed work and a future visit")

    _, worker_id, prefix = max(candidates, key=lambda item: item[0])
    completed = []
    source_location_id = office_location_id
    previous_completion = None
    for visit in prefix:
        start = datetime.fromisoformat(visit["service_start_at"])
        planned_end = datetime.fromisoformat(visit["service_end_at"])
        completed_at = min(planned_end, cutoff)
        with database.connect() as connection:
            revision, location_id = connection.execute(
                text("SELECT revision, location_id FROM tickets WHERE id=:id"),
                {"id": visit["ticket_id"]},
            ).one()
        dispatch_at = start - timedelta(minutes=5)
        route_at = start - timedelta(minutes=2)
        if previous_completion is not None and dispatch_at <= previous_completion:
            dispatch_at = previous_completion + timedelta(seconds=1)
            route_at = dispatch_at + timedelta(seconds=1)
        if route_at >= start or completed_at < start:
            raise AssertionError(
                f"S10 fixture cannot complete ticket {visit['ticket_id']} in order"
            )

        event = _execution_event(
            client, visit["ticket_id"], "dispatch", revision, dispatch_at.isoformat()
        )
        event = _execution_event(
            client,
            visit["ticket_id"],
            "start-route",
            event["revision"],
            route_at.isoformat(),
            worker_id=worker_id,
            location_id=source_location_id,
        )
        event = _execution_event(
            client,
            visit["ticket_id"],
            "start",
            event["revision"],
            start.isoformat(),
            worker_id=worker_id,
            location_id=location_id,
        )
        _execution_event(
            client,
            visit["ticket_id"],
            "complete",
            event["revision"],
            completed_at.isoformat(),
            worker_id=worker_id,
            location_id=location_id,
        )
        completed.append(visit["ticket_id"])
        source_location_id = location_id
        previous_completion = completed_at
    return {"worker_id": worker_id, "ticket_ids": completed, "safe_point_at": previous_completion}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "backend/.local/acceptance-plan5")
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    clock_file = args.report_dir / "acceptance-clock.txt"
    clock_file.write_text("2030-01-15T08:20:00+03:00\n", encoding="utf-8")
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
            "ACCEPTANCE_CLOCK_FILE": str(clock_file),
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
                json={"username": tables["users"][0]["username"], "password": PASSWORD},
            )
            client.headers.update({"Authorization": f"Bearer {login['access_token']}"})
            areas = {source: ids["service_areas"][str(source)] for source in (101, 102, 103)}
            roster = set(scenarios["roster_worker_ids"])
            workers = {row["user_id"]: row["service_area_id"] for row in tables["workers"]}
            initial = {}
            for source, area_id in areas.items():
                # The package has no published day: the native planner builds the first plan
                # from the morning requests and the area's roster.
                morning = [
                    ids["tickets"][str(case["ticket_id"])]
                    for case in scenarios["tickets"]
                    if case["phase"] == "planned" and case["service_area_id"] == source
                ]
                crew = [
                    ids["workers"][str(worker)]
                    for worker, area in sorted(workers.items())
                    if worker in roster and area == source
                ]
                first = _request(
                    client,
                    "POST",
                    "/api/v1/planning/preview",
                    201,
                    json={
                        "route_date": "2030-01-15",
                        "service_area_id": area_id,
                        "ticket_ids": morning,
                        "worker_ids": crew,
                        "allow_partial": True,
                    },
                )
                if first["unassigned"]:
                    raise AssertionError(f"Initial plan left requests: {first['unassigned']}")
                _request(client, "POST", f"/api/v1/planning/plans/{first['plan_id']}/apply", 200)
                current = _request(
                    client, "GET", f"/api/v1/planning/areas/{area_id}/2030-01-15/current", 200
                )
                if current["revision"] != 1 or len(current["visits"]) != len(morning):
                    raise AssertionError(f"Initial plan of area {source} was not published")
                assert_visits_within_shifts(current)
                initial[source] = current
                report["steps"].append(
                    {
                        "id": f"initial_{source}",
                        "plan_id": first["plan_id"],
                        "solver_status": first.get("solver_status"),
                        "revision": current["revision"],
                        "visits": len(current["visits"]),
                        "roster": len(current["roster"]),
                    }
                )
            initial_geometry = {
                source: _route_snapshots(client, isolated, initial[source]) for source in (101, 103)
            }
            route_day = datetime.fromisoformat(f"{scenarios['route_date']}T00:00:00+03:00").date()
            for source, current in initial.items():
                shifts = {}
                lengths = []
                for member in current["roster"]:
                    start = datetime.combine(
                        route_day, time_of_day.fromisoformat(member["workshift_start"]), MOSCOW
                    )
                    end = datetime.combine(
                        route_day, time_of_day.fromisoformat(member["workshift_end"]), MOSCOW
                    )
                    if end <= start:
                        end += timedelta(days=1)
                    shifts[member["worker_id"]] = (start, end)
                    lengths.append(int((end - start).total_seconds() // 60))
                expected_shifts = {}
                for worker in tables["workers"]:
                    if worker["user_id"] not in roster or worker["service_area_id"] != source:
                        continue
                    start = datetime.combine(route_day, worker["workshift_start"], MOSCOW)
                    end = datetime.combine(route_day, worker["workshift_end"], MOSCOW)
                    if end <= start:
                        end += timedelta(days=1)
                    expected_shifts[ids["workers"][str(worker["user_id"])]] = (start, end)
                if shifts != expected_shifts:
                    raise AssertionError(f"Area {source} changed imported shift profiles")
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
            reassigned = [
                ticket_id
                for ticket_id, previous in old.items()
                if updated[ticket_id]["worker_id"] != previous["worker_id"]
            ]
            if reassigned:
                raise AssertionError(f"Regular apply reassigned published visits: {reassigned}")
            # S05 keeps assignments and order; a later stop may start later inside its fixed
            # window, and every such shift must be declared in the preview diff.
            moved = sorted(
                ticket_id
                for ticket_id, previous in old.items()
                if updated[ticket_id]["service_start_at"] != previous["service_start_at"]
            )
            undeclared = set(moved) - set(regular["event"]["shifted_ticket_ids"])
            if undeclared:
                raise AssertionError(f"Regular apply moved undeclared visits: {sorted(undeclared)}")
            windows = {
                ids["tickets"][str(case["ticket_id"])]: [
                    datetime.fromisoformat(value) for value in case["window"]
                ]
                for case in scenarios["tickets"]
            }
            for ticket_id, visit in updated.items():
                start = datetime.fromisoformat(visit["service_start_at"])
                end = datetime.fromisoformat(visit["service_end_at"])
                window_start, window_end = windows[ticket_id]
                if start < window_start or end > window_end:
                    raise AssertionError(f"Visit of ticket {ticket_id} left its window")
                if ticket_id in old and start < datetime.fromisoformat(
                    old[ticket_id]["service_start_at"]
                ):
                    raise AssertionError(f"Regular apply moved ticket {ticket_id} earlier")
            inserted = updated[regular_id]
            neighbours = [
                v["sequence"] for v in old.values() if v["worker_id"] == inserted["worker_id"]
            ]
            if not neighbours or not min(neighbours) < inserted["sequence"] <= max(neighbours):
                raise AssertionError("Regular ticket was not inserted between two stops")
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
            assert_visits_within_shifts(current)

            regular_geometry = _route_snapshots(client, isolated, current)
            _assert_historical_geometry(client, initial_geometry[101])
            if not set(regular_geometry) - set(initial_geometry[101]):
                raise AssertionError("Regular insertion did not save new route geometry")
            replay = _request(client, "POST", f"/api/v1/planning/plans/{plan_id}/apply", 200)
            if not replay["already_applied"]:
                raise AssertionError("Repeated apply created another logical result")
            report["steps"].append(
                {
                    "id": "regular_apply",
                    "revision": current["revision"],
                    "published_visits": len(current["visits"]),
                    "old_visits_preserved": len(old),
                    "inserted": {
                        key: inserted[key]
                        for key in ("worker_id", "sequence", "service_start_at", "service_end_at")
                    },
                    "shifted_within_windows": moved,
                    "all_visits_within_shifts": True,
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
            _assert_historical_geometry(client, initial_geometry[103])
            report["steps"].append(
                {
                    "id": "no_slot",
                    "outcome": no_slot["event"]["outcome"],
                    "reason_count": len(no_slot["event"]["candidate_reasons"]),
                    "revision": unchanged["revision"],
                }
            )
            clock_file.write_text("2030-01-15T11:45:00+03:00\n", encoding="utf-8")
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
            with isolated.connect() as connection:
                plans_before_experiment = connection.execute(
                    text("SELECT count(*) FROM planning_plans")
                ).scalar_one()
            experiment = _request(
                client,
                "POST",
                f"/api/v1/planning/areas/{areas[101]}/{scenarios['route_date']}/window-experiment",
                200,
                json={
                    "base_day_revision": before_tight_window["revision"],
                    "allow_partial": True,
                    "windows": [
                        {
                            "ticket_id": tight_window_id,
                            "visit_window_start": "2030-01-15T10:00:00+03:00",
                            "visit_window_end": "2030-01-15T14:00:00+03:00",
                        }
                    ],
                },
            )
            override = experiment["window_overrides"][0]
            if (
                not experiment["experimental"]
                or experiment["applied"]
                or datetime.fromisoformat(override["original_visit_window_start"])
                != tight_window_before.visit_window_start
                or datetime.fromisoformat(override["original_visit_window_end"])
                != tight_window_before.visit_window_end
                or datetime.fromisoformat(override["scenario_visit_window_end"])
                != datetime.fromisoformat("2030-01-15T14:00:00+03:00")
            ):
                raise AssertionError("S15 comparison used an unexpected customer window")
            if set(experiment["baseline"]["metrics"]) != set(experiment["experiment"]["metrics"]):
                raise AssertionError("S15 baseline and experiment metrics are not comparable")
            baseline_ids = {
                stop["ticket_id"]
                for route in experiment["baseline"]["routes"]
                for stop in route["stops"]
            }
            experiment_ids = {
                stop["ticket_id"]
                for route in experiment["experiment"]["routes"]
                for stop in route["stops"]
            }
            if tight_window_id in baseline_ids or tight_window_id not in experiment_ids:
                raise AssertionError("S15 window expansion did not isolate the emergency")
            if (
                _request(
                    client,
                    "GET",
                    f"/api/v1/planning/areas/{areas[101]}/{scenarios['route_date']}/current",
                    200,
                )
                != before_tight_window
            ):
                raise AssertionError("S15 experiment changed the published day")
            with isolated.connect() as connection:
                plans_after_experiment = connection.execute(
                    text("SELECT count(*) FROM planning_plans")
                ).scalar_one()
                ticket_window_after_experiment = connection.execute(
                    text("SELECT visit_window_start, visit_window_end FROM tickets WHERE id=:id"),
                    {"id": tight_window_id},
                ).one()
            if (
                plans_after_experiment != plans_before_experiment
                or ticket_window_after_experiment != tight_window_before
            ):
                raise AssertionError("S15 experiment saved a plan or changed the ticket")
            _assert_historical_geometry(client, regular_geometry)
            report["steps"].append(
                {
                    "id": "S15_window_experiment_10_12_vs_10_14",
                    "baseline": experiment["baseline"]["metrics"],
                    "experiment": experiment["experiment"]["metrics"],
                    "published_revision_unchanged": True,
                }
            )
            emergency_id = ids["tickets"]["45"]
            with isolated.connect() as connection:
                emergency_meta = connection.execute(
                    text(
                        "SELECT received_at, response_deadline_at, visit_window_start, "
                        "visit_window_end FROM tickets WHERE id=:id"
                    ),
                    {"id": emergency_id},
                ).one()
                later_window_before = (
                    emergency_meta.visit_window_start,
                    emergency_meta.visit_window_end,
                )
            clock_file.write_text("2030-01-15T11:45:00+03:00\n", encoding="utf-8")
            safe_point = _complete_s10_route_prefix(
                client,
                isolated,
                initial[103],
                ids["locations"]["1"],
                emergency_meta.received_at.isoformat(),
            )
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
            forecast = event["sla_forecast"]
            if event["selection_reason"]["code"] != "emergency_response_priority":
                raise AssertionError("Emergency selection policy is missing from preview")
            if forecast["response_target_minutes"] != 120 or not forecast["response_deadline_met"]:
                raise AssertionError(f"120-minute response target was not met: {forecast}")
            if forecast["response_timeline_valid"] is not True:
                raise AssertionError(f"Emergency forecast starts before receipt: {forecast}")
            if (
                datetime.fromisoformat(forecast["response_deadline_at"])
                != emergency_meta.response_deadline_at
                or datetime.fromisoformat(forecast["visit_window_start"])
                != emergency_meta.visit_window_start
                or datetime.fromisoformat(forecast["visit_window_end"])
                != emergency_meta.visit_window_end
            ):
                raise AssertionError(
                    f"Emergency response preview changed its SLA or window: {forecast}"
                )
            changed_ids = {
                item["ticket_id"]
                for item in diff["changed"] + diff["removed"] + diff["preempted_tickets"]
            }
            if changed_ids.intersection(safe_point["ticket_ids"]):
                raise AssertionError("Emergency preview changed completed work")
            worker_future = [
                visit
                for route in emergency_plan["routes"]
                if route["worker_id"] == safe_point["worker_id"]
                for visit in route["stops"]
                if visit["ticket_id"] not in safe_point["ticket_ids"]
            ]
            if any(
                datetime.fromisoformat(visit["service_start_at"]) < safe_point["safe_point_at"]
                for visit in worker_future
            ):
                raise AssertionError("Emergency route starts before the confirmed safe point")
            current_before_apply = _request(
                client, "GET", f"/api/v1/planning/areas/{areas[103]}/2030-01-15/current", 200
            )
            if current_before_apply["revision"] != initial[103]["revision"]:
                raise AssertionError("Emergency preview changed the published day before apply")
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
            assert_visits_within_shifts(emergency_current)
            if emergency_id not in {v["ticket_id"] for v in emergency_current["visits"]}:
                raise AssertionError("Emergency is absent from the published route")
            emergency_geometry = _route_snapshots(
                client, isolated, emergency_current, set(initial_geometry[103])
            )
            _assert_historical_geometry(client, initial_geometry[103])
            if not set(emergency_geometry) - set(initial_geometry[103]):
                raise AssertionError("Emergency replan did not save new route geometry")
            report["steps"].append(
                {
                    "id": "S17_geojson_revisions",
                    "regular_routes": len(regular_geometry),
                    "emergency_routes": len(emergency_geometry),
                    "historical_geometry_unchanged": True,
                }
            )
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
            if tuple(later_window_after) != later_window_before:
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
                    "safe_point": {
                        "worker_id": safe_point["worker_id"],
                        "completed_ticket_ids": safe_point["ticket_ids"],
                        "available_at": safe_point["safe_point_at"].isoformat(),
                    },
                }
            )

            emergency_60_id = ids["tickets"]["44"]
            emergency_60 = _request(
                client,
                "POST",
                f"/api/v1/planning/areas/{areas[102]}/2030-01-15/tickets/{emergency_60_id}/preview",
                201,
                json={"base_day_revision": 1},
            )
            forecast_60 = emergency_60["event"]["sla_forecast"]
            if forecast_60["response_target_minutes"] != 60:
                raise AssertionError(f"60-minute response target is missing: {forecast_60}")
            if forecast_60["response_deadline_met"] is None:
                raise AssertionError(f"60-minute response target has no result: {forecast_60}")
            if emergency_60["event"]["can_apply"]:
                if forecast_60["response_timeline_valid"] is not True:
                    raise AssertionError(
                        f"60-minute emergency starts before receipt: {forecast_60}"
                    )
                if (
                    forecast_60["response_deadline_met"] is False
                    and emergency_60["event"]["outcome"] != "sla_violation"
                ):
                    raise AssertionError("Missed 60-minute response target is not labeled")
            elif (
                forecast_60["response_sla_status"] != "unassigned"
                or forecast_60["response_deadline_met"] is not False
            ):
                raise AssertionError(
                    f"Unassigned 60-minute response is not explicit: {forecast_60}"
                )
            unchanged_102 = _request(
                client, "GET", f"/api/v1/planning/areas/{areas[102]}/2030-01-15/current", 200
            )
            if unchanged_102["revision"] != initial[102]["revision"]:
                raise AssertionError("60-minute response preview changed the published day")
            report["steps"].append(
                {
                    "id": "emergency_60_minute_preview",
                    "outcome": emergency_60["event"]["outcome"],
                    "forecast": forecast_60,
                    "published_revision": unchanged_102["revision"],
                }
            )
            run_intraday(client, base, isolated, ids, tables, report)
    (args.report_dir / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

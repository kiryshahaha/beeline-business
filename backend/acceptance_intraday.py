"""Plan 5 intraday scenarios on the imported acceptance package.

The runner in run_acceptance_plan5.py imports the package, starts the backend, the native
planner and the routing stub, then hands a logged-in client to `run`. Scenarios go through
the public API and pick their areas, engineers, brigades and work types from scenarios.json,
the published day revisions and the imported catalogs, so the package may change its values.
SQL only reads stored results or arranges a starting condition: a contradicting engineer
area (S18), a qualification of the engineer outside the roster (S19) and a failing commit
(S20).
"""

import json
import threading
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text

from app.modules.data_exchange.formats import serialize

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = json.loads(
    (ROOT / "data/synthetic/acceptance/scenarios.json").read_text(encoding="utf-8")
)
DAY = SCENARIOS["route_date"]
MOSCOW = ZoneInfo("Europe/Moscow")
TRANSPORTS = ("car", "walking", "bicycle", "public_transport")
EMERGENCY_OUTCOMES = {
    "emergency_replan_ready",
    "waiting_safe_point",
    "emergency_unassigned",
    "sla_risk",
    "sla_violation",
}
REGULAR_OUTCOMES = {"insertion_ready", "not_insertable"}
AREA_CONFLICTS = {"service_area_configuration_mismatch", "worker_service_area_unresolved"}
SHIFT_CODES = {"window_outside_shift", "outside_shift_horizon", "service_after_shift"}
SERVICE = timedelta(minutes=30)


def at(clock) -> str:
    if isinstance(clock, datetime):
        return clock.isoformat()
    return f"{DAY}T{clock}:00+03:00"


def moment(value) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def local(value: time) -> datetime:
    return datetime.combine(datetime.fromisoformat(DAY).date(), value, MOSCOW)


def minutes(value: int) -> timedelta:
    return timedelta(minutes=value)


def check(condition, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _candidate_codes(event: dict) -> dict[int, str]:
    return {
        item["worker_id"]: item["reason"]["code"]
        for item in event["candidate_reasons"]
        if "worker_id" in item
    }


def _refusal(codes_by_worker: dict, ticket_reason: str | None, worker: int) -> str | None:
    """A candidate's own reason, or the ticket's when no engineer was examined."""
    return codes_by_worker.get(worker) or ticket_reason


class Run:
    def __init__(self, client, base_url, engine, ids, package, report):
        self.client = client
        self.base_url = base_url
        self.engine = engine
        self.ids = ids
        self.package = package
        self.report = report
        sources = sorted({ticket["service_area_id"] for ticket in SCENARIOS["tickets"]})
        self.areas = [ids["service_areas"][str(source)] for source in sources]
        self.outsider = ids["users"][str(SCENARIOS["outside_roster_worker_id"])]
        self.profiles = {row["id"]: dict(row) for row in self.rows(PROFILES_SQL)}
        self.work_types = {
            row["id"]: row
            for row in self.rows(WORK_TYPES_SQL, ids=list(ids["work_types"].values()))
        }
        self.offices = {
            row["service_area_id"]: row["id"]
            for row in self.rows(
                "SELECT id, service_area_id FROM offices WHERE id = ANY(:ids) ORDER BY id",
                ids=list(ids["offices"].values()),
            )
        }
        self.roster = {
            area: [entry["worker_id"] for entry in self.day(area)["roster"]] for area in self.areas
        }

    # --- HTTP -------------------------------------------------------------------------

    def call(self, method, path, expected, *, now=None, headers=None, client=None, **kwargs):
        headers = dict(headers or {})
        if now is not None:
            headers["X-Acceptance-Now"] = at(now)
        response = (client or self.client).request(method, path, headers=headers, **kwargs)
        try:
            body = response.json() if response.content else None
        except ValueError:
            body = response.text
        allowed = expected if isinstance(expected, tuple) else (expected,)
        if response.status_code not in allowed:
            raise AssertionError(f"{method} {path}: {response.status_code} {body}")
        return (response.status_code, body) if isinstance(expected, tuple) else body

    def day(self, area: int, revision: int | None = None) -> dict:
        tail = "current" if revision is None else f"revisions/{revision}"
        return self.call("GET", f"/api/v1/planning/areas/{area}/{DAY}/{tail}", 200)

    def preview(self, area, ticket_id, revision, *, now, expected=201, **extra):
        return self.call(
            "POST",
            f"/api/v1/planning/areas/{area}/{DAY}/tickets/{ticket_id}/preview",
            expected,
            now=now,
            json={"base_day_revision": revision, **extra},
        )

    def replan(self, area, revision, *, now) -> dict:
        return self.call(
            "POST",
            f"/api/v1/planning/areas/{area}/{DAY}/replan/preview",
            201,
            now=now,
            json={"base_day_revision": revision},
        )

    def apply(self, plan_id, *, now, expected=200, client=None):
        return self.call(
            "POST", f"/api/v1/planning/plans/{plan_id}/apply", expected, now=now, client=client
        )

    def ticket(self, ticket_id: int) -> dict:
        return self.call("GET", f"/api/v1/tickets/{ticket_id}", 200)

    @staticmethod
    def event_key(action: str, ticket_id: int, revision: int) -> str:
        return f"acceptance-{action}-{ticket_id}-{revision}"

    def execute(self, ticket_id: int, action: str, clock, **fields) -> dict:
        revision = self.ticket(ticket_id)["revision"]
        return self.call(
            "POST",
            f"/api/v1/tickets/{ticket_id}/{action}",
            200,
            now=clock,
            headers={"Idempotency-Key": self.event_key(action, ticket_id, revision)},
            json={"expected_revision": revision, "occurred_at": at(clock), **fields},
        )

    def advance(self, area: int, clock, *, keep=()) -> None:
        """Execute every published visit that started before `clock`, as planned.

        Engineers of the kept visits stay on them; the scenario drives their stage itself.
        """
        now = moment(at(clock))
        visits = sorted(
            self.day(area)["visits"], key=lambda visit: (visit["worker_id"], visit["sequence"])
        )
        held = {visit["worker_id"] for visit in visits if visit["ticket_id"] in keep}
        for visit in visits:
            ticket_id = visit["ticket_id"]
            start = moment(visit["service_start_at"])
            end = moment(visit["service_end_at"])
            if visit["worker_id"] in held or start >= now:
                continue
            state = self.lifecycle(ticket_id)
            if state in {"assigned", "dispatched"}:
                self.execute(ticket_id, "start-route", start - minutes(5))
                state = "en_route"
            if state == "en_route":
                self.execute(ticket_id, "start", start)
                state = "in_progress"
            if state == "in_progress" and end <= now:
                self.execute(ticket_id, "complete", end, note="Работа выполнена")

    def location_in(self, area: int) -> int:
        first = min(self.day(area)["visits"], key=lambda visit: visit["ticket_id"])
        return self.location_of(first["ticket_id"])

    def ticket_body(self, *, area, work_type, received, window, **fields) -> dict:
        return {
            "location_id": fields.pop("location_id", None) or self.location_in(area),
            "service_area_id": area,
            "work_type_id": work_type,
            "received_at": at(received),
            "visit_window_start": at(window[0]),
            "visit_window_end": at(window[1]),
            "estimated_duration_minutes": int(SERVICE.total_seconds() // 60),
            **fields,
        }

    def create_ticket(self, *, area, brigade, work_type, received, window, office=None, **fields):
        """Receive a ticket, give it the brigade and reserve its kit (office=False: none)."""
        body = self.ticket_body(
            area=area, work_type=work_type, received=received, window=window, **fields
        )
        ticket_id = self.call("POST", "/api/v1/tickets", 201, now=received, json=body)["id"]
        self.settle(ticket_id, area=area, brigade=brigade, work_type=work_type, office=office)
        return ticket_id

    def settle(self, ticket_id, *, area, brigade, work_type, office=None) -> None:
        self.call("PUT", f"/api/v1/tickets/{ticket_id}/brigade", 200, json={"brigade_id": brigade})
        if office is not False:
            self.reserve(ticket_id, work_type, office or self.offices[area])

    def reserve(self, ticket_id: int, work_type: int, office: int) -> None:
        for appliance, quantity in self.work_types[work_type]["appliances"].items():
            self.call(
                "POST",
                f"/api/v1/tickets/{ticket_id}/appliances",
                201,
                json={"appliance_id": int(appliance), "quantity": quantity, "office_id": office},
            )

    # --- stored state -----------------------------------------------------------------

    def rows(self, sql: str, **params) -> list:
        with self.engine.connect() as connection:
            return list(connection.execute(text(sql), params).mappings())

    def scalar(self, sql: str, **params):
        with self.engine.connect() as connection:
            return connection.execute(text(sql), params).scalar()

    def write(self, sql: str, **params) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(sql), params)

    def lifecycle(self, ticket_id: int) -> str:
        return self.scalar("SELECT lifecycle_state FROM tickets WHERE id=:id", id=ticket_id)

    def location_of(self, ticket_id: int) -> int:
        return self.scalar("SELECT location_id FROM tickets WHERE id=:id", id=ticket_id)

    def last_notification(self) -> int:
        return self.scalar("SELECT COALESCE(max(id), 0) FROM notification_events")

    def day_state(self, worker_id: int) -> dict:
        return self.rows(
            "SELECT current_ticket_id, current_destination_id, last_location_id, revision "
            "FROM worker_day_states WHERE worker_id=:worker AND route_date=:day",
            worker=worker_id,
            day=DAY,
        )[0]

    def step(self, **data) -> None:
        self.report["steps"].append(data)

    # --- the fixture, derived instead of hard-coded -------------------------------------

    def qualified(self, worker: int, work_type: int) -> bool:
        return set(self.work_types[work_type]["skills"]) <= set(self.profiles[worker]["skills"])

    def work_type(self, category: str) -> int:
        found = [wt for wt, row in self.work_types.items() if row["category"] == category]
        check(found, f"fixture: no {category} work type")
        return found[0]

    def regular_type(self) -> int:
        regular = [wt for wt, row in self.work_types.items() if row["category"] != "emergency"]
        check(regular, "fixture: no regular work type")
        return min(regular, key=lambda wt: (len(self.work_types[wt]["skills"]), wt))

    def first_open_visit(self, area: int, worker: int) -> dict:
        visits = sorted(
            (visit for visit in self.day(area)["visits"] if visit["worker_id"] == worker),
            key=lambda visit: visit["sequence"],
        )
        for visit in visits:
            if self.lifecycle(visit["ticket_id"]) in {"assigned", "dispatched"}:
                return visit
        raise AssertionError(f"fixture: worker {worker} has no open visit")

    def roles(self) -> dict:
        emergency, regular = self.work_type("emergency"), self.regular_type()
        outsider = self.profiles[self.outsider]
        area_b = outsider["service_area_id"]
        check(area_b in self.areas, "fixture: the outsider has no area of the package")
        check(self.outsider not in self.roster[area_b], "fixture: the outsider is in the roster")
        busy = {visit["worker_id"] for area in self.areas for visit in self.day(area)["visits"]}
        worker_b = next(
            (
                worker
                for worker in self.roster[area_b]
                if self.profiles[worker]["brigade_id"] == outsider["brigade_id"]
                and self.qualified(worker, emergency)
                and worker in busy
            ),
            None,
        )
        check(worker_b, "fixture: no qualified roster engineer in the outsider's brigade")
        area_a, worker_a = next(
            (
                (area, worker)
                for area in self.areas
                if area != area_b
                for worker in self.roster[area]
                if self.qualified(worker, emergency) and worker in busy
            ),
            (None, None),
        )
        check(area_a, "fixture: no second area with a qualified emergency engineer")
        area_c = next((area for area in self.areas if area not in {area_a, area_b}), None)
        check(area_c, "fixture: the package needs a third area")
        brigades = {}
        for worker in self.roster[area_c]:
            if self.qualified(worker, regular) and worker in busy:
                brigades.setdefault(self.profiles[worker]["brigade_id"], []).append(worker)
        pair = next(
            (
                (brigade, sorted(workers)[:2])
                for brigade, workers in brigades.items()
                if len(workers) > 1
            ),
            None,
        )
        check(pair, "fixture: no brigade with two engineers in the third area")
        other_brigade = next(
            (
                self.profiles[worker]["brigade_id"]
                for worker in self.roster[area_c]
                if self.profiles[worker]["brigade_id"] != pair[0]
            ),
            None,
        )
        check(other_brigade, "fixture: the third area needs a second brigade")
        return {
            "emergency": emergency,
            "regular": regular,
            "area_a": area_a,
            "worker_a": worker_a,
            "area_b": area_b,
            "worker_b": worker_b,
            "area_c": area_c,
            "brigade_c": pair[0],
            "pair": pair[1],
            "other_brigade": other_brigade,
        }

    # --- S20: one revision, one set of consequences ------------------------------------

    def check_published(self, area: int, before: dict, after: dict, since: int, *, event=None):
        """Assignments, times, routes, history, event linkage and notices follow one revision."""
        check(after["revision"] == before["revision"] + 1, f"{area}: not exactly one revision")
        check(after["previous_revision"] == before["revision"], f"{area}: broken revision chain")
        history = {
            item["revision"]: item
            for item in self.call("GET", f"/api/v1/planning/areas/{area}/{DAY}/revisions", 200)
        }
        check(
            not history[before["revision"]]["is_current"]
            and history[before["revision"]]["superseded_by_revision"] == after["revision"]
            and history[after["revision"]]["is_current"],
            f"{area}: history does not hand over the current revision",
        )
        stored = self.day(area, before["revision"])
        for field in ("visits", "roster", "unassigned_ticket_ids", "diff", "plan_id", "event_id"):
            check(stored[field] == before[field], f"{area}: old revision changed its {field}")
        if event is not None:
            check(after["event_id"] == event["source_event_id"], f"{area}: event linkage lost")
            linked = self.rows(
                "SELECT ticket_id, event_type FROM work_events WHERE id=:id", id=after["event_id"]
            )[0]
            check(
                (linked["ticket_id"], linked["event_type"]) == (event["ticket_id"], "new_ticket"),
                f"{area}: revision points at another event",
            )
        visits = {visit["ticket_id"]: visit for visit in after["visits"]}
        tickets = {
            row["id"]: row
            for row in self.rows(
                "SELECT id, assigned_worker_id, planned_start_at, lifecycle_state "
                "FROM tickets WHERE id = ANY(:ids)",
                ids=list(visits) + list(after["unassigned_ticket_ids"]),
            )
        }
        routes = {
            row["id"]: row["geojson"]
            for row in self.rows(
                "SELECT id, geojson FROM routes WHERE id = ANY(:ids)",
                ids=sorted({visit["route_id"] for visit in visits.values() if visit["route_id"]}),
            )
        }
        for ticket_id, visit in visits.items():
            ticket = tickets[ticket_id]
            check(
                ticket["assigned_worker_id"] == visit["worker_id"],
                f"ticket {ticket_id}: assignee differs from revision",
            )
            # Started work keeps the time it really began; the rest follows the revision.
            if ticket["lifecycle_state"] in {"assigned", "dispatched"}:
                check(
                    ticket["planned_start_at"] == moment(visit["service_start_at"]),
                    f"ticket {ticket_id}: planned time differs from revision",
                )
            if visit["route_id"] is not None:
                check(visit["route_id"] in routes, f"ticket {ticket_id}: route is missing")
                check(
                    any(
                        feature["properties"].get("ticket_id") == ticket_id
                        for feature in routes[visit["route_id"]]["features"]
                    ),
                    f"ticket {ticket_id}: absent from its stored route",
                )
        for ticket_id in after["unassigned_ticket_ids"]:
            check(
                tickets[ticket_id]["assigned_worker_id"] is None,
                f"ticket {ticket_id}: unassigned in revision but kept its engineer",
            )
        notes = self.rows(
            "SELECT recipient_id, ticket_id, kind, data FROM notification_events "
            "WHERE id > :since AND kind IN ('ticket_assigned', 'ticket_unassigned', "
            "'ticket_rescheduled') ORDER BY id",
            since=since,
        )
        diff = after["diff"]
        added = {item["ticket_id"]: item["worker_id"] for item in diff.get("added", [])}
        dropped = {item["ticket_id"]: item["worker_id"] for item in diff.get("removed", [])}
        rescheduled = {}
        for change in diff.get("changed", []):
            fields = change.get("changes", {})
            if "worker_id" in fields:
                added[change["ticket_id"]] = fields["worker_id"]["to"]
                dropped[change["ticket_id"]] = fields["worker_id"]["from"]
            start = fields.get("service_start_at")
            if start and start.get("from") and start.get("to"):
                if abs(moment(start["to"]) - moment(start["from"])) >= minutes(15):
                    rescheduled[change["ticket_id"]] = start["to"]
        for ticket_id in added:
            if ticket_id in tickets and ticket_id not in dropped:
                check(
                    tickets[ticket_id]["lifecycle_state"] != "waiting_assignment",
                    f"ticket {ticket_id}: published but still waiting for assignment",
                )
        sent = {kind: {} for kind in ("ticket_assigned", "ticket_unassigned", "ticket_rescheduled")}
        for note in notes:
            sent[note["kind"]].setdefault(note["ticket_id"], []).append(note)
        check(
            {
                ticket_id: [note["recipient_id"] for note in items]
                for ticket_id, items in sent["ticket_assigned"].items()
            }
            == {ticket_id: [worker] for ticket_id, worker in added.items()},
            f"{area}: assignment notices differ from the revision {sent['ticket_assigned']}",
        )
        check(
            {
                ticket_id: [note["recipient_id"] for note in items]
                for ticket_id, items in sent["ticket_unassigned"].items()
            }
            == {ticket_id: [worker] for ticket_id, worker in dropped.items()},
            f"{area}: unassignment notices differ from the revision {sent['ticket_unassigned']}",
        )
        check(
            set(sent["ticket_rescheduled"]) == set(rescheduled),
            f"{area}: reschedule notices differ from the revision diff",
        )
        for ticket_id, items in sent["ticket_rescheduled"].items():
            check(
                len(items) == 1
                and moment(items[0]["data"]["to"]) == moment(rescheduled[ticket_id])
                and items[0]["data"]["day_revision"] == after["revision"],
                f"ticket {ticket_id}: reschedule notice does not match revision",
            )
        for ticket_id, items in sent["ticket_unassigned"].items():
            if ticket_id not in added:
                check(
                    items[0]["data"].get("day_revision") == after["revision"],
                    f"ticket {ticket_id}: unassignment notice without its revision",
                )
        return {
            "revision": after["revision"],
            "added": sorted(added),
            "dropped": sorted(dropped),
            "rescheduled_notices": sorted(rescheduled),
        }

    def check_frozen(self, before: dict, after: dict, frozen: dict) -> None:
        """Visits of the current stage keep worker, order and times in the new revision."""
        old = {visit["ticket_id"]: visit for visit in before["visits"]}
        new = {visit["ticket_id"]: visit for visit in after["visits"]}
        for ticket_id, state in frozen.items():
            check(ticket_id in new, f"frozen ticket {ticket_id} left the plan")
            for field in ("worker_id", "sequence", "service_start_at", "service_end_at"):
                check(
                    new[ticket_id][field] == old[ticket_id][field],
                    f"frozen ticket {ticket_id} changed {field}",
                )
            check(self.lifecycle(ticket_id) == state, f"frozen ticket {ticket_id} left {state}")


PROFILES_SQL = """
SELECT w.user_id AS id, w.transport_type::text AS transport_type,
       w.workshift_start, w.workshift_end, w.service_area_id,
       m.brigade_id, b.office_id,
       COALESCE(array_agg(s.skill_id) FILTER (WHERE s.skill_id IS NOT NULL), '{}') AS skills
FROM workers AS w
LEFT JOIN brigade_members AS m ON m.worker_id = w.user_id
LEFT JOIN brigades AS b ON b.id = m.brigade_id
LEFT JOIN worker_skill_assignments AS s ON s.worker_id = w.user_id
GROUP BY w.user_id, m.brigade_id, b.office_id
"""

WORK_TYPES_SQL = """
SELECT t.id, t.category::text AS category,
       COALESCE(
           (SELECT array_agg(skill_id) FROM work_type_required_skills WHERE work_type_id = t.id),
           '{}'
       ) AS skills,
       COALESCE(
           (SELECT jsonb_object_agg(appliance_id, quantity)
            FROM work_type_required_appliances WHERE work_type_id = t.id),
           '{}'
       ) AS appliances
FROM work_types AS t
WHERE t.id = ANY(:ids)
"""


def s19_explicit_outside_roster(run: Run, roles: dict) -> None:
    """Neither event flow nor the replan accepts a caller-selected engineer."""
    area = roles["area_b"]
    current = run.day(area)
    new = [
        (run.ids["tickets"][str(item["ticket_id"])], item["category"])
        for item in SCENARIOS["tickets"]
        if item["phase"] == "new" and run.ids["service_areas"][str(item["service_area_id"])] == area
    ]
    emergency = next(ticket for ticket, kind in new if kind == "emergency")
    regular = next(ticket for ticket, kind in new if kind != "emergency")
    for ticket_id in (regular, emergency):
        body = run.preview(
            area,
            ticket_id,
            current["revision"],
            now="12:45",
            expected=422,
            worker_ids=[run.outsider],
        )
        check(body["detail"][0]["type"] == "extra_forbidden", f"{ticket_id}: worker list taken")
    run.call(
        "POST",
        f"/api/v1/planning/areas/{area}/{DAY}/replan/preview",
        422,
        now="12:45",
        json={"base_day_revision": current["revision"], "worker_ids": [run.outsider]},
    )
    refused = run.call(
        "POST",
        "/api/v1/planning/preview",
        422,
        now="12:45",
        json={
            "route_date": DAY,
            "service_area_id": area,
            "base_day_revision": current["revision"],
            "ticket_ids": [emergency],
            "worker_ids": [run.outsider],
            "replan": True,
        },
    )
    check(refused["detail"]["code"] == "replan_endpoint_required", "replan bypass accepted")
    check(run.day(area) == current, "refused attempts changed the published day")
    run.step(
        id="s19_explicit_outside_roster",
        outsider=run.outsider,
        refused=["ticket_event_regular", "ticket_event_emergency", "replan", "solve_as_replan"],
        revision=current["revision"],
    )


def s09_source_marker(run: Run, roles: dict) -> None:
    """Only the HelpDesk source marker selects the emergency branch."""
    area, brigade = roles["area_c"], roles["brigade_c"]
    first = min(moment(visit["service_start_at"]) for visit in run.day(area)["visits"])
    now, received = first - minutes(30), first - minutes(35)
    window = (first + minutes(60), first + minutes(360))
    text_fields = {
        "title": "Авария: у клиента нет связи",
        "description": "Клиент пишет «авария, срочно», просит приехать как можно быстрее",
    }
    cases = {
        "hd_emergency_regular_type": (roles["regular"], {"request_type_hd": "Авария"}, True),
        "hd_emergency_emergency_type": (roles["emergency"], {"request_type_hd": "Авария"}, True),
        "hd_repair_emergency_type_priority_1": (
            roles["emergency"],
            {"request_type_hd": "Ремонт", "priority": 1},
            False,
        ),
        "no_hd_emergency_type_priority_1": (roles["emergency"], {"priority": 1}, False),
        "no_hd_regular_type_priority_1": (roles["regular"], {"priority": 1}, False),
    }
    for hd, category in (("Ремонт", "emergency"), ("Авария", "repair")):
        body = run.ticket_body(
            area=area,
            work_type=roles["emergency"],
            received=received,
            window=window,
            request_type_hd=hd,
            category=category,
            **text_fields,
        )
        refused = run.call("POST", "/api/v1/tickets", 422, json=body)
        check("category_classification_conflict" in str(refused), "category override accepted")
    revision = run.day(area)["revision"]
    results = {}
    for name, (work_type, fields, emergency) in cases.items():
        ticket_id = run.create_ticket(
            area=area,
            brigade=brigade,
            work_type=work_type,
            received=received,
            window=window,
            **fields,
            **text_fields,
        )
        ticket = run.ticket(ticket_id)
        logged = run.scalar(
            "SELECT payload->>'category' FROM work_events "
            "WHERE ticket_id=:id AND event_type='new_ticket'",
            id=ticket_id,
        )
        check((ticket["category"] == "emergency") == emergency, f"{name}: category")
        check(logged == ticket["category"], f"{name}: new_ticket event has another category")
        check(
            (ticket["response_deadline_at"] is not None) == emergency,
            f"{name}: reaction deadline",
        )
        event = run.preview(area, ticket_id, revision, now=now)["event"]
        check(event["category"] == ticket["category"], f"{name}: category changed in preview")
        if emergency:
            check(event["outcome"] in EMERGENCY_OUTCOMES, f"{name}: skipped the emergency branch")
            check(event["sla_forecast"] is not None, f"{name}: no reaction forecast")
        else:
            check(ticket["priority"] == fields.get("priority", ticket["priority"]), name)
            check(event["outcome"] in REGULAR_OUTCOMES, f"{name}: took the emergency branch")
            check(event["sla_forecast"] is None, f"{name}: emergency forecast")
        results[name] = {"category": ticket["category"], "outcome": event["outcome"]}
    check(run.day(area)["revision"] == revision, "previews published a revision")
    run.step(id="s09_source_marker", tickets=results, refused_overrides=2)


def s04_constraints(run: Run, roles: dict) -> list[dict]:
    """Skill, transport, equipment and shift refuse a candidate the same way on every path."""
    area, brigade, pair = roles["area_c"], roles["brigade_c"], roles["pair"]
    regular, other = roles["regular"], roles["other_brigade"]
    start = min(local(run.profiles[worker]["workshift_start"]) for worker in run.roster[area])
    now = start - minutes(30)
    window = (start + minutes(120), start + minutes(420))
    skill_type = next(
        (wt for wt in run.work_types if not any(run.qualified(worker, wt) for worker in pair)),
        None,
    )
    check(skill_type, "fixture: every work type fits the brigade")
    transport = next(
        (
            kind
            for kind in TRANSPORTS
            if kind not in {run.profiles[w]["transport_type"] for w in pair}
        ),
        None,
    )
    check(transport, "fixture: the brigade uses every transport")
    check(run.work_types[regular]["appliances"], "fixture: the regular work type needs no kit")
    foreign_office = next(office for owner, office in run.offices.items() if owner != area)
    other_workers = [w for w in run.roster[area] if run.profiles[w]["brigade_id"] == other]
    other_end = max(local(run.profiles[w]["workshift_end"]) for w in other_workers)
    cases = [
        {"name": "skill", "work_type": skill_type, "codes": {"missing_skill"}},
        {
            "name": "transport",
            "work_type": regular,
            "fields": {"required_transport_type": transport},
            "codes": {"required_transport_mismatch"},
        },
        {
            "name": "equipment_office",
            "work_type": regular,
            "office": foreign_office,
            "codes": {"office_mismatch"},
        },
        {
            "name": "equipment_not_reserved",
            "work_type": regular,
            "office": False,
            "codes": {"equipment_not_reserved"},
        },
        {
            "name": "shift",
            "work_type": regular,
            "brigade": other,
            "workers": other_workers,
            "window": (other_end + minutes(60), other_end + minutes(150)),
            "codes": SHIFT_CODES,
        },
    ]
    revision = run.day(area)["revision"]
    for case in cases:
        case.setdefault("brigade", brigade)
        case.setdefault("workers", pair)
        case.setdefault("window", window)
        ticket_id = run.create_ticket(
            area=area,
            brigade=case["brigade"],
            work_type=case["work_type"],
            received=now - minutes(10),
            window=case["window"],
            office=case.get("office"),
            request_type_hd="Ремонт",
            title=f"[Приёмка S04] {case['name']}",
            **case.get("fields", {}),
        )
        case["ticket_id"] = ticket_id
        event = run.preview(area, ticket_id, revision, now=now)["event"]
        check(event["outcome"] == "not_insertable", f"{case['name']}: solve assigned it")
        codes = _candidate_codes(event)
        solve = {w: _refusal(codes, event["reason"], w) for w in case["workers"]}
        check(set(solve.values()) <= case["codes"], f"{case['name']}: solve reasons {solve}")
        check(
            all(item["reason"].get("message") for item in event["candidate_reasons"]),
            f"{case['name']}: a reason without its explanation",
        )
        manual = {}
        for worker in case["workers"]:
            preview = run.call(
                "POST",
                f"/api/v1/tickets/{ticket_id}/assign/preview",
                200,
                now=now,
                json={"worker_id": worker},
            )
            check(
                not preview["is_eligible"]
                and case["codes"] & {item["code"] for item in preview["violations"]},
                f"{case['name']}: manual preview {preview}",
            )
            refused = run.call(
                "PUT",
                f"/api/v1/tickets/{ticket_id}/assignees",
                422,
                now=now,
                json={"worker_id": worker, "is_pinned": False},
            )["detail"]
            manual[worker] = [item["code"] for item in refused.get("violations", [])]
            check(case["codes"] & set(manual[worker]), f"{case['name']}: manual {refused}")
        check(run.ticket(ticket_id)["assigned_worker_id"] is None, "manual path saved it")
        case["solve"], case["manual"] = solve, manual
    # The native solver sees the same rules for the whole remainder of the day.
    plan = run.replan(area, revision, now=now)
    routed = {stop["ticket_id"] for route in plan["routes"] for stop in route["stops"]}
    unassigned = {item["ticket_id"]: item for item in plan["unassigned"]}
    for case in cases:
        item = unassigned.get(case["ticket_id"])
        check(item and case["ticket_id"] not in routed, f"{case['name']}: solver routed it")
        codes = {c["worker_id"]: c["reason"]["code"] for c in item.get("candidates", [])}
        solver = {w: _refusal(codes, item["reason"]["code"], w) for w in case["workers"]}
        check(set(solver.values()) <= case["codes"], f"{case['name']}: solver {solver}")
        case["solver"] = solver
    check(run.day(area)["revision"] == revision, "constraint checks published a revision")
    return cases


def s04_import(run: Run, cases: list[dict]) -> None:
    """The exchange import refuses an active assignment that breaks the same rules."""
    template = next(row for row in run.package["tickets"] if row["assigned_worker_id"])
    allocation = run.package["ticket_appliances"][0]
    tickets_before = run.scalar("SELECT count(*) FROM tickets")
    imports_before = run.scalar("SELECT count(*) FROM data_imports")
    results = {}
    for index, case in enumerate(cases):
        stored = run.ticket(case["ticket_id"])
        row = {
            **template,
            "id": 900 + index,
            "location_id": stored["location_id"],
            "service_area_id": stored["service_area_id"],
            "brigade_id": stored["brigade_id"],
            "work_type_id": stored["work_type_id"],
            "work_type": stored["work_type"],
            "category": stored["category"],
            "priority": stored["priority"],
            "request_type_hd": stored["request_type_hd"],
            "required_transport_type": stored["required_transport_type"],
            "title": f"[Приёмка S04 импорт] {case['name']}",
            "status": "planned",
            "lifecycle_state": "assigned",
            "assigned_worker_id": case["workers"][0],
            "received_at": moment(stored["received_at"]),
            "visit_window_start": moment(stored["visit_window_start"]),
            "visit_window_end": moment(stored["visit_window_end"]),
            "planned_start_at": None,
            "planned_end_at": None,
        }
        office = case.get("office")
        package = {"tickets": [row]}
        if office is not False:
            package["ticket_appliances"] = [
                {
                    **allocation,
                    "ticket_id": row["id"],
                    "appliance_id": int(appliance),
                    "office_id": office or run.offices[stored["service_area_id"]],
                    "quantity": quantity,
                }
                for appliance, quantity in run.work_types[stored["work_type_id"]][
                    "appliances"
                ].items()
            ]
        refused = run.call(
            "POST",
            "/api/v1/data/import",
            422,
            params={"dry_run": "false"},
            files={"file": ("s04.zip", serialize(package, "csv"), "application/zip")},
        )["detail"]
        check(refused.get("code") == "assignment_rejected", f"{case['name']}: import {refused}")
        codes = {item["reason"]["code"] for item in refused.get("violations", [])}
        check(codes and codes <= case["codes"], f"{case['name']}: import reasons {codes}")
        results[case["name"]] = sorted(codes)
    check(run.scalar("SELECT count(*) FROM tickets") == tickets_before, "import saved tickets")
    check(run.scalar("SELECT count(*) FROM data_imports") == imports_before, "import recorded")
    run.step(
        id="s04_constraints",
        cases={
            case["name"]: {
                "codes": sorted(case["codes"]),
                "solve": case["solve"],
                "solver": case["solver"],
                "manual": case["manual"],
                "import": results[case["name"]],
            }
            for case in cases
        },
    )


def s08_regular_during_active_stage(run: Run, roles: dict) -> dict:
    """A new ordinary ticket goes after the current stage or stays unassigned."""
    area, brigade, (travelling, working) = roles["area_c"], roles["brigade_c"], roles["pair"]
    first, second = run.first_open_visit(area, travelling), run.first_open_visit(area, working)
    en_route, in_progress = first["ticket_id"], second["ticket_id"]
    length = {
        visit["ticket_id"]: moment(visit["service_end_at"]) - moment(visit["service_start_at"])
        for visit in (first, second)
    }
    check(min(length.values()) >= minutes(20), "fixture: the current stages are too short")
    departed = moment(first["service_start_at"]) + minutes(5)
    started = moment(second["service_start_at"]) + minutes(5)
    now = max(departed, started) + minutes(7)
    run.advance(area, now, keep={en_route, in_progress})
    revision = run.ticket(en_route)["revision"]
    key = run.event_key("start-route", en_route, revision)
    moved = run.execute(en_route, "start-route", departed)
    events = run.scalar("SELECT count(*) FROM work_events WHERE ticket_id=:id", id=en_route)
    # S16: a retry with the same key is one logical result, even with a new timestamp;
    # the same key with other content is refused.
    replay = run.call(
        "POST",
        f"/api/v1/tickets/{en_route}/start-route",
        200,
        now=departed + minutes(1),
        headers={"Idempotency-Key": key},
        json={"expected_revision": revision, "occurred_at": at(departed + minutes(1))},
    )
    check(replay["revision"] == moved["revision"], "S16: event replay moved the ticket")
    conflict = run.call(
        "POST",
        f"/api/v1/tickets/{en_route}/start-route",
        409,
        now=departed + minutes(1),
        headers={"Idempotency-Key": key},
        json={
            "expected_revision": revision,
            "occurred_at": at(departed),
            "reason": "Другое событие с тем же ключом",
        },
    )["detail"]
    check(conflict["code"] == "idempotency_conflict", f"S16: reused key {conflict}")
    check(
        run.scalar("SELECT count(*) FROM work_events WHERE ticket_id=:id", id=en_route) == events,
        "S16: event replay stored a second event",
    )
    run.execute(in_progress, "start-route", moment(second["service_start_at"]))
    run.execute(in_progress, "start", started)
    states = {worker: run.day_state(worker) for worker in (travelling, working)}
    frozen = {en_route: "en_route", in_progress: "in_progress"}
    earliest = {en_route: departed + length[en_route], in_progress: started + length[in_progress]}
    before = run.day(area)
    since = run.last_notification()
    fits = run.create_ticket(
        area=area,
        brigade=brigade,
        work_type=roles["regular"],
        received=now - minutes(2),
        window=(now - minutes(2), now + minutes(200)),
        request_type_hd="Ремонт",
        title="[Приёмка S08] обычная заявка во время активного этапа",
    )
    preview = run.preview(area, fits, before["revision"], now=now)
    event = preview["event"]
    check(event["outcome"] == "insertion_ready", f"S08: no slot after the current stage {event}")
    check(
        {visit["ticket_id"] for visit in event["preserved_current_stage"]} >= set(frozen),
        "S08: current stage not reported",
    )
    slot = event["selected_slot"]
    stage = next(
        visit
        for visit in before["visits"]
        if visit["ticket_id"] in frozen and visit["worker_id"] == slot["worker_id"]
    )
    check(slot["sequence"] > stage["sequence"], "S08: inserted before the current stage")
    check(
        moment(slot["arrival_at"]) >= earliest[stage["ticket_id"]],
        f"S08: new stop overlaps the current stage ({slot['arrival_at']})",
    )
    applied = run.apply(preview["plan"]["plan_id"], now=now)
    after = run.day(area)
    run.check_frozen(before, after, frozen)
    old = {visit["ticket_id"]: visit for visit in before["visits"]}
    for visit in after["visits"]:
        if visit["ticket_id"] in old:
            for field in ("worker_id", "service_start_at"):
                check(visit[field] == old[visit["ticket_id"]][field], "S08: old visit moved")
    for worker, state in states.items():
        current = run.day_state(worker)
        check(
            (current["current_ticket_id"], current["current_destination_id"])
            == (state["current_ticket_id"], state["current_destination_id"]),
            f"S08: worker {worker} current stage changed",
        )
    published = run.check_published(area, before, after, since, event=event)
    blocked = run.create_ticket(
        area=area,
        brigade=brigade,
        work_type=roles["regular"],
        received=now,
        window=(now, now + SERVICE + minutes(8)),
        request_type_hd="Ремонт",
        title="[Приёмка S08] обычная заявка только до конца текущего этапа",
    )
    refused = run.preview(area, blocked, after["revision"], now=now)
    check(
        refused["event"]["outcome"] == "not_insertable" and refused["plan"] is None,
        f"S08: slot inside the current stage {refused['event']}",
    )
    # The window fits the service; only the current stages of both candidates block it.
    check(
        {travelling, working} <= set(_candidate_codes(refused["event"])),
        f"S08: refusal does not name the candidates {refused['event']['candidate_reasons']}",
    )
    check(run.day(area) == after, "S08: refused ticket changed the day")
    check(
        run.ticket(blocked)["assigned_worker_id"] is None
        and run.lifecycle(blocked) == "waiting_assignment",
        "S08: refused ticket got an engineer",
    )
    run.step(
        id="s08_regular_during_active_stage",
        frozen=frozen,
        inserted_ticket=fits,
        slot=slot,
        applied_revision=applied.get("day_revision"),
        published=published,
        blocked_ticket=blocked,
        blocked_reasons=_candidate_codes(refused["event"]),
        event_key_conflict=conflict["code"],
    )
    return {
        "en_route": en_route,
        "in_progress": in_progress,
        "arrive": now + minutes(20),
        "length": length,
        "started": started,
    }


def _concurrent(run: Run, plan_ids: list, now) -> list:
    """Apply plans at the same moment from separate connections."""
    results = [None] * len(plan_ids)
    barrier = threading.Barrier(len(plan_ids))
    headers = dict(run.client.headers)

    def apply(index, plan_id):
        with httpx.Client(base_url=run.base_url, headers=headers, timeout=60) as client:
            barrier.wait()
            results[index] = run.apply(plan_id, now=now, expected=(200, 409), client=client)

    threads = [
        threading.Thread(target=apply, args=(index, plan_id))
        for index, plan_id in enumerate(plan_ids)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def s16_repeated_and_concurrent(run: Run, roles: dict, stage: dict):
    """A repeated arrival, competing and stale applies publish one logical result."""
    area, brigade = roles["area_c"], roles["brigade_c"]
    run.execute(stage["en_route"], "start", stage["arrive"])
    run.execute(
        stage["en_route"],
        "complete",
        stage["arrive"] + stage["length"][stage["en_route"]],
        note="Работа выполнена",
    )
    run.execute(
        stage["in_progress"],
        "complete",
        stage["started"] + stage["length"][stage["in_progress"]],
        note="Работа выполнена",
    )
    now = stage["arrive"] + max(stage["length"].values()) + minutes(2)
    run.advance(area, now)
    body = run.ticket_body(
        area=area,
        work_type=roles["regular"],
        received=now,
        window=(now, now + minutes(200)),
        request_type_hd="Ремонт",
        title="[Приёмка S16] повторное поступление",
    )
    key = {"Idempotency-Key": "acceptance-s16-arrival"}
    tickets_before = run.scalar("SELECT count(*) FROM tickets")
    first = run.call("POST", "/api/v1/tickets", 201, now=now, json=body, headers=key)
    again = run.call("POST", "/api/v1/tickets", 201, now=now, json=body, headers=key)
    conflict = run.call(
        "POST",
        "/api/v1/tickets",
        409,
        now=now,
        json={**body, "title": "[Приёмка S16] другое тело с тем же ключом"},
        headers=key,
    )["detail"]
    ticket_id = first["id"]
    check(again["id"] == ticket_id, "S16: repeated arrival created another ticket")
    check(conflict["code"] == "idempotency_conflict", f"S16: reused key {conflict}")
    check(run.scalar("SELECT count(*) FROM tickets") == tickets_before + 1, "S16: duplicate")
    check(
        run.scalar(
            "SELECT count(*) FROM work_events WHERE ticket_id=:id AND event_type='new_ticket'",
            id=ticket_id,
        )
        == 1,
        "S16: repeated arrival stored a second event",
    )
    run.settle(ticket_id, area=area, brigade=brigade, work_type=roles["regular"])
    before = run.day(area)
    since = run.last_notification()
    plans = [
        run.preview(area, ticket_id, before["revision"], now=now)["plan"]["plan_id"]
        for _ in range(2)
    ]
    results = _concurrent(run, plans, now)
    statuses = sorted(status for status, _ in results)
    check(statuses == [200, 409], f"S16: competing applies {results}")
    winner = plans[[status for status, _ in results].index(200)]
    loser = plans[[status for status, _ in results].index(409)]
    losing_code = next(body["detail"]["code"] for status, body in results if status == 409)
    check(losing_code in {"plan_stale", "day_revision_stale"}, f"S16: {losing_code}")
    after = run.day(area)
    check(
        [visit["ticket_id"] for visit in after["visits"]].count(ticket_id) == 1,
        "S16: ticket published twice",
    )
    published = run.check_published(area, before, after, since)
    stale = run.apply(loser, now=now, expected=409)
    check(stale["detail"]["code"] in {"plan_stale", "day_revision_stale"}, "S16: stale apply")
    check(run.apply(winner, now=now)["already_applied"], "S16: winner replay")
    check(run.day(area) == after, "S16: stale or repeated apply changed the day")

    later = now + minutes(50)
    run.advance(area, later)
    second = run.create_ticket(
        area=area,
        brigade=brigade,
        work_type=roles["regular"],
        received=later,
        window=(later, later + minutes(200)),
        request_type_hd="Ремонт",
        title="[Приёмка S16] устаревание после события исполнения",
    )
    current = run.day(area)
    outdated = run.preview(area, second, current["revision"], now=later)["plan"]["plan_id"]
    future = next(
        visit
        for visit in sorted(current["visits"], key=lambda visit: visit["service_start_at"])
        if moment(visit["service_start_at"]) > later + minutes(60)
        and run.lifecycle(visit["ticket_id"]) == "assigned"
    )
    run.execute(future["ticket_id"], "dispatch", later)
    refused = run.apply(outdated, now=later, expected=409)["detail"]
    check(refused["code"] in {"plan_stale", "day_revision_stale"}, f"S16: {refused}")
    check(run.day(area) == current, "S16: stale apply after an event changed the day")
    since = run.last_notification()
    plan_id = run.preview(area, second, current["revision"], now=later)["plan"]["plan_id"]
    same = _concurrent(run, [plan_id, plan_id], later)
    check(all(status == 200 for status, _ in same), f"S16: same plan {same}")
    check(
        sorted(body["already_applied"] for _, body in same) == [False, True],
        f"S16: same plan applied twice {same}",
    )
    final = run.day(area)
    run.check_published(area, current, final, since)
    run.step(
        id="s16_repeated_and_concurrent",
        arrival={"ticket_id": ticket_id, "replayed": True, "conflict": conflict["code"]},
        competing={"statuses": statuses, "losing_code": losing_code},
        stale_after_event=refused["code"],
        repeated_plan=sorted(body["already_applied"] for _, body in same),
        published=published,
        final_revision=final["revision"],
    )
    return later


def _emergency_flow(run: Run, roles: dict, *, area, worker, name, offsets, during=None):
    """An emergency arrives during the current stage; it is routed only after completion."""
    visit = run.first_open_visit(area, worker)
    stage_ticket, stage_start = visit["ticket_id"], moment(visit["service_start_at"])
    clock = {key: stage_start + minutes(value) for key, value in offsets.items()}
    run.advance(area, clock["preview"], keep={stage_ticket})
    run.execute(stage_ticket, "start-route", clock["departed"])
    if "started_before" in clock:
        run.execute(stage_ticket, "start", clock["started_before"])
    stage_state = run.lifecycle(stage_ticket)
    emergency = run.create_ticket(
        area=area,
        brigade=run.profiles[worker]["brigade_id"],
        work_type=roles["emergency"],
        received=clock["received"],
        window=(clock["received"], clock["received"] + minutes(120)),
        request_type_hd="Авария",
        title=f"[Приёмка {name}] авария во время текущего этапа",
    )
    arrival = run.ticket(emergency)
    before = run.day(area)
    state_before = run.day_state(worker)
    waiting = run.preview(area, emergency, before["revision"], now=clock["preview"])
    event = waiting["event"]
    check(not event["can_apply"], f"{name}: route built during the current stage {event}")
    check(event["outcome"] == "waiting_safe_point", f"{name}: outcome {event['outcome']}")
    check(
        stage_ticket in {visit["ticket_id"] for visit in event["preserved_current_stage"]},
        f"{name}: current stage not preserved",
    )
    if waiting["plan"]:
        blocked = run.apply(waiting["plan"]["plan_id"], now=clock["preview"], expected=409)
        check(
            blocked["detail"]["code"] == "ticket_event_preview_not_applicable",
            f"{name}: waiting plan applied {blocked}",
        )
    redirect = None
    if stage_state == "en_route":
        redirect = run.call(
            "POST",
            f"/api/v1/planning/days/{area}/{DAY}/redirect",
            409,
            now=clock["preview"],
            headers={"Idempotency-Key": f"acceptance-redirect-{emergency}"},
            json={
                "worker_id": worker,
                "current_ticket_id": stage_ticket,
                "new_destination_id": run.location_of(emergency),
                "expected_day_revision": state_before["revision"],
                "reason": "Попытка развернуть бригаду к аварии",
            },
        )["detail"]
    state_after = run.day_state(worker)
    check(
        (state_after["current_ticket_id"], state_after["current_destination_id"])
        == (state_before["current_ticket_id"], state_before["current_destination_id"]),
        f"{name}: current leg changed",
    )
    check(run.day(area) == before, f"{name}: waiting preview changed the day")
    extra = during(clock["preview"]) if during else None
    if "started_after" in clock:
        run.execute(stage_ticket, "start", clock["started_after"])
        still = run.preview(area, emergency, before["revision"], now=clock["started_after"])
        check(still["event"]["outcome"] == "waiting_safe_point", f"{name}: in-progress routing")
    run.execute(stage_ticket, "complete", clock["completed"], note="Работа выполнена")
    run.advance(area, clock["after"])
    since = run.last_notification()
    before = run.day(area)
    ready = run.preview(area, emergency, before["revision"], now=clock["after"])
    event = ready["event"]
    check(event["can_apply"] and ready["plan"], f"{name}: no route after completion {event}")
    slot = event["selected_slot"]
    check(slot["worker_id"] == worker, f"{name}: served by {slot['worker_id']}")
    route = next(route for route in ready["plan"]["routes"] if route["worker_id"] == worker)
    check(moment(route["departure_at"]) >= clock["completed"], f"{name}: left before completion")
    check(
        route["start_location_id"] == run.location_of(stage_ticket),
        f"{name}: route does not start at the completed ticket",
    )
    forecast = event["sla_forecast"]
    check(moment(forecast["received_at"]) == clock["received"], f"{name}: SLA clock restarted")
    check(
        forecast["reaction_to_service_start_minutes"]
        == int((moment(slot["service_start_at"]) - clock["received"]).total_seconds() // 60),
        f"{name}: reaction not counted from receipt",
    )
    run.apply(ready["plan"]["plan_id"], now=clock["after"])
    after = run.day(area)
    published = run.check_published(area, before, after, since, event=event)
    run.check_frozen(before, after, {stage_ticket: "completed"})
    stored = run.ticket(emergency)
    check(
        (stored["received_at"], stored["response_deadline_at"])
        == (arrival["received_at"], arrival["response_deadline_at"]),
        f"{name}: receipt or reaction deadline changed",
    )
    run.step(
        id=name,
        stage_ticket=stage_ticket,
        stage_state_on_arrival=stage_state,
        emergency_ticket=emergency,
        waiting_outcome="waiting_safe_point",
        redirect=redirect,
        departure_at=route["departure_at"],
        forecast=forecast,
        published=published,
        during_stage=extra,
    )
    return {"emergency": emergency, "after": clock["after"], "revision": after["revision"]}


def s11_emergency_while_en_route(run: Run, roles: dict) -> dict:
    return _emergency_flow(
        run,
        roles,
        area=roles["area_a"],
        worker=roles["worker_a"],
        name="s11_emergency_while_en_route",
        offsets={
            "departed": 5,
            "received": 10,
            "preview": 12,
            "started_after": 15,
            "completed": 40,
            "after": 41,
        },
    )


def s12_emergency_while_in_progress(run: Run, roles: dict) -> None:
    """S12, and S19 for both flows: the idle qualified outsider is never taken."""
    area, worker = roles["area_b"], roles["worker_b"]
    run.write(
        "INSERT INTO worker_skill_assignments (worker_id, skill_id) "
        "SELECT :outsider, skill_id FROM worker_skill_assignments WHERE worker_id=:worker "
        "EXCEPT SELECT :outsider, skill_id FROM worker_skill_assignments WHERE worker_id=:outsider",
        outsider=run.outsider,
        worker=worker,
    )
    run.profiles[run.outsider]["skills"] = sorted(
        set(run.profiles[run.outsider]["skills"]) | set(run.profiles[worker]["skills"])
    )
    roster = run.day(area)["roster"]
    check(run.qualified(run.outsider, roles["emergency"]), "S19: outsider not qualified")

    def regular_with_idle_outsider(now):
        # Only the engineer on his current stage and the outsider are qualified; the
        # window closes before that stage can end.
        brigade = run.profiles[worker]["brigade_id"]
        mates = [
            other
            for other in run.roster[area]
            if other != worker
            and run.profiles[other]["brigade_id"] == brigade
            and run.qualified(other, roles["emergency"])
        ]
        ticket_id = run.create_ticket(
            area=area,
            brigade=brigade,
            work_type=roles["emergency"],
            received=now,
            window=(now, now + SERVICE + minutes(8)),
            request_type_hd="Ремонт",
            title="[Приёмка S19] обычная заявка, которую мог бы взять только работник вне состава",
        )
        current = run.day(area)
        event = run.preview(area, ticket_id, current["revision"], now=now)["event"]
        codes = _candidate_codes(event)
        check(run.outsider not in codes, "S19: outsider among the candidates")
        if not mates:
            check(event["outcome"] == "not_insertable", f"S19: regular flow {event}")
        elif event["selected_slot"]:
            check(event["selected_slot"]["worker_id"] != run.outsider, "S19: outsider chosen")
        check(worker in codes, f"S19: the busy engineer is not reported {codes}")
        check(run.day(area) == current, "S19: regular preview changed the day")
        return {"ticket_id": ticket_id, "outcome": event["outcome"], "reasons": codes}

    result = _emergency_flow(
        run,
        roles,
        area=area,
        worker=worker,
        name="s12_emergency_while_in_progress",
        offsets={
            "departed": 0,
            "started_before": 5,
            "received": 20,
            "preview": 22,
            "completed": 45,
            "after": 46,
        },
        during=regular_with_idle_outsider,
    )
    current = run.day(area)
    check(current["roster"] == roster, "S19: emergency changed the roster")
    check(
        run.outsider not in {visit["worker_id"] for visit in current["visits"]},
        "S19: emergency used the idle engineer outside the roster",
    )
    run.step(
        id="s19_flows_with_idle_outsider",
        outsider=run.outsider,
        emergency_ticket=result["emergency"],
        roster_unchanged=True,
    )


def s20_dropped_visit_and_failed_commit(run: Run, roles: dict, s11: dict) -> None:
    """A visit taken off a route is announced; a failed commit leaves nothing behind."""
    area, worker = roles["area_a"], roles["worker_a"]
    brigade = run.profiles[worker]["brigade_id"]
    qualified = [
        other
        for other in run.roster[area]
        if run.profiles[other]["brigade_id"] == brigade and run.qualified(other, roles["emergency"])
    ]
    check(qualified == [worker], f"fixture: the emergency must have one engineer {qualified}")
    transport = run.profiles[worker]["transport_type"]
    check(
        not any(
            run.profiles[other]["transport_type"] == transport
            for other in run.roster[area]
            if other != worker and run.profiles[other]["brigade_id"] == brigade
        ),
        "fixture: the engineer's transport must single him out in his brigade",
    )
    # A moment when the engineer is between visits: the manual path needs him free.
    now = s11["after"] + minutes(5)
    for visit in sorted(
        (visit for visit in run.day(area)["visits"] if visit["worker_id"] == worker),
        key=lambda visit: visit["service_start_at"],
    ):
        if moment(visit["service_start_at"]) < now < moment(visit["service_end_at"]) + minutes(5):
            now = moment(visit["service_end_at"]) + minutes(5)
    run.advance(area, now)
    # The displacement needs a free stretch of his route: the tight visit and the
    # emergency compete for the same 100 minutes and nothing else is there.
    gap = now
    for visit in sorted(
        (visit for visit in run.day(area)["visits"] if visit["worker_id"] == worker),
        key=lambda visit: visit["service_start_at"],
    ):
        if (
            moment(visit["service_start_at"]) < gap + minutes(110)
            and moment(visit["service_end_at"]) > gap
        ):
            gap = moment(visit["service_end_at"]) + minutes(5)
    since = run.last_notification()
    before = run.day(area)
    tight = run.create_ticket(
        area=area,
        brigade=brigade,
        work_type=roles["regular"],
        received=now,
        window=(gap + minutes(50), gap + minutes(50) + SERVICE + minutes(5)),
        request_type_hd="Ремонт",
        required_transport_type=transport,
        title="[Приёмка S20] заявка с узким окном",
    )
    inserted = run.preview(area, tight, before["revision"], now=now)
    check(
        inserted["event"]["selected_slot"]
        and inserted["event"]["selected_slot"]["worker_id"] == worker,
        f"S20: tight visit not on the engineer {inserted['event']}",
    )
    run.apply(inserted["plan"]["plan_id"], now=now)
    manual = run.day(area)
    run.check_published(area, before, manual, since, event=inserted["event"])
    since = run.last_notification()
    emergency = run.create_ticket(
        area=area,
        brigade=brigade,
        work_type=roles["emergency"],
        received=now,
        window=(gap + minutes(45), gap + minutes(45) + SERVICE + minutes(15)),
        request_type_hd="Авария",
        title="[Приёмка S20] авария, вытесняющая заявку",
    )
    preview = run.preview(area, emergency, manual["revision"], now=now)
    event = preview["event"]
    check(event["can_apply"], f"S20: emergency cannot be applied {event}")
    run.apply(preview["plan"]["plan_id"], now=now)
    after = run.day(area)
    published = run.check_published(area, manual, after, since, event=event)
    check(tight in published["dropped"], "S20: the displaced visit stayed on the route")
    check(
        run.ticket(tight)["assigned_worker_id"] is None
        and run.lifecycle(tight) == "waiting_assignment",
        "S20: the displaced ticket kept its engineer",
    )

    since = run.last_notification()
    ticket_id = run.create_ticket(
        area=area,
        brigade=brigade,
        work_type=roles["regular"],
        received=now,
        window=(now + minutes(120), now + minutes(300)),
        request_type_hd="Ремонт",
        title="[Приёмка S20] apply, который падает при фиксации",
    )
    preview = run.preview(area, ticket_id, after["revision"], now=now)
    check(preview["plan"], f"S20: no plan to fail {preview['event']}")
    plan_id = preview["plan"]["plan_id"]
    routes = run.scalar("SELECT count(*) FROM routes")
    events = run.scalar("SELECT count(*) FROM work_events")
    run.write(
        "CREATE FUNCTION acceptance_fail_commit() RETURNS trigger LANGUAGE plpgsql AS "
        "$$ BEGIN RAISE EXCEPTION 'acceptance: forced failure before commit'; END $$"
    )
    run.write(
        "CREATE TRIGGER acceptance_fail_commit BEFORE UPDATE ON planning_plans FOR EACH ROW "
        "WHEN (NEW.state = 'applied' AND OLD.state IS DISTINCT FROM 'applied') "
        "EXECUTE FUNCTION acceptance_fail_commit()"
    )
    try:
        status, _ = run.apply(plan_id, now=now, expected=(500, 503))
    finally:
        run.write("DROP TRIGGER acceptance_fail_commit ON planning_plans")
        run.write("DROP FUNCTION acceptance_fail_commit()")
    check(run.day(area) == after, "S20: failed apply published a revision")
    check(
        run.ticket(ticket_id)["assigned_worker_id"] is None
        and run.lifecycle(ticket_id) == "waiting_assignment",
        "S20: failed apply kept the assignment",
    )
    check(run.scalar("SELECT count(*) FROM routes") == routes, "S20: failed apply kept routes")
    check(run.scalar("SELECT count(*) FROM work_events") == events, "S20: failed apply events")
    check(run.last_notification() == since, "S20: failed apply sent notices")
    check(
        run.scalar("SELECT state FROM planning_plans WHERE id=:id", id=plan_id) == "ready",
        "S20: failed apply changed the plan",
    )
    run.apply(plan_id, now=now)
    retried = run.day(area)
    run.check_published(area, after, retried, since, event=preview["event"])
    run.step(
        id="s20_dropped_visit_and_failed_commit",
        insertion_revision=manual["revision"],
        displaced_ticket=tight,
        emergency_revision=after["revision"],
        dropped=published["dropped"],
        failed_apply_status=status,
        retried_revision=retried["revision"],
    )


def s18_invalid_configuration(run: Run, roles: dict, now) -> None:
    """Contradicting area data is named and refused; nothing falls back or is kept."""
    area, other_area, worker = roles["area_c"], roles["area_a"], roles["pair"][0]
    brigade = roles["brigade_c"]
    profile_area = run.profiles[worker]["service_area_id"]
    before = run.day(area)
    since = run.last_notification()
    foreign = next(visit["ticket_id"] for visit in run.day(other_area)["visits"])
    mismatch = run.preview(area, foreign, before["revision"], now=now, expected=409)["detail"]
    check(mismatch["code"] == "ticket_service_area_mismatch", f"S18: other area {mismatch}")
    run.write(
        "UPDATE workers SET service_area_id=:area WHERE user_id=:id", area=other_area, id=worker
    )
    try:
        report = run.call("GET", "/api/v1/service-areas/consistency", 200)
        check(not report["consistent"], "S18: contradiction reported as consistent")
        issue = next((item for item in report["workers"] if item["subject_id"] == worker), None)
        check(issue is not None, f"S18: consistency report is silent {report}")
        check(
            {area, other_area} <= set(issue["sources"].values()),
            f"S18: issue does not name both areas {issue}",
        )
        ticket_id = run.create_ticket(
            area=area,
            brigade=brigade,
            work_type=roles["regular"],
            received=now,
            window=(now + minutes(10), now + minutes(250)),
            request_type_hd="Ремонт",
            title="[Приёмка S18] заявка при противоречивом участке инженера",
        )
        status, body = run.preview(
            area, ticket_id, before["revision"], now=now, expected=(201, 409)
        )
        if status == 409:
            # His published visits cannot stay with him, so nothing can be inserted around them.
            detail = body["detail"]
            check(
                detail["worker_id"] == worker and detail["worker_reason"]["code"] in AREA_CONFLICTS,
                f"S18: conflict without its cause {detail}",
            )
            solve = {"status": 409, "code": detail["code"], "cause": detail["worker_reason"]}
        else:
            codes = _candidate_codes(body["event"])
            check(
                body["event"]["outcome"] == "not_insertable"
                and codes.get(worker) in AREA_CONFLICTS,
                f"S18: reason {codes}",
            )
            solve = {"status": 201, "outcome": body["event"]["outcome"], "reason": codes[worker]}
        status, body = run.call(
            "POST",
            f"/api/v1/planning/areas/{area}/{DAY}/replan/preview",
            (201, 409),
            now=now,
            json={"base_day_revision": before["revision"]},
        )
        if status == 409:
            detail = body["detail"]
            check(
                detail.get("worker_id") == worker
                and detail["worker_reason"]["code"] in AREA_CONFLICTS,
                f"S18: solver conflict without its cause {detail}",
            )
            solver = {
                "status": 409,
                "code": detail["code"],
                "cause": detail["worker_reason"]["code"],
            }
        else:
            excluded = {item["worker_id"]: item["reason"] for item in body["excluded_workers"]}
            check(
                excluded.get(worker, {}).get("code") in AREA_CONFLICTS,
                f"S18: solver took the engineer {excluded.get(worker)}",
            )
            check(
                worker not in {route["worker_id"] for route in body["routes"]},
                "S18: solver routed the engineer",
            )
            solver = {"status": 201, "excluded": excluded[worker]["code"]}
        manual = run.call(
            "PUT",
            f"/api/v1/tickets/{ticket_id}/assignees",
            422,
            now=now,
            json={"worker_id": worker, "is_pinned": False},
        )["detail"]
        check(manual.get("code") in AREA_CONFLICTS, f"S18: manual {manual}")
        check(run.ticket(ticket_id)["assigned_worker_id"] is None, "S18: partial assignment")
        check(run.day(area) == before, "S18: invalid configuration published a revision")
        check(run.last_notification() == since, "S18: notifications without a result")
    finally:
        run.write(
            "UPDATE workers SET service_area_id=:area WHERE user_id=:id",
            area=profile_area,
            id=worker,
        )
    run.step(
        id="s18_invalid_configuration",
        other_area_ticket=mismatch["code"],
        worker=worker,
        issue=issue,
        solve=solve,
        solver=solver,
        manual=manual["code"],
    )


def run(client, base_url, engine, ids, package, report) -> None:
    runner = Run(client, base_url, engine, ids, package, report)
    roles = runner.roles()
    report["intraday_roles"] = roles
    s19_explicit_outside_roster(runner, roles)
    s09_source_marker(runner, roles)
    cases = s04_constraints(runner, roles)
    s04_import(runner, cases)
    stage = s08_regular_during_active_stage(runner, roles)
    later = s16_repeated_and_concurrent(runner, roles, stage)
    s11 = s11_emergency_while_en_route(runner, roles)
    s20_dropped_visit_and_failed_commit(runner, roles, s11)
    s12_emergency_while_in_progress(runner, roles)
    s18_invalid_configuration(runner, roles, later + minutes(10))

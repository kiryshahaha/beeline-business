"""The current day plan of a service area, its revision history and their differences.

A revision stores `plan_state`: the visits and metrics as published at that moment.
Nothing rewrites an earlier `plan_state`, so a historical revision keeps answering
with the geometry and promised times it was applied with, while the freshest one
answers for the area-day. Actual execution progress lives in the execution module
and is deliberately not merged into this promised timeline.
"""

from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.planning.day_models import DayPlanRevision
from app.modules.planning.errors import PlanningError
from app.modules.planning.models import PlanningPlan
from app.modules.users.models import Worker

# Numeric metrics whose change is worth showing next to a revision.
COMPARED_METRICS = (
    "assigned_tickets",
    "unassigned_tickets",
    "used_workers",
    "distance_meters",
    "travel_minutes",
    "service_minutes",
    "waiting_minutes",
)

VISIT_FIELDS = ("arrival_at", "service_start_at", "service_end_at")


def build_plan_state(public: dict, route_ids: dict[int, int] | None = None) -> dict:
    """Flatten a published plan into the visits and metrics a revision keeps forever."""
    route_ids = route_ids or {}
    visits = [
        {
            "ticket_id": stop["ticket_id"],
            "worker_id": route["worker_id"],
            "route_id": route_ids.get(route["worker_id"]),
            "sequence": stop["sequence"],
            "arrival_at": stop["arrival_at"],
            "service_start_at": stop["service_start_at"],
            "service_end_at": stop["service_end_at"],
        }
        for route in public.get("routes", [])
        for stop in route.get("stops", [])
        if stop.get("ticket_id") is not None
    ]
    return {
        "route_date": public.get("route_date"),
        "plan_id": public.get("plan_id"),
        "outcome": public.get("outcome"),
        "visits": sorted(visits, key=lambda visit: visit["ticket_id"]),
        "unassigned_ticket_ids": sorted(item["ticket_id"] for item in public.get("unassigned", [])),
        "metrics": public.get("metrics") or {},
        # Rules and objective breakdown the solver used; a manual edit has neither.
        "planning_policy": public.get("planning_policy"),
        "objective_components": public.get("objective_components"),
    }


def build_replan_state(
    public: dict,
    previous: dict | None,
    lifecycle_by_ticket: dict[int, str],
    route_ids: dict[int, int] | None = None,
) -> dict:
    """Replace the unstarted remainder while retaining execution already in motion."""
    state = build_plan_state(public, route_ids)
    visits = _visits_by_ticket(state)
    frozen_states = {"en_route", "in_progress", "completed"}
    for visit in (previous or {}).get("visits", []):
        ticket_id = visit["ticket_id"]
        if lifecycle_by_ticket.get(ticket_id) in frozen_states:
            visits[ticket_id] = visit

    offsets: dict[int, int] = {}
    for visit in visits.values():
        if lifecycle_by_ticket.get(visit["ticket_id"]) in frozen_states:
            worker_id = visit.get("worker_id")
            sequence = visit.get("sequence")
            if worker_id is not None and sequence is not None:
                offsets[worker_id] = max(offsets.get(worker_id, 0), sequence)
    for ticket_id, visit in list(visits.items()):
        if lifecycle_by_ticket.get(ticket_id) in frozen_states:
            continue
        worker_id = visit.get("worker_id")
        if worker_id is not None and visit.get("sequence") is not None:
            visits[ticket_id] = {**visit, "sequence": offsets.get(worker_id, 0) + visit["sequence"]}

    state["visits"] = sorted(visits.values(), key=lambda visit: visit["ticket_id"])
    state["metrics"] = {
        **(state.get("metrics") or {}),
        "assigned_tickets": len(state["visits"]),
        "unassigned_tickets": len(state.get("unassigned_ticket_ids", [])),
        "used_workers": len({visit["worker_id"] for visit in state["visits"]}),
        "metric_scope": "remaining_route_metrics_with_frozen_visits",
    }
    if not state["visits"] and not state["unassigned_ticket_ids"]:
        state["outcome"] = "empty"
    elif state["unassigned_ticket_ids"]:
        state["outcome"] = "partial"
    else:
        state["outcome"] = "complete"
    return state


def _visits_by_ticket(state: dict) -> dict[int, dict]:
    return {visit["ticket_id"]: visit for visit in (state or {}).get("visits", [])}


def _metric_changes(before: dict, after: dict) -> dict[str, dict]:
    old, new = (before or {}).get("metrics") or {}, (after or {}).get("metrics") or {}
    changes = {}
    metric_names = (
        ("assigned_tickets", "unassigned_tickets", "used_workers")
        if new.get("metric_scope") == "remaining_route_metrics_with_frozen_visits"
        else COMPARED_METRICS
    )
    for name in metric_names:
        was, now = old.get(name), new.get(name)
        if was is None and now is None:
            continue
        if was == now:
            continue
        delta = None
        if isinstance(was, int | float) and isinstance(now, int | float):
            delta = round(now - was, 3)
        changes[name] = {"from": was, "to": now, "delta": delta}
    return changes


def diff_states(before: dict | None, after: dict) -> dict:
    """What changed for the dispatcher: who, in which order, at what time."""
    old, new = _visits_by_ticket(before or {}), _visits_by_ticket(after)
    changed = []
    for ticket_id in sorted(set(old) & set(new)):
        was, now = old[ticket_id], new[ticket_id]
        fields = {}
        if was.get("worker_id") != now.get("worker_id"):
            fields["worker_id"] = {"from": was.get("worker_id"), "to": now.get("worker_id")}
        if was.get("sequence") != now.get("sequence"):
            fields["sequence"] = {"from": was.get("sequence"), "to": now.get("sequence")}
        for field in VISIT_FIELDS:
            if was.get(field) != now.get(field):
                fields[field] = {"from": was.get(field), "to": now.get(field)}
        if fields:
            changed.append({"ticket_id": ticket_id, "changes": fields})
    return {
        "added": [new[ticket_id] for ticket_id in sorted(set(new) - set(old))],
        "removed": [old[ticket_id] for ticket_id in sorted(set(old) - set(new))],
        "changed": changed,
        "unchanged_ticket_ids": sorted(
            ticket_id
            for ticket_id in set(old) & set(new)
            if ticket_id not in {item["ticket_id"] for item in changed}
        ),
        "metrics": _metric_changes(before or {}, after),
    }


def _clock(value) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else value.isoformat()


def roster_entry(
    worker_id: int,
    service_area_id: int,
    workshift_start=None,
    workshift_end=None,
    source: str = "published",
) -> dict:
    """One engineer admitted to the area-day with the shift they had at that moment."""
    return {
        "worker_id": worker_id,
        "service_area_id": service_area_id,
        "workshift_start": _clock(workshift_start),
        "workshift_end": _clock(workshift_end),
        "source": source,
    }


def roster_from_snapshot(snapshot: dict, service_area_id: int, source="published") -> list[dict]:
    """Everyone the dispatcher selected for a plan, not only engineers who got a visit."""
    rows = {row["user_id"]: row for row in snapshot.get("workers", [])}
    return [
        roster_entry(
            worker_id,
            service_area_id,
            rows.get(worker_id, {}).get("workshift_start"),
            rows.get(worker_id, {}).get("workshift_end"),
            source,
        )
        for worker_id in sorted(set(snapshot.get("request", {}).get("worker_ids", [])))
    ]


def roster_for_workers(
    session: Session, worker_ids: Iterable[int], service_area_id: int, source: str
) -> list[dict]:
    """Entries for engineers a dispatcher admits explicitly, with their current shift."""
    ids = sorted(set(worker_ids))
    if not ids:
        return []
    rows = session.execute(
        select(Worker.user_id, Worker.workshift_start, Worker.workshift_end)
        .where(Worker.user_id.in_(ids))
        .order_by(Worker.user_id)
    ).all()
    return [
        roster_entry(row.user_id, service_area_id, row.workshift_start, row.workshift_end, source)
        for row in rows
    ]


def roster_ids(roster: Iterable[dict] | None) -> list[int]:
    return sorted({entry["worker_id"] for entry in roster or []})


def merge_roster(base: list[dict] | None, additions: Iterable[dict]) -> list[dict]:
    """Admitted engineers keep their first entry; only explicit additions extend it."""
    entries = {entry["worker_id"]: entry for entry in base or []}
    for entry in additions:
        entries.setdefault(entry["worker_id"], entry)
    return [entries[worker_id] for worker_id in sorted(entries)]


def reconstruct_roster(
    session: Session, service_area_id: int, route_date: date
) -> list[dict] | None:
    """Rebuild a roster for revisions saved before it was recorded.

    Only immutable facts of this area-day count: the engineers selected in the planning
    snapshots its revisions were applied with and those who had a published visit. The
    other engineers of the area are never added. None when the history holds nothing.
    """
    entries: dict[int, dict] = {}
    revisions = session.scalars(
        select(DayPlanRevision)
        .where(
            DayPlanRevision.service_area_id == service_area_id,
            DayPlanRevision.route_date == route_date,
        )
        .order_by(DayPlanRevision.revision)
    ).all()
    for revision in revisions:
        if revision.roster is not None:
            entries = {entry["worker_id"]: entry for entry in revision.roster}
            continue
        plan = session.get(PlanningPlan, revision.plan_id) if revision.plan_id else None
        if plan is not None:
            for entry in roster_from_snapshot(
                plan.input_snapshot or {}, service_area_id, "reconstructed_from_snapshot"
            ):
                entries.setdefault(entry["worker_id"], entry)
        for visit in (revision.plan_state or {}).get("visits", []):
            worker_id = visit.get("worker_id")
            if worker_id is not None:
                entries.setdefault(
                    worker_id,
                    roster_entry(worker_id, service_area_id, source="reconstructed_from_visits"),
                )
    return [entries[worker_id] for worker_id in sorted(entries)] or None


def day_roster(session: Session, service_area_id: int, route_date: date) -> list[dict] | None:
    """The roster of the current revision, rebuilt from history for older revisions."""
    current = session.execute(
        select(DayPlanRevision.roster).where(
            DayPlanRevision.service_area_id == service_area_id,
            DayPlanRevision.route_date == route_date,
            DayPlanRevision.is_current.is_(True),
        )
    ).one_or_none()
    if current is None:
        return None
    if current.roster is not None:
        return current.roster
    return reconstruct_roster(session, service_area_id, route_date)


def roster_change(before: list[dict] | None, after: list[dict] | None) -> dict | None:
    old, new = set(roster_ids(before)), set(roster_ids(after))
    if old == new:
        return None
    return {"added": sorted(new - old), "removed": sorted(old - new)}


def current_revision(session: Session, service_area_id: int, route_date: date) -> int | None:
    return session.execute(
        select(DayPlanRevision.revision).where(
            DayPlanRevision.service_area_id == service_area_id,
            DayPlanRevision.route_date == route_date,
            DayPlanRevision.is_current.is_(True),
        )
    ).scalar_one_or_none()


def publish_revision(
    session: Session,
    *,
    service_area_id: int,
    route_date: date,
    actor_id: int,
    reason: str,
    fingerprint: str,
    plan_state: dict,
    result: dict,
    at: datetime,
    plan_id=None,
    event_id: int | None = None,
    roster_additions: Iterable[dict] = (),
) -> DayPlanRevision:
    """Append one revision and hand the `is_current` marker over atomically.

    The partial unique index lets exactly one revision of an area-day stay current,
    so two concurrent applies cannot both publish: the second waits on the row lock
    and then numbers itself after the first.

    The roster carries over unchanged. Only an explicit dispatcher action (a plan with
    selected engineers, a manual assignment) passes `roster_additions`; a replan never
    does, so new demand cannot bring in an engineer who was not admitted to the day.
    """
    previous = session.scalar(
        select(DayPlanRevision)
        .where(
            DayPlanRevision.service_area_id == service_area_id,
            DayPlanRevision.route_date == route_date,
            DayPlanRevision.is_current.is_(True),
        )
        .with_for_update()
    )
    previous_number = previous.revision if previous is not None else 0
    number = previous_number + 1
    previous_roster = None
    if previous is not None:
        previous_roster = (
            previous.roster
            if previous.roster is not None
            else reconstruct_roster(session, service_area_id, route_date)
        )
    additions = list(roster_additions)
    roster = (
        merge_roster(previous_roster, additions)
        if previous_roster is not None or additions
        else None
    )
    diff = diff_states(previous.plan_state if previous is not None else None, plan_state)
    change = roster_change(previous_roster, roster)
    if change is not None:
        diff["roster"] = change
    if previous is not None:
        previous.is_current = False
        previous.superseded_at = at
        previous.superseded_by_revision = number
        session.flush()
    revision = DayPlanRevision(
        service_area_id=service_area_id,
        route_date=route_date,
        revision=number,
        previous_revision=previous_number or None,
        plan_id=plan_id,
        event_id=event_id,
        actor_id=actor_id,
        reason=reason,
        fingerprint=fingerprint,
        plan_state=plan_state,
        diff=diff,
        result=result,
        roster=roster,
        is_current=True,
        effective_at=at,
    )
    session.add(revision)
    return revision


def _public(revision: DayPlanRevision) -> dict:
    return {
        "service_area_id": revision.service_area_id,
        "route_date": revision.route_date,
        "revision": revision.revision,
        "previous_revision": revision.previous_revision,
        "superseded_by_revision": revision.superseded_by_revision,
        "superseded_at": revision.superseded_at,
        "is_current": revision.is_current,
        "reason": revision.reason,
        "plan_id": revision.plan_id,
        "event_id": revision.event_id,
        "actor_id": revision.actor_id,
        "fingerprint": revision.fingerprint,
        "effective_at": revision.effective_at,
        "created_at": revision.created_at,
        "metrics": (revision.plan_state or {}).get("metrics") or {},
        "planning_policy": (revision.plan_state or {}).get("planning_policy"),
        "objective_components": (revision.plan_state or {}).get("objective_components"),
        "roster": revision.roster,
    }


def read_revisions(session: Session, service_area_id: int, route_date: date) -> list[dict]:
    rows = session.scalars(
        select(DayPlanRevision)
        .where(
            DayPlanRevision.service_area_id == service_area_id,
            DayPlanRevision.route_date == route_date,
        )
        .order_by(DayPlanRevision.revision)
    ).all()
    return [_public(row) for row in rows]


def _load(session: Session, service_area_id: int, route_date: date, number: int | None):
    condition = (
        DayPlanRevision.is_current.is_(True)
        if number is None
        else DayPlanRevision.revision == number
    )
    return session.scalar(
        select(DayPlanRevision).where(
            DayPlanRevision.service_area_id == service_area_id,
            DayPlanRevision.route_date == route_date,
            condition,
        )
    )


def read_revision(
    session: Session, service_area_id: int, route_date: date, number: int | None = None
) -> dict:
    revision = _load(session, service_area_id, route_date, number)
    if revision is None:
        raise PlanningError("day_plan_not_found", 404)
    state = revision.plan_state or {}
    return {
        **_public(revision),
        "visits": state.get("visits", []),
        "unassigned_ticket_ids": state.get("unassigned_ticket_ids", []),
        "diff": revision.diff,
    }


def read_diff(
    session: Session,
    service_area_id: int,
    route_date: date,
    *,
    base: int | None,
    target: int | None,
) -> dict:
    """Compare two published revisions, or a revision with the one it replaced."""
    to_revision = _load(session, service_area_id, route_date, target)
    if to_revision is None:
        raise PlanningError("day_plan_not_found", 404)
    if base is None:
        from_revision = (
            _load(session, service_area_id, route_date, to_revision.previous_revision)
            if to_revision.previous_revision is not None
            else None
        )
    else:
        from_revision = _load(session, service_area_id, route_date, base)
        if from_revision is None:
            raise PlanningError("day_plan_not_found", 404)
    if from_revision is not None and from_revision.revision > to_revision.revision:
        raise PlanningError("revision_order_invalid", 422)
    before = from_revision.roster if from_revision is not None else None
    comparable = to_revision.roster is not None and (
        from_revision is None or from_revision.roster is not None
    )
    roster = roster_change(before, to_revision.roster) if comparable else None
    return {
        "roster": roster,
        "service_area_id": service_area_id,
        "route_date": route_date,
        "from_revision": from_revision.revision if from_revision is not None else None,
        "to_revision": to_revision.revision,
        "reason": to_revision.reason,
        "is_current": to_revision.is_current,
        **diff_states(
            from_revision.plan_state if from_revision is not None else None,
            to_revision.plan_state,
        ),
    }

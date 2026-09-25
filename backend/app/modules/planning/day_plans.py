"""The current day plan of a service area, its revision history and their differences.

A revision stores `plan_state`: the visits and metrics as published at that moment.
Nothing rewrites an earlier `plan_state`, so a historical revision keeps answering
with the geometry and promised times it was applied with, while the freshest one
answers for the area-day. Actual execution progress lives in the execution module
and is deliberately not merged into this promised timeline.
"""

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.planning.day_models import DayPlanRevision
from app.modules.planning.errors import PlanningError

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
    }


def _visits_by_ticket(state: dict) -> dict[int, dict]:
    return {visit["ticket_id"]: visit for visit in (state or {}).get("visits", [])}


def _metric_changes(before: dict, after: dict) -> dict[str, dict]:
    old, new = (before or {}).get("metrics") or {}, (after or {}).get("metrics") or {}
    changes = {}
    for name in COMPARED_METRICS:
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
) -> DayPlanRevision:
    """Append one revision and hand the `is_current` marker over atomically.

    The partial unique index lets exactly one revision of an area-day stay current,
    so two concurrent applies cannot both publish: the second waits on the row lock
    and then numbers itself after the first.
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
        diff=diff_states(previous.plan_state if previous is not None else None, plan_state),
        result=result,
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
    return {
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

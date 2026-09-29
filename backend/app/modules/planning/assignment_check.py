"""The planner's hard rules for an assignment that arrives already made.

Solve and manual assignment evaluate every candidate in `prepare`. An exchange import that
brings a planned ticket together with its engineer runs the same evaluation for that one
engineer. Only the rules of the pair count here: the time of day, current execution, line
status and other assignments of the engineer are properties of the running day.
"""

from datetime import datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.planning.eligibility import MOSCOW, prepare
from app.modules.planning.errors import PlanningError
from app.modules.planning.policy import execution_policy, policy_snapshot
from app.modules.planning.repository import load_snapshot
from app.modules.planning.schemas import PreviewRequest


def _reason(value) -> dict:
    return value if isinstance(value, dict) else {"code": value}


def assignment_violation(session: Session, ticket_id: int, worker_id: int) -> dict | None:
    """The first hard rule the engineer breaks for the planned ticket, or None."""
    route_date = session.execute(
        text(
            "SELECT (COALESCE(planned_start_at, visit_window_start) "
            "AT TIME ZONE 'Europe/Moscow')::date FROM tickets WHERE id = :ticket_id"
        ),
        {"ticket_id": ticket_id},
    ).scalar_one()
    request = PreviewRequest(route_date=route_date, ticket_ids=[ticket_id], worker_ids=[worker_id])
    try:
        snapshot = load_snapshot(
            session, request, policy_snapshot=policy_snapshot(execution_policy(get_settings()))
        )
    except PlanningError as error:
        return {"code": error.code, **error.details}
    snapshot = {
        **snapshot,
        "assignments": [],
        "busy_tickets": [],
        "worker_day_states": [],
        "workers": [{**worker, "is_on_line": True} for worker in snapshot["workers"]],
    }
    # Just before the day starts: no shift has started and nothing is running yet.
    before_day = datetime.combine(route_date, time(), MOSCOW) - timedelta(microseconds=1)
    prepared = prepare(snapshot, before_day)
    if any(ticket["id"] == ticket_id for ticket in prepared["tickets"]):
        return None
    rejection = next(item for item in prepared["unassigned"] if item["ticket_id"] == ticket_id)
    candidate = next(
        (item for item in rejection["candidates"] if item["worker_id"] == worker_id), None
    )
    if candidate is not None:
        return _reason(candidate["reason"])
    excluded = next(
        (item for item in prepared["excluded_workers"] if item["worker_id"] == worker_id), None
    )
    return _reason(excluded["reason"] if excluded is not None else rejection["reason"])


def assignment_violations(session: Session, assignments: list[tuple[int, int]]) -> list[dict]:
    return [
        {"ticket_id": ticket_id, "worker_id": worker_id, "reason": reason}
        for ticket_id, worker_id in assignments
        if (reason := assignment_violation(session, ticket_id, worker_id)) is not None
    ]

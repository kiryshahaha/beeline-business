"""SQL primitives shared by execution commands and day-state reducers."""

import json

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session


def lock_ticket_for_execution(session: Session, ticket_id: int) -> RowMapping | None:
    return (
        session.execute(
            text(
                """
                SELECT
                    ticket.id, ticket.title, ticket.status,
                    CASE
                        WHEN ticket.lifecycle_state = 'waiting_assignment'
                             AND ticket.status = 'in_progress'
                            THEN 'in_progress'
                        WHEN ticket.lifecycle_state = 'waiting_assignment'
                             AND ticket.status = 'completed'
                            THEN 'completed'
                        WHEN ticket.lifecycle_state = 'waiting_assignment'
                             AND ticket.status = 'wont_fix'
                            THEN 'cancelled'
                        ELSE ticket.lifecycle_state
                    END AS lifecycle_state,
                    ticket.revision, ticket.execution_cycle, ticket.location_id,
                    ticket.visit_window_start, ticket.visit_window_end,
                    ticket.planned_start_at, ticket.planned_end_at,
                    ticket.actual_started_at, ticket.actual_completed_at,
                    ticket.cancel_reason, building.district_id
                FROM tickets AS ticket
                JOIN locations AS location ON location.id = ticket.location_id
                JOIN buildings AS building ON building.id = location.building_id
                WHERE ticket.id = :ticket_id
                FOR UPDATE
                """
            ),
            {"ticket_id": ticket_id},
        )
        .mappings()
        .one_or_none()
    )


def find_event_by_key(session: Session, idempotency_key: str) -> RowMapping | None:
    return (
        session.execute(
            text(
                """
                SELECT id, event_type, ticket_id, worker_id, district_id,
                       occurred_at, recorded_at, previous_state, new_state,
                       before_revision, after_revision, idempotency_key, payload
                FROM work_events
                WHERE idempotency_key = :idempotency_key
                """
            ),
            {"idempotency_key": idempotency_key},
        )
        .mappings()
        .one_or_none()
    )


def insert_work_event(
    session: Session,
    *,
    event_type: str,
    ticket_id: int | None,
    worker_id: int | None,
    district_id: int | None,
    route_date,
    occurred_at,
    actor_id: int | None,
    reason: str | None,
    previous_state: str | None,
    new_state: str | None,
    before_revision: int | None,
    after_revision: int | None,
    idempotency_key: str,
    payload: dict[str, object],
) -> int | None:
    return session.execute(
        text(
            """
            INSERT INTO work_events (
                event_type, ticket_id, worker_id, district_id, route_date,
                occurred_at, actor_id, reason, previous_state, new_state,
                before_revision, after_revision, idempotency_key, payload
            ) VALUES (
                :event_type, :ticket_id, :worker_id, :district_id, :route_date,
                :occurred_at, :actor_id, :reason, :previous_state, :new_state,
                :before_revision, :after_revision, :idempotency_key,
                CAST(:payload AS JSONB)
            )
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
            """
        ),
        {
            "event_type": event_type,
            "ticket_id": ticket_id,
            "worker_id": worker_id,
            "district_id": district_id,
            "route_date": route_date,
            "occurred_at": occurred_at,
            "actor_id": actor_id,
            "reason": reason,
            "previous_state": previous_state,
            "new_state": new_state,
            "before_revision": before_revision,
            "after_revision": after_revision,
            "idempotency_key": idempotency_key,
            "payload": json.dumps(payload, ensure_ascii=False, default=str),
        },
    ).scalar_one_or_none()


def update_ticket_snapshot(
    session: Session,
    ticket_id: int,
    *,
    expected_revision: int,
    new_state: str,
    legacy_status: str,
    actual_started_at=None,
    actual_completed_at=None,
    cancel_reason: str | None = None,
    clear_cancel_reason: bool = False,
    clear_actual_times: bool = False,
) -> int:
    values = {
        "ticket_id": ticket_id,
        "expected_revision": expected_revision,
        "new_state": new_state,
        "legacy_status": legacy_status,
        "actual_started_at": actual_started_at,
        "actual_completed_at": actual_completed_at,
        "cancel_reason": cancel_reason,
    }
    clauses = [
        "lifecycle_state = :new_state",
        "status = :legacy_status",
        "revision = revision + 1",
        "updated_at = now()",
    ]
    if actual_started_at is not None:
        clauses.append("actual_started_at = :actual_started_at")
    if actual_completed_at is not None:
        clauses.append("actual_completed_at = :actual_completed_at")
    if cancel_reason is not None:
        clauses.append("cancel_reason = :cancel_reason")
    if clear_cancel_reason:
        clauses.append("cancel_reason = NULL")
    if clear_actual_times:
        clauses.extend(["actual_started_at = NULL", "actual_completed_at = NULL"])
    updated = session.execute(
        text(
            "UPDATE tickets SET "
            + ", ".join(clauses)
            + " WHERE id = :ticket_id AND revision = :expected_revision "
            "RETURNING revision"
        ),
        values,
    ).scalar_one_or_none()
    if updated is None:
        raise RuntimeError("ticket_revision_changed")
    return updated


def attach_last_event(session: Session, ticket_id: int, event_id: int) -> None:
    session.execute(
        text(
            "UPDATE tickets SET last_event_id = :event_id, updated_at = now() WHERE id = :ticket_id"
        ),
        {"ticket_id": ticket_id, "event_id": event_id},
    )


def append_worker_event(
    session: Session,
    *,
    event_type: str,
    ticket_id: int | None = None,
    worker_id: int,
    district_id: int,
    route_date,
    occurred_at,
    actor_id: int,
    reason: str | None,
    idempotency_key: str,
    before_revision: int | None = None,
    after_revision: int | None = None,
    payload: dict[str, object],
) -> int | None:
    return insert_work_event(
        session,
        event_type=event_type,
        ticket_id=ticket_id,
        worker_id=worker_id,
        district_id=district_id,
        route_date=route_date,
        occurred_at=occurred_at,
        actor_id=actor_id,
        reason=reason,
        previous_state=None,
        new_state=None,
        before_revision=before_revision,
        after_revision=after_revision,
        idempotency_key=idempotency_key,
        payload=payload,
    )

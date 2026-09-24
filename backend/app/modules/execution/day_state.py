"""Reconstruct and update a worker's confirmed position and availability."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.planning_guard import lock_planning_mutation
from app.modules.execution import repository
from app.modules.execution.enums import TicketLifecycleState, WorkEventType
from app.modules.execution.schemas import (
    RedirectCommand,
    WorkerDayStateRead,
    WorkerUnavailableCommand,
)
from app.modules.execution.service import ExecutionConflict, IdempotencyConflict

MOSCOW = ZoneInfo("Europe/Moscow")


def _event_payload(event: dict) -> dict:
    payload = event.get("payload") or {}
    command = payload.get("command")
    if isinstance(command, dict):
        return {**payload, **command}
    return payload


def _parse_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def reduce_worker_day_events(events, *, initially_available: bool = True) -> dict:
    state = {
        "available": initially_available,
        "unavailable_at": None,
        "unavailable_until": None,
        "last_location_id": None,
        "current_ticket_id": None,
        "current_destination_id": None,
        "en_route_started_at": None,
        "expected_available_at": None,
        "reason": None,
    }
    ordered = sorted(events, key=lambda event: (event["occurred_at"], event.get("id", 0)))
    for event in ordered:
        event_type = event["event_type"]
        payload = _event_payload(event)
        if event_type == "worker_unavailable":
            state["available"] = False
            state["unavailable_at"] = event["occurred_at"]
            state["expected_available_at"] = _parse_datetime(payload.get("expected_available_at"))
            state["unavailable_until"] = state["expected_available_at"]
            state["reason"] = payload.get("reason") or event.get("reason")
        elif event_type == "start_route":
            state["last_location_id"] = payload.get("location_id")
            state["current_ticket_id"] = payload.get("ticket_id")
            state["current_destination_id"] = payload.get("destination_id")
            state["en_route_started_at"] = event["occurred_at"]
        elif event_type == "redirect":
            state["current_destination_id"] = payload.get("destination_id")
            state["current_ticket_id"] = payload.get("ticket_id", state["current_ticket_id"])
            state["reason"] = payload.get("reason") or event.get("reason")
        elif event_type == "start":
            state["last_location_id"] = payload.get("location_id", state["last_location_id"])
            state["current_ticket_id"] = payload.get("ticket_id", state["current_ticket_id"])
            state["current_destination_id"] = None
            state["en_route_started_at"] = None
        elif event_type == "complete":
            state["last_location_id"] = payload.get("location_id", state["last_location_id"])
            state["current_ticket_id"] = None
            state["current_destination_id"] = None
            state["en_route_started_at"] = None
        elif event_type in (WorkEventType.CANCEL.value, "cancel"):
            if payload.get("ticket_id") in (None, state["current_ticket_id"]):
                state["current_ticket_id"] = None
                state["current_destination_id"] = None
                state["en_route_started_at"] = None
        elif event_type == "progress_delay":
            state["expected_available_at"] = _parse_datetime(payload.get("expected_available_at"))
            state["reason"] = payload.get("reason") or event.get("reason")
    return state


class WorkerNotFound(Exception):
    pass


class DistrictNotFound(Exception):
    pass


class DayStateRevisionConflict(ExecutionConflict):
    pass


class UnsafeRedirect(Exception):
    pass


@contextmanager
def _transaction(session: Session) -> Iterator[None]:
    if session.in_transaction():
        yield
    else:
        with session.begin():
            yield


def _event_rows(session: Session, worker_id: int, district_id: int, route_date: date, at):
    return list(
        session.execute(
            text(
                """
                SELECT id, event_type, ticket_id, occurred_at, reason,
                       previous_state, new_state, payload, after_revision
                FROM work_events
                WHERE worker_id = :worker_id
                  AND district_id = :district_id
                  AND route_date = :route_date
                  AND occurred_at <= :at
                ORDER BY occurred_at, id
                """
            ),
            {
                "worker_id": worker_id,
                "district_id": district_id,
                "route_date": route_date,
                "at": at,
            },
        )
        .mappings()
        .all()
    )


def _state_row(session: Session, worker_id: int, district_id: int, route_date: date, *, lock=False):
    suffix = " FOR UPDATE" if lock else ""
    return (
        session.execute(
            text(
                """
                SELECT worker_id, district_id, route_date, revision, available,
                       unavailable_at, unavailable_until, last_location_id,
                       current_ticket_id, current_destination_id,
                       en_route_started_at, expected_available_at, reason
                FROM worker_day_states
                WHERE worker_id = :worker_id
                  AND district_id = :district_id
                  AND route_date = :route_date
                """
                + suffix
            ),
            {
                "worker_id": worker_id,
                "district_id": district_id,
                "route_date": route_date,
            },
        )
        .mappings()
        .one_or_none()
    )


def _ensure_state_row(
    session: Session, worker_id: int, district_id: int, route_date: date, *, lock: bool
):
    state = _state_row(session, worker_id, district_id, route_date, lock=lock)
    if state is not None:
        return state
    session.execute(
        text(
            """
            INSERT INTO worker_day_states (worker_id, district_id, route_date)
            VALUES (:worker_id, :district_id, :route_date)
            ON CONFLICT (worker_id, district_id, route_date) DO NOTHING
            """
        ),
        {
            "worker_id": worker_id,
            "district_id": district_id,
            "route_date": route_date,
        },
    )
    return _state_row(session, worker_id, district_id, route_date, lock=lock)


def _ticket_worker_id(session: Session, ticket_id: int, worker_id: int | None) -> int | None:
    if worker_id is not None:
        return worker_id
    return session.execute(
        text(
            """
            SELECT worker_id
            FROM ticket_assignments
            WHERE ticket_id = :ticket_id
            ORDER BY worker_id
            LIMIT 1
            """
        ),
        {"ticket_id": ticket_id},
    ).scalar_one_or_none()


def prepare_ticket_event_state(
    session: Session,
    *,
    worker_id: int,
    district_id: int,
    route_date: date,
):
    return _ensure_state_row(session, worker_id, district_id, route_date, lock=True)


def materialize_ticket_event(
    session: Session,
    *,
    event_type: str,
    worker_id: int,
    ticket_id: int,
    district_id: int,
    route_date: date,
    occurred_at: datetime,
    payload: dict,
    expected_revision: int,
    fallback_location_id: int | None = None,
) -> int:
    state = _state_row(session, worker_id, district_id, route_date, lock=True)
    if state is None:
        raise WorkerNotFound
    fields = {
        "last_location_id": state["last_location_id"],
        "current_ticket_id": state["current_ticket_id"],
        "current_destination_id": state["current_destination_id"],
        "en_route_started_at": state["en_route_started_at"],
        "expected_available_at": state["expected_available_at"],
        "reason": state["reason"],
    }
    if event_type == WorkEventType.START_ROUTE.value:
        fields.update(
            {
                "last_location_id": payload.get("location_id") or state["last_location_id"],
                "current_ticket_id": ticket_id,
                "current_destination_id": payload.get("destination_id") or fallback_location_id,
                "en_route_started_at": occurred_at,
            }
        )
    elif event_type == WorkEventType.START.value:
        fields.update(
            {
                "last_location_id": payload.get("location_id")
                or fallback_location_id
                or state["last_location_id"],
                "current_ticket_id": ticket_id,
                "current_destination_id": None,
                "en_route_started_at": None,
            }
        )
    elif event_type == WorkEventType.COMPLETE.value:
        fields.update(
            {
                "last_location_id": payload.get("location_id")
                or fallback_location_id
                or state["last_location_id"],
                "current_ticket_id": None,
                "current_destination_id": None,
                "en_route_started_at": None,
                "expected_available_at": None,
                "reason": None,
            }
        )
    elif event_type == WorkEventType.CANCEL.value:
        if state["current_ticket_id"] in (None, ticket_id):
            fields.update(
                {
                    "current_ticket_id": None,
                    "current_destination_id": None,
                    "en_route_started_at": None,
                }
            )
    elif event_type == WorkEventType.PROGRESS_DELAY.value:
        fields.update(
            {
                "expected_available_at": _parse_datetime(payload.get("expected_available_at")),
                "reason": payload.get("reason"),
            }
        )
    after_revision = expected_revision + 1
    updated = session.execute(
        text(
            """
            UPDATE worker_day_states
            SET revision = :revision,
                last_location_id = :last_location_id,
                current_ticket_id = :current_ticket_id,
                current_destination_id = :current_destination_id,
                en_route_started_at = :en_route_started_at,
                expected_available_at = :expected_available_at,
                reason = :reason,
                updated_at = now()
            WHERE worker_id = :worker_id
              AND district_id = :district_id
              AND route_date = :route_date
              AND revision = :expected_revision
            RETURNING revision
            """
        ),
        {
            **fields,
            "revision": after_revision,
            "worker_id": worker_id,
            "district_id": district_id,
            "route_date": route_date,
            "expected_revision": expected_revision,
        },
    ).scalar_one_or_none()
    if updated is None:
        raise DayStateRevisionConflict("stale_revision", current_revision=state["revision"])
    return updated


def _read_state(
    session: Session,
    worker_id: int,
    district_id: int,
    route_date: date,
    at,
    *,
    revision: int | None = None,
) -> WorkerDayStateRead:
    events = _event_rows(session, worker_id, district_id, route_date, at)
    state = reduce_worker_day_events(events)
    worker_revisions = [
        (event["payload"] or {}).get("worker_day_revision")
        for event in events
        if isinstance(event["payload"], dict)
    ]
    revision = revision or max(
        [value for value in worker_revisions if value is not None] or [len(events) + 1]
    )
    latest_states = {}
    completed_ticket_ids = set()
    event_ids = []
    for event in events:
        event_ids.append(event["id"])
        if event["ticket_id"] is None:
            continue
        latest_states[event["ticket_id"]] = event["new_state"]
        if event["event_type"] == WorkEventType.COMPLETE.value:
            completed_ticket_ids.add(event["ticket_id"])
    assigned_ticket_ids = set(
        session.execute(
            text(
                """
                SELECT assignment.ticket_id
                FROM ticket_assignments AS assignment
                JOIN tickets AS ticket ON ticket.id = assignment.ticket_id
                JOIN locations AS location ON location.id = ticket.location_id
                JOIN buildings AS building ON building.id = location.building_id
                WHERE assignment.worker_id = :worker_id
                  AND building.district_id = :district_id
                  AND assignment.assigned_at <= :at
                  AND (ticket.visit_window_start AT TIME ZONE 'Europe/Moscow')::date = :route_date
                """
            ),
            {
                "worker_id": worker_id,
                "district_id": district_id,
                "route_date": route_date,
                "at": at,
            },
        ).scalars()
    )
    remaining_ticket_ids = {
        ticket_id
        for ticket_id in assigned_ticket_ids
        if latest_states.get(ticket_id)
        not in {
            TicketLifecycleState.COMPLETED.value,
            TicketLifecycleState.CANCELLED.value,
        }
    }
    in_progress_ticket_id = state["current_ticket_id"]
    if in_progress_ticket_id is not None:
        remaining_ticket_ids.discard(in_progress_ticket_id)
    current_plan_revision = session.execute(
        text(
            """
            SELECT max(revision)
            FROM day_plan_revisions
            WHERE district_id = :district_id
              AND route_date = :route_date
              AND created_at <= :at
            """
        ),
        {"district_id": district_id, "route_date": route_date, "at": at},
    ).scalar_one_or_none()
    return WorkerDayStateRead(
        worker_id=worker_id,
        district_id=district_id,
        route_date=route_date,
        available=state["available"],
        unavailable_at=state["unavailable_at"],
        unavailable_until=state.get("unavailable_until"),
        last_location_id=state["last_location_id"],
        current_ticket_id=state["current_ticket_id"],
        current_destination_id=state["current_destination_id"],
        en_route_started_at=state["en_route_started_at"],
        expected_available_at=state["expected_available_at"],
        reason=state["reason"],
        revision=revision or 1,
        completed_ticket_ids=sorted(completed_ticket_ids),
        in_progress_ticket_id=in_progress_ticket_id,
        remaining_ticket_ids=sorted(remaining_ticket_ids),
        event_ids=event_ids,
        current_plan_revision=current_plan_revision,
    )


def day_state_at(
    session: Session, worker_id: int, district_id: int, route_date: date, at: datetime
) -> WorkerDayStateRead:
    worker_exists = session.execute(
        text("SELECT 1 FROM workers WHERE user_id = :worker_id"), {"worker_id": worker_id}
    ).scalar_one_or_none()
    if worker_exists is None:
        raise WorkerNotFound
    district_exists = session.execute(
        text("SELECT 1 FROM districts WHERE id = :district_id"),
        {"district_id": district_id},
    ).scalar_one_or_none()
    if district_exists is None:
        raise DistrictNotFound
    return _read_state(session, worker_id, district_id, route_date, at)


def _shift_end(route_date: date, shift_end) -> datetime:
    return datetime.combine(route_date, shift_end, tzinfo=MOSCOW)


def _same_worker_event(existing, command) -> bool:
    payload = existing["payload"] or {}
    if existing["reason"] != command.reason:
        return False
    if payload.get("district_id") != command.district_id:
        return False
    if payload.get("route_date") != command.route_date.isoformat():
        return False
    if payload.get("command", {}) != command.payload:
        return False
    if command.expected_available_at is not None:
        return payload.get("expected_available_at") == command.expected_available_at.isoformat()
    return True


def _same_redirect_event(existing, command) -> bool:
    payload = existing["payload"] or {}
    return (
        existing["reason"] == command.reason
        and payload.get("ticket_id") == command.current_ticket_id
        and payload.get("destination_id") == command.new_destination_id
        and payload.get("worker_id") == command.worker_id
    )


def mark_worker_unavailable(
    session: Session,
    worker_id: int,
    command: WorkerUnavailableCommand,
    *,
    actor_id: int,
    idempotency_key: str,
) -> tuple[WorkerDayStateRead, list[int]]:
    with _transaction(session):
        lock_planning_mutation(session)
        if command.worker_id is not None and command.worker_id != worker_id:
            raise ValueError("worker_id не совпадает с адресом операции")
        if command.reason is None:
            raise ValueError("Для недоступности нужна причина")
        district_exists = session.execute(
            text("SELECT 1 FROM districts WHERE id = :district_id"),
            {"district_id": command.district_id},
        ).scalar_one_or_none()
        if district_exists is None:
            raise DistrictNotFound
        existing = repository.find_event_by_key(session, idempotency_key)
        if existing is not None:
            if (
                existing["worker_id"] != worker_id
                or existing["event_type"] != WorkEventType.WORKER_UNAVAILABLE.value
            ):
                raise IdempotencyConflict(existing["id"])
            if not _same_worker_event(existing, command):
                raise IdempotencyConflict(existing["id"])
            return (
                _read_state(
                    session,
                    worker_id,
                    command.district_id,
                    command.route_date,
                    command.occurred_at,
                    revision=existing["after_revision"],
                ),
                [],
            )
        worker = (
            session.execute(
                text(
                    "SELECT user_id, workshift_start, workshift_end FROM workers "
                    "WHERE user_id = :worker_id FOR UPDATE"
                ),
                {"worker_id": worker_id},
            )
            .mappings()
            .one_or_none()
        )
        if worker is None:
            raise WorkerNotFound
        snapshot = _ensure_state_row(
            session, worker_id, command.district_id, command.route_date, lock=True
        )
        if command.expected_revision != snapshot["revision"]:
            raise DayStateRevisionConflict(
                "stale_revision",
                current_revision=snapshot["revision"],
            )
        expected_available_at = command.expected_available_at
        if expected_available_at is None:
            expected_available_at = _shift_end(command.route_date, worker["workshift_end"])
            if worker["workshift_end"] <= worker["workshift_start"]:
                expected_available_at += timedelta(days=1)
        if expected_available_at <= command.occurred_at:
            raise ValueError("Ожидаемое время доступности должно быть позже события")
        from app.modules.users import repository as users_repository

        released_ticket_ids = users_repository.release_planned_assignments(session, worker_id)
        users_repository.clear_planned_times_without_assignees(session, released_ticket_ids)
        session.execute(
            text("UPDATE workers SET is_on_line = false WHERE user_id = :worker_id"),
            {"worker_id": worker_id},
        )
        before_revision = snapshot["revision"]
        event_payload = {
            "expected_available_at": expected_available_at.isoformat(),
            "worker_id": worker_id,
            "district_id": command.district_id,
            "route_date": command.route_date.isoformat(),
            "worker_day_revision": snapshot["revision"] + 1,
        }
        if command.reason is not None:
            event_payload["reason"] = command.reason
        if command.payload:
            event_payload["command"] = command.payload
        event_id = repository.append_worker_event(
            session,
            event_type=WorkEventType.WORKER_UNAVAILABLE.value,
            worker_id=worker_id,
            district_id=command.district_id,
            route_date=command.route_date,
            occurred_at=command.occurred_at,
            actor_id=actor_id,
            reason=command.reason,
            before_revision=before_revision,
            after_revision=before_revision + 1,
            idempotency_key=idempotency_key,
            payload=event_payload,
        )
        if event_id is None:
            raise IdempotencyConflict(existing["id"] if existing else 0)
        after_revision = before_revision + 1
        session.execute(
            text(
                """
                UPDATE worker_day_states
                SET revision = :revision,
                    available = false,
                    unavailable_at = :unavailable_at,
                    unavailable_until = :unavailable_until,
                    expected_available_at = :expected_available_at,
                    reason = :reason,
                    updated_at = now()
                WHERE worker_id = :worker_id
                  AND district_id = :district_id
                  AND route_date = :route_date
                """
            ),
            {
                "revision": after_revision,
                "unavailable_at": command.occurred_at,
                "unavailable_until": expected_available_at,
                "expected_available_at": expected_available_at,
                "reason": command.reason,
                "worker_id": worker_id,
                "district_id": command.district_id,
                "route_date": command.route_date,
            },
        )
        return (
            _read_state(
                session,
                worker_id,
                command.district_id,
                command.route_date,
                command.occurred_at,
                revision=after_revision,
            ),
            released_ticket_ids,
        )


def redirect_worker(
    session: Session,
    district_id: int,
    route_date: date,
    command: RedirectCommand,
    *,
    actor_id: int,
    idempotency_key: str,
) -> WorkerDayStateRead:
    with _transaction(session):
        lock_planning_mutation(session)
        existing = repository.find_event_by_key(session, idempotency_key)
        if existing is not None:
            if (
                existing["worker_id"] != command.worker_id
                or existing["event_type"] != WorkEventType.REDIRECT.value
                or existing["district_id"] != district_id
                or existing["route_date"] != route_date
                or not _same_redirect_event(existing, command)
            ):
                raise IdempotencyConflict(existing["id"])
            return _read_state(
                session,
                command.worker_id,
                district_id,
                route_date,
                command.occurred_at,
                revision=(existing["payload"] or {}).get("worker_day_revision"),
            )
        district_exists = session.execute(
            text("SELECT 1 FROM districts WHERE id = :district_id"),
            {"district_id": district_id},
        ).scalar_one_or_none()
        if district_exists is None:
            raise DistrictNotFound
        current_plan_revision = session.execute(
            text(
                """
                SELECT revision
                FROM day_plan_revisions
                WHERE district_id = :district_id
                  AND route_date = :route_date
                  AND is_current
                FOR UPDATE
                """
            ),
            {"district_id": district_id, "route_date": route_date},
        ).scalar_one_or_none()
        if current_plan_revision != command.expected_day_revision:
            raise DayStateRevisionConflict(
                "stale_day_revision", current_revision=current_plan_revision
            )
        state = _state_row(session, command.worker_id, district_id, route_date, lock=True)
        if state is None:
            raise UnsafeRedirect("Снимок рабочего дня не найден")
        if state["current_ticket_id"] != command.current_ticket_id:
            raise UnsafeRedirect("Текущая заявка инженера не совпадает")
        if state["current_destination_id"] is None:
            raise UnsafeRedirect("Перенаправить можно только начатый переезд")
        destination_district = session.execute(
            text(
                """
                SELECT building.district_id
                FROM locations AS location
                JOIN buildings AS building ON building.id = location.building_id
                WHERE location.id = :location_id
                """
            ),
            {"location_id": command.new_destination_id},
        ).scalar_one_or_none()
        if destination_district is None:
            raise UnsafeRedirect("Новое место назначения не найдено")
        if destination_district != district_id:
            raise UnsafeRedirect("Новое место назначения относится к другому району")
        payload = {
            "ticket_id": command.current_ticket_id,
            "destination_id": command.new_destination_id,
            "worker_id": command.worker_id,
            "reason": command.reason,
            "worker_day_revision": state["revision"] + 1,
        }
        event_id = repository.append_worker_event(
            session,
            event_type=WorkEventType.REDIRECT.value,
            ticket_id=command.current_ticket_id,
            worker_id=command.worker_id,
            district_id=district_id,
            route_date=route_date,
            occurred_at=command.occurred_at,
            actor_id=actor_id,
            reason=command.reason,
            before_revision=state["revision"],
            after_revision=state["revision"] + 1,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if event_id is None:
            raise IdempotencyConflict(existing["id"] if existing else 0)
        session.execute(
            text(
                """
                UPDATE worker_day_states
                SET revision = revision + 1,
                    current_destination_id = :destination_id,
                    reason = :reason,
                    updated_at = now()
                WHERE worker_id = :worker_id
                  AND district_id = :district_id
                  AND route_date = :route_date
                """
            ),
            {
                "destination_id": command.new_destination_id,
                "reason": command.reason,
                "worker_id": command.worker_id,
                "district_id": district_id,
                "route_date": route_date,
            },
        )
        new_plan_revision = current_plan_revision + 1
        fingerprint = sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        session.execute(
            text(
                """
                UPDATE day_plan_revisions
                SET is_current = false
                WHERE district_id = :district_id
                  AND route_date = :route_date
                  AND is_current
                """
            ),
            {"district_id": district_id, "route_date": route_date},
        )
        session.execute(
            text(
                """
                INSERT INTO day_plan_revisions (
                    district_id, route_date, revision, previous_revision,
                    event_id, actor_id, fingerprint, diff, result
                ) VALUES (
                    :district_id, :route_date, :revision, :previous_revision,
                    :event_id, :actor_id, :fingerprint, CAST(:diff AS JSONB),
                    CAST(:result AS JSONB)
                )
                """
            ),
            {
                "district_id": district_id,
                "route_date": route_date,
                "revision": new_plan_revision,
                "previous_revision": current_plan_revision,
                "event_id": event_id,
                "actor_id": actor_id,
                "fingerprint": fingerprint,
                "diff": json.dumps(payload, ensure_ascii=False),
                "result": json.dumps({"event_id": event_id}, ensure_ascii=False),
            },
        )
        return _read_state(
            session,
            command.worker_id,
            district_id,
            route_date,
            command.occurred_at,
            revision=state["revision"] + 1,
        )

"""Transactional execution commands owned by the observer role."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.planning_guard import lock_planning_mutation
from app.modules.execution import repository
from app.modules.execution.enums import TicketLifecycleState, WorkEventType
from app.modules.execution.schemas import ExecutionCommand, ExecutionResult, WindowChangeCommand
from app.modules.notifications.enums import NotificationKind
from app.modules.tickets.enums import TicketStatus

MOSCOW = ZoneInfo("Europe/Moscow")


class ExecutionError(Exception):
    """Base class for errors that the execution router maps to HTTP responses."""


class IllegalTransition(ExecutionError):
    pass


class RevisionRequired(ExecutionError):
    pass


class ExecutionConflict(ExecutionError):
    def __init__(
        self, code: str, *, current_revision: int | None = None, current_state: str | None = None
    ):
        super().__init__(code)
        self.code = code
        self.current_revision = current_revision
        self.current_state = current_state


class IdempotencyConflict(ExecutionError):
    def __init__(self, event_id: int):
        super().__init__("idempotency_conflict")
        self.event_id = event_id


class TicketNotFound(ExecutionError):
    pass


class RequiredReason(ExecutionError):
    pass


_FORWARD_EVENTS = {
    WorkEventType.ASSIGN: (TicketLifecycleState.WAITING_ASSIGNMENT, TicketLifecycleState.ASSIGNED),
    WorkEventType.DISPATCH: (TicketLifecycleState.ASSIGNED, TicketLifecycleState.DISPATCHED),
    WorkEventType.START_ROUTE: (TicketLifecycleState.DISPATCHED, TicketLifecycleState.EN_ROUTE),
    WorkEventType.START: (TicketLifecycleState.EN_ROUTE, TicketLifecycleState.IN_PROGRESS),
    WorkEventType.COMPLETE: (TicketLifecycleState.IN_PROGRESS, TicketLifecycleState.COMPLETED),
}
_CANCELLABLE = {
    TicketLifecycleState.WAITING_ASSIGNMENT,
    TicketLifecycleState.ASSIGNED,
    TicketLifecycleState.DISPATCHED,
    TicketLifecycleState.EN_ROUTE,
}
_LEGACY_STATUS_BY_STATE = {
    TicketLifecycleState.WAITING_ASSIGNMENT: TicketStatus.PLANNED,
    TicketLifecycleState.ASSIGNED: TicketStatus.PLANNED,
    TicketLifecycleState.DISPATCHED: TicketStatus.PLANNED,
    TicketLifecycleState.EN_ROUTE: TicketStatus.PLANNED,
    TicketLifecycleState.IN_PROGRESS: TicketStatus.IN_PROGRESS,
    TicketLifecycleState.COMPLETED: TicketStatus.COMPLETED,
    TicketLifecycleState.CANCELLED: TicketStatus.WONT_FIX,
}


def legacy_status_for_state(state: TicketLifecycleState) -> TicketStatus:
    return _LEGACY_STATUS_BY_STATE[state]


def _canonical_state(
    raw_state: str | TicketLifecycleState, legacy_status: str
) -> TicketLifecycleState:
    try:
        state = TicketLifecycleState(raw_state)
    except ValueError:
        state = TicketLifecycleState.WAITING_ASSIGNMENT
    if state == TicketLifecycleState.WAITING_ASSIGNMENT:
        return {
            TicketStatus.IN_PROGRESS.value: TicketLifecycleState.IN_PROGRESS,
            TicketStatus.COMPLETED.value: TicketLifecycleState.COMPLETED,
            TicketStatus.WONT_FIX.value: TicketLifecycleState.CANCELLED,
        }.get(legacy_status, state)
    return state


def next_state_for_event(
    current_state: TicketLifecycleState, event_type: WorkEventType
) -> TicketLifecycleState:
    if event_type in _FORWARD_EVENTS:
        expected_previous, next_state = _FORWARD_EVENTS[event_type]
        if current_state != expected_previous:
            raise IllegalTransition(f"{current_state.value} -> {event_type.value}")
        return next_state
    if event_type == WorkEventType.CANCEL:
        if current_state not in _CANCELLABLE:
            raise IllegalTransition(f"{current_state.value} -> cancel")
        return TicketLifecycleState.CANCELLED
    if event_type == WorkEventType.PROGRESS_DELAY:
        if current_state in (TicketLifecycleState.COMPLETED, TicketLifecycleState.CANCELLED):
            raise IllegalTransition(f"{current_state.value} -> progress_delay")
        return current_state
    raise IllegalTransition(f"Unsupported event {event_type.value}")


@contextmanager
def _transaction(session: Session) -> Iterator[None]:
    if session.in_transaction():
        yield
    else:
        with session.begin():
            yield


def _event_payload(command: ExecutionCommand) -> dict[str, object]:
    payload = {
        "command": command.payload,
        "reason": command.reason,
        "occurred_at": command.occurred_at.isoformat(),
    }
    for field in (
        "expected_available_at",
        "worker_id",
        "ticket_id",
        "location_id",
        "destination_id",
    ):
        value = getattr(command, field)
        if value is not None:
            payload[field] = value.isoformat() if hasattr(value, "isoformat") else value
    return payload


def _route_date(occurred_at) -> date:
    return occurred_at.astimezone(MOSCOW).date()


_WORKER_EVENT_TYPES = {
    WorkEventType.START_ROUTE,
    WorkEventType.START,
    WorkEventType.COMPLETE,
    WorkEventType.CANCEL,
    WorkEventType.PROGRESS_DELAY,
}


def _worker_context(
    session: Session,
    ticket_id: int,
    event_type: WorkEventType,
    worker_id: int | None,
    district_id: int,
    route_date,
):
    if event_type not in _WORKER_EVENT_TYPES:
        return None, None
    from app.modules.execution import day_state

    if worker_id is not None:
        assigned = session.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM tickets
                        WHERE id = :ticket_id AND assigned_worker_id = :worker_id
                )
                """
            ),
            {"ticket_id": ticket_id, "worker_id": worker_id},
        ).scalar_one()
        if not assigned:
            raise ExecutionConflict("worker_not_assigned", current_state=None)
    worker_id = day_state._ticket_worker_id(session, ticket_id, worker_id)
    if worker_id is None:
        return None, None
    state = day_state.prepare_ticket_event_state(
        session,
        worker_id=worker_id,
        district_id=district_id,
        route_date=route_date,
    )
    return worker_id, state["revision"]


def _require_reason(
    event_type: WorkEventType,
    reason: str | None,
    expected_available_at=None,
    occurred_at=None,
) -> None:
    if (
        event_type
        in {
            WorkEventType.CANCEL,
            WorkEventType.PROGRESS_DELAY,
            WorkEventType.WORKER_UNAVAILABLE,
        }
        and not reason
    ):
        raise RequiredReason(event_type.value)
    if event_type == WorkEventType.PROGRESS_DELAY and expected_available_at is None:
        raise RequiredReason("expected_available_at")
    if (
        event_type == WorkEventType.PROGRESS_DELAY
        and occurred_at is not None
        and expected_available_at <= occurred_at
    ):
        raise RequiredReason("expected_available_at_future")


def _result(session: Session, ticket_id: int, event_id: int | None, revision: int, replayed: bool):
    from app.modules.tickets.service import get_ticket

    return ExecutionResult(
        ticket=get_ticket(session, ticket_id),
        event_id=event_id,
        revision=revision,
        replayed=replayed,
    )


def _check_replay(
    session: Session,
    existing,
    *,
    ticket_id: int,
    event_type: WorkEventType,
    payload: dict[str, object],
):
    if existing is None:
        return None
    if (
        existing["ticket_id"] != ticket_id
        or existing["event_type"] != event_type.value
        or not _payload_matches(existing["payload"], payload)
    ):
        raise IdempotencyConflict(existing["id"])
    return _result(
        session,
        ticket_id,
        existing["id"],
        existing["after_revision"] or existing["before_revision"] or 1,
        True,
    )


def _payload_matches(stored: dict, requested: dict) -> bool:
    return all(stored.get(key) == value for key, value in requested.items() if key != "occurred_at")


def apply_ticket_event(
    session: Session,
    ticket_id: int,
    event_type: WorkEventType,
    command: ExecutionCommand,
    *,
    actor_id: int,
    idempotency_key: str,
    compatibility: bool = False,
) -> ExecutionResult:
    payload = _event_payload(command)
    with _transaction(session):
        lock_planning_mutation(session)
        existing = repository.find_event_by_key(session, idempotency_key)
        replay = _check_replay(
            session,
            existing,
            ticket_id=ticket_id,
            event_type=event_type,
            payload=payload,
        )
        if replay is not None:
            return replay

        ticket = repository.lock_ticket_for_execution(session, ticket_id)
        if ticket is None:
            raise TicketNotFound
        current_state = _canonical_state(ticket["lifecycle_state"], ticket["status"])
        event_worker_id, worker_day_revision = _worker_context(
            session,
            ticket_id,
            event_type,
            command.worker_id,
            ticket["district_id"],
            _route_date(command.occurred_at),
        )
        if command.expected_revision is None:
            if not compatibility:
                raise RevisionRequired
            expected_revision = ticket["revision"]
        else:
            expected_revision = command.expected_revision
            if expected_revision != ticket["revision"]:
                raise ExecutionConflict(
                    "stale_revision",
                    current_revision=ticket["revision"],
                    current_state=current_state.value,
                )
        _require_reason(
            event_type,
            command.reason,
            command.expected_available_at,
            command.occurred_at,
        )
        if event_worker_id is not None:
            payload.setdefault("ticket_id", ticket_id)
            if event_type == WorkEventType.START_ROUTE:
                payload.setdefault("destination_id", ticket["location_id"])
            elif event_type in {WorkEventType.START, WorkEventType.COMPLETE}:
                payload.setdefault("location_id", ticket["location_id"])
        if compatibility and event_type in {WorkEventType.START, WorkEventType.COMPLETE}:
            if current_state in {TicketLifecycleState.COMPLETED, TicketLifecycleState.CANCELLED}:
                next_state = next_state_for_event(current_state, event_type)
            else:
                next_state = (
                    TicketLifecycleState.IN_PROGRESS
                    if event_type == WorkEventType.START
                    else TicketLifecycleState.COMPLETED
                )
        else:
            next_state = next_state_for_event(current_state, event_type)
        before_revision = ticket["revision"]
        legacy_status = legacy_status_for_state(next_state)
        if compatibility and current_state == next_state:
            return _result(session, ticket_id, None, before_revision, False)
        next_revision = before_revision + 1
        event_id = repository.insert_work_event(
            session,
            event_type=event_type.value,
            ticket_id=ticket_id,
            worker_id=event_worker_id,
            district_id=ticket["district_id"],
            route_date=_route_date(command.occurred_at),
            occurred_at=command.occurred_at,
            actor_id=actor_id,
            reason=command.reason,
            previous_state=current_state.value,
            new_state=next_state.value,
            before_revision=before_revision,
            after_revision=next_revision,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if event_id is None:
            existing = repository.find_event_by_key(session, idempotency_key)
            replay = _check_replay(
                session,
                existing,
                ticket_id=ticket_id,
                event_type=event_type,
                payload=payload,
            )
            if replay is not None:
                return replay
            raise IdempotencyConflict(existing["id"] if existing else 0)
        if event_worker_id is not None:
            from app.modules.execution import day_state

            day_state.materialize_ticket_event(
                session,
                event_type=event_type.value,
                worker_id=event_worker_id,
                ticket_id=ticket_id,
                district_id=ticket["district_id"],
                route_date=_route_date(command.occurred_at),
                occurred_at=command.occurred_at,
                payload=payload,
                expected_revision=worker_day_revision,
                fallback_location_id=ticket["location_id"],
            )
        try:
            revision = repository.update_ticket_snapshot(
                session,
                ticket_id,
                expected_revision=expected_revision,
                new_state=next_state.value,
                legacy_status=legacy_status.value,
                actual_started_at=command.occurred_at
                if event_type == WorkEventType.START
                else None,
                actual_completed_at=command.occurred_at
                if event_type == WorkEventType.COMPLETE
                else None,
                cancel_reason=command.reason if event_type == WorkEventType.CANCEL else None,
            )
        except RuntimeError as error:
            raise ExecutionConflict(
                "stale_revision",
                current_revision=before_revision,
                current_state=current_state.value,
            ) from error
        repository.attach_last_event(session, ticket_id, event_id)
        if event_type == WorkEventType.COMPLETE:
            from app.modules.appliances import service as appliances_service

            appliances_service.on_ticket_status_completed(
                session,
                ticket_id,
                actor_id=actor_id,
                event_id=event_id,
                execution_cycle=ticket["execution_cycle"],
            )
        from app.modules.tickets import repository as ticket_repository

        if event_type != WorkEventType.ASSIGN and ticket["status"] != legacy_status.value:
            ticket_repository.add_notification_events(
                session,
                ticket_repository.list_observer_ids(session),
                kind=NotificationKind.TICKET_STATUS_CHANGED,
                ticket_id=ticket_id,
                data={
                    "title": ticket["title"],
                    "previous_status": ticket["status"],
                    "status": legacy_status.value,
                    "actor_id": actor_id,
                },
            )
        return _result(session, ticket_id, event_id, revision, False)


def reopen_ticket(
    session: Session,
    ticket_id: int,
    command: ExecutionCommand,
    *,
    actor_id: int,
    idempotency_key: str,
) -> ExecutionResult:
    payload = _event_payload(command)
    with _transaction(session):
        lock_planning_mutation(session)
        existing = repository.find_event_by_key(session, idempotency_key)
        replay = _check_replay(
            session,
            existing,
            ticket_id=ticket_id,
            event_type=WorkEventType.REOPEN,
            payload=payload,
        )
        if replay is not None:
            return replay
        ticket = repository.lock_ticket_for_execution(session, ticket_id)
        if ticket is None:
            raise TicketNotFound
        current_state = _canonical_state(ticket["lifecycle_state"], ticket["status"])
        if command.expected_revision != ticket["revision"]:
            raise ExecutionConflict(
                "stale_revision",
                current_revision=ticket["revision"],
                current_state=current_state.value,
            )
        if current_state not in {TicketLifecycleState.COMPLETED, TicketLifecycleState.CANCELLED}:
            raise IllegalTransition(f"{current_state.value} -> reopen")
        before_revision = ticket["revision"]
        event_id = repository.insert_work_event(
            session,
            event_type=WorkEventType.REOPEN.value,
            ticket_id=ticket_id,
            worker_id=None,
            district_id=ticket["district_id"],
            route_date=_route_date(command.occurred_at),
            occurred_at=command.occurred_at,
            actor_id=actor_id,
            reason=command.reason,
            previous_state=current_state.value,
            new_state=TicketLifecycleState.WAITING_ASSIGNMENT.value,
            before_revision=before_revision,
            after_revision=before_revision + 1,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if event_id is None:
            existing = repository.find_event_by_key(session, idempotency_key)
            replay = _check_replay(
                session,
                existing,
                ticket_id=ticket_id,
                event_type=WorkEventType.REOPEN,
                payload=payload,
            )
            if replay is not None:
                return replay
            raise IdempotencyConflict(existing["id"] if existing else 0)
        revision = repository.update_ticket_snapshot(
            session,
            ticket_id,
            expected_revision=before_revision,
            new_state=TicketLifecycleState.WAITING_ASSIGNMENT.value,
            legacy_status=TicketStatus.PLANNED.value,
            clear_cancel_reason=True,
            clear_actual_times=True,
        )
        session.execute(
            text(
                """
            UPDATE tickets
            SET execution_cycle = execution_cycle + 1,
                planned_start_at = NULL,
                planned_end_at = NULL,
                updated_at = now()
            WHERE id = :ticket_id
                """
            ),
            {"ticket_id": ticket_id},
        )
        session.execute(
            text("UPDATE tickets SET assigned_worker_id = NULL WHERE id = :ticket_id"),
            {"ticket_id": ticket_id},
        )
        repository.attach_last_event(session, ticket_id, event_id)
        return _result(session, ticket_id, event_id, revision, False)


def change_window(
    session: Session,
    ticket_id: int,
    command: WindowChangeCommand,
    *,
    actor_id: int,
    idempotency_key: str,
) -> ExecutionResult:
    payload = _event_payload(command) | {
        "new_window_start": command.new_window_start.isoformat(),
        "new_window_end": command.new_window_end.isoformat(),
    }
    with _transaction(session):
        lock_planning_mutation(session)
        existing = repository.find_event_by_key(session, idempotency_key)
        replay = _check_replay(
            session,
            existing,
            ticket_id=ticket_id,
            event_type=WorkEventType.WINDOW_CHANGE,
            payload=payload,
        )
        if replay is not None:
            return replay
        ticket = repository.lock_ticket_for_execution(session, ticket_id)
        if ticket is None:
            raise TicketNotFound
        if command.expected_revision != ticket["revision"]:
            raise ExecutionConflict("stale_revision", current_revision=ticket["revision"])
        before_revision = ticket["revision"]
        current_state = _canonical_state(ticket["lifecycle_state"], ticket["status"])
        if current_state in {TicketLifecycleState.COMPLETED, TicketLifecycleState.CANCELLED}:
            raise IllegalTransition(f"{current_state.value} -> window_change")
        payload.update(
            {
                "previous_window_start": ticket["visit_window_start"].isoformat(),
                "previous_window_end": ticket["visit_window_end"].isoformat(),
            }
        )
        event_id = repository.insert_work_event(
            session,
            event_type=WorkEventType.WINDOW_CHANGE.value,
            ticket_id=ticket_id,
            worker_id=None,
            district_id=ticket["district_id"],
            route_date=_route_date(command.occurred_at),
            occurred_at=command.occurred_at,
            actor_id=actor_id,
            reason=command.reason,
            previous_state=current_state.value,
            new_state=current_state.value,
            before_revision=before_revision,
            after_revision=before_revision + 1,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if event_id is None:
            existing = repository.find_event_by_key(session, idempotency_key)
            replay = _check_replay(
                session,
                existing,
                ticket_id=ticket_id,
                event_type=WorkEventType.WINDOW_CHANGE,
                payload=payload,
            )
            if replay is not None:
                return replay
            raise IdempotencyConflict(existing["id"] if existing else 0)
        revision = repository.update_ticket_snapshot(
            session,
            ticket_id,
            expected_revision=before_revision,
            new_state=current_state.value,
            legacy_status=ticket["status"],
        )
        session.execute(
            text(
                """
            UPDATE tickets
            SET visit_window_start = :start_at, visit_window_end = :end_at, updated_at = now()
            WHERE id = :ticket_id
                """
            ),
            {
                "ticket_id": ticket_id,
                "start_at": command.new_window_start,
                "end_at": command.new_window_end,
            },
        )
        repository.attach_last_event(session, ticket_id, event_id)
        return _result(session, ticket_id, event_id, revision, False)

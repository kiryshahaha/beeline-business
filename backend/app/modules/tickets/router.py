"""Ticket creation, filtered listing and retrieval by ID."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.appliances.inventory import InventoryError
from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.execution import service as execution_service
from app.modules.execution.enums import WorkEventType
from app.modules.execution.schemas import ExecutionCommand, WindowChangeCommand
from app.modules.tickets import service
from app.modules.tickets.enums import TicketStatus
from app.modules.tickets.schemas import (
    TicketAssigneesUpdate,
    TicketCreate,
    TicketRead,
    TicketSlaEstimateRead,
    TicketStatusUpdate,
)
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/tickets", tags=["tickets"])
DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[UserRead, Depends(get_current_user)]
CurrentObserver = Annotated[UserRead, Depends(require_roles(UserRole.OBSERVER))]
IdempotencyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


def _idempotency_key(value: str | None) -> str:
    if value is None or not value.strip() or len(value) > 128:
        raise HTTPException(
            status_code=422, detail="Требуется непустой Idempotency-Key длиной до 128 символов"
        )
    return value.strip()


def _execution_error(error: Exception) -> None:
    if isinstance(error, execution_service.TicketNotFound):
        raise HTTPException(status_code=404, detail="Заявка не найдена") from error
    if isinstance(error, execution_service.ExecutionConflict):
        raise HTTPException(
            status_code=409,
            detail={
                "code": error.code,
                "current_revision": error.current_revision,
                "current_state": error.current_state,
            },
        ) from error
    if isinstance(error, execution_service.IdempotencyConflict):
        raise HTTPException(
            status_code=409,
            detail={"code": "idempotency_conflict", "event_id": error.event_id},
        ) from error
    if isinstance(error, execution_service.RevisionRequired):
        raise HTTPException(status_code=422, detail="Требуется expected_revision") from error
    if isinstance(error, (execution_service.IllegalTransition, execution_service.RequiredReason)):
        raise HTTPException(status_code=422, detail=str(error)) from error
    from app.modules.appliances.service import EquipmentConflict

    if isinstance(error, EquipmentConflict):
        raise HTTPException(
            status_code=409,
            detail={"code": error.code, "message": str(error)},
        ) from error
    raise error


@router.get("", response_model=list[TicketRead])
def list_tickets(
    session: DatabaseSession,
    current_user: CurrentUser,
    status: Annotated[TicketStatus | None, Query(description="Фильтр по статусу заявки.")] = None,
    city_id: Annotated[
        int | None, Query(ge=1, le=2_147_483_647, description="ID города места выполнения.")
    ] = None,
    district_id: Annotated[
        int | None, Query(ge=1, le=2_147_483_647, description="ID района места выполнения.")
    ] = None,
    brigade_id: Annotated[
        int | None,
        Query(ge=1, le=2_147_483_647, description="ID бригады назначенных исполнителей."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Максимум заявок в ответе.")] = 20,
    offset: Annotated[
        int, Query(ge=0, le=2_147_483_647, description="Сколько подходящих заявок пропустить.")
    ] = 0,
) -> list[TicketRead]:
    """Получить список заявок с полными адресами по возрастанию ID.

    Фильтры необязательны и объединяются через AND. Пагинация применяется
    после фильтрации. Наблюдатель видит все заявки, бригадир — заявки своей бригады,
    исполнитель — только назначенные ему заявки.
    Фильтр brigade_id пересекается с доступными заявками. Если совпадений нет,
    возвращается пустой массив.
    """
    return service.list_tickets(
        session,
        status=status,
        city_id=city_id,
        district_id=district_id,
        limit=limit,
        offset=offset,
        brigade_id=brigade_id,
        current_user=current_user,
    )


@router.post("", response_model=TicketRead, status_code=status.HTTP_201_CREATED)
def create_ticket(
    data: TicketCreate,
    session: DatabaseSession,
    response: Response,
    current_user: CurrentObserver,
) -> TicketRead:
    """Создать заявку на существующее место выполнения из адресного справочника."""
    try:
        ticket = service.create_ticket(session, data, actor_id=current_user.id)
    except service.LocationNotFoundError as error:
        raise HTTPException(status_code=422, detail="Место выполнения не найдено") from error
    except service.WorkTypeNotFoundError as error:
        raise HTTPException(status_code=422, detail="Вид работ не найден") from error
    except service.InvalidSlaDeadlineError as error:
        raise HTTPException(
            status_code=422, detail="Срок SLA должен быть позже времени поступления"
        ) from error
    response.headers["Location"] = f"/api/v1/tickets/{ticket.id}"
    return ticket


@router.get(
    "/{id}", response_model=TicketRead, responses={404: {"description": "Заявка не найдена"}}
)
def get_ticket(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    session: DatabaseSession,
    current_user: CurrentUser,
) -> TicketRead:
    """Получить одну заявку вместе с адресом и координатами места выполнения."""
    try:
        return service.get_ticket(session, id, current_user)
    except service.TicketNotFoundError as error:
        raise HTTPException(status_code=404, detail="Заявка не найдена") from error


@router.get("/{id}/sla-estimate", response_model=TicketSlaEstimateRead)
def estimate_ticket_sla(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    previous_ticket_end_at: Annotated[
        datetime, Query(description="Время окончания предыдущей заявки")
    ],
    travel_minutes: Annotated[int, Query(ge=0, description="Время в пути в минутах")],
    session: DatabaseSession,
    current_user: CurrentUser,
) -> TicketSlaEstimateRead:
    """Estimate arrival, service completion and separate visit-window/SLA risks."""
    try:
        return service.estimate_sla(
            session,
            id,
            current_user,
            previous_ticket_end_at=previous_ticket_end_at,
            travel_minutes=travel_minutes,
        )
    except service.TicketNotFoundError as error:
        raise HTTPException(status_code=404, detail="Заявка не найдена") from error
    except service.SlaEstimationConfigurationError as error:
        raise HTTPException(status_code=409, detail={"code": error.code}) from error


@router.put("/{id}/assignees", response_model=TicketRead)
def replace_ticket_assignees(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    data: TicketAssigneesUpdate,
    session: DatabaseSession,
    _current_user: CurrentObserver,
) -> TicketRead:
    """Replace the complete worker list; newly assigned workers receive an event."""
    try:
        return service.replace_assignees(session, id, data.worker_ids, actor_id=_current_user.id)
    except service.TicketNotFoundError as error:
        raise HTTPException(status_code=404, detail="Заявка не найдена") from error
    except service.WorkerNotFoundError as error:
        raise HTTPException(
            status_code=422, detail="Один или несколько исполнителей не найдены"
        ) from error
    except service.WorkerOffLineError as error:
        raise HTTPException(
            status_code=422,
            detail="Один или несколько исполнителей сняты с линии",
        ) from error
    except service.ServiceAreaMismatchError as error:
        raise HTTPException(
            status_code=422,
            detail="Исполнитель принадлежит другому участку обслуживания",
        ) from error
    except InventoryError as error:
        raise HTTPException(status_code=error.status, detail=error.detail()) from error


@router.patch("/{id}/status", response_model=TicketRead)
def update_ticket_status(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    data: TicketStatusUpdate,
    session: DatabaseSession,
    current_user: CurrentObserver,
    idempotency_key: IdempotencyHeader = None,
) -> TicketRead:
    """Change ticket status; this operation is reserved for observers."""
    try:
        return service.update_ticket_status(
            session,
            id,
            data.status,
            current_user,
            expected_revision=data.expected_revision,
            reason=data.reason,
            idempotency_key=idempotency_key.strip() if idempotency_key else None,
        )
    except service.TicketNotFoundError as error:
        raise HTTPException(status_code=404, detail="Заявка не найдена") from error
    except service.PermissionDeniedError as error:
        raise HTTPException(
            status_code=403, detail="Нет прав на изменение статуса заявки"
        ) from error
    except InventoryError as error:
        raise HTTPException(status_code=error.status, detail=error.detail()) from error
    except Exception as error:
        _execution_error(error)
        raise AssertionError("unreachable")


def _apply_execution_command(
    id: int,
    event_type: WorkEventType,
    data: ExecutionCommand,
    session: Session,
    current_user: UserRead,
    idempotency_key: str | None,
) -> TicketRead:
    try:
        return execution_service.apply_ticket_event(
            session,
            id,
            event_type,
            data,
            actor_id=current_user.id,
            idempotency_key=_idempotency_key(idempotency_key),
        ).ticket
    except Exception as error:
        _execution_error(error)
        raise AssertionError("unreachable")


@router.post("/{id}/dispatch", response_model=TicketRead)
def dispatch_ticket(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    data: ExecutionCommand,
    session: DatabaseSession,
    current_user: CurrentObserver,
    idempotency_key: IdempotencyHeader = None,
) -> TicketRead:
    return _apply_execution_command(
        id, WorkEventType.DISPATCH, data, session, current_user, idempotency_key
    )


@router.post("/{id}/start-route", response_model=TicketRead)
def start_ticket_route(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    data: ExecutionCommand,
    session: DatabaseSession,
    current_user: CurrentObserver,
    idempotency_key: IdempotencyHeader = None,
) -> TicketRead:
    return _apply_execution_command(
        id, WorkEventType.START_ROUTE, data, session, current_user, idempotency_key
    )


@router.post("/{id}/start", response_model=TicketRead)
def start_ticket_work(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    data: ExecutionCommand,
    session: DatabaseSession,
    current_user: CurrentObserver,
    idempotency_key: IdempotencyHeader = None,
) -> TicketRead:
    return _apply_execution_command(
        id, WorkEventType.START, data, session, current_user, idempotency_key
    )


@router.post("/{id}/complete", response_model=TicketRead)
def complete_ticket_work(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    data: ExecutionCommand,
    session: DatabaseSession,
    current_user: CurrentObserver,
    idempotency_key: IdempotencyHeader = None,
) -> TicketRead:
    return _apply_execution_command(
        id, WorkEventType.COMPLETE, data, session, current_user, idempotency_key
    )


@router.post("/{id}/cancel", response_model=TicketRead)
def cancel_ticket(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    data: ExecutionCommand,
    session: DatabaseSession,
    current_user: CurrentObserver,
    idempotency_key: IdempotencyHeader = None,
) -> TicketRead:
    return _apply_execution_command(
        id, WorkEventType.CANCEL, data, session, current_user, idempotency_key
    )


@router.post("/{id}/delay", response_model=TicketRead)
def delay_ticket(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    data: ExecutionCommand,
    session: DatabaseSession,
    current_user: CurrentObserver,
    idempotency_key: IdempotencyHeader = None,
) -> TicketRead:
    if data.expected_available_at is None:
        raise HTTPException(status_code=422, detail="Требуется expected_available_at")
    return _apply_execution_command(
        id, WorkEventType.PROGRESS_DELAY, data, session, current_user, idempotency_key
    )


@router.post("/{id}/reopen", response_model=TicketRead)
def reopen_ticket(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    data: ExecutionCommand,
    session: DatabaseSession,
    current_user: CurrentObserver,
    idempotency_key: IdempotencyHeader = None,
) -> TicketRead:
    try:
        return execution_service.reopen_ticket(
            session,
            id,
            data,
            actor_id=current_user.id,
            idempotency_key=_idempotency_key(idempotency_key),
        ).ticket
    except Exception as error:
        _execution_error(error)
        raise AssertionError("unreachable")


@router.post("/{id}/window-change", response_model=TicketRead)
def change_ticket_window(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    data: WindowChangeCommand,
    session: DatabaseSession,
    current_user: CurrentObserver,
    idempotency_key: IdempotencyHeader = None,
) -> TicketRead:
    try:
        return execution_service.change_window(
            session,
            id,
            data,
            actor_id=current_user.id,
            idempotency_key=_idempotency_key(idempotency_key),
        ).ticket
    except Exception as error:
        _execution_error(error)
        raise AssertionError("unreachable")

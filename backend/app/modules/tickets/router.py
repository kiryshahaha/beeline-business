"""Ticket creation, filtered listing and retrieval by ID."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth.dependencies import OptionalCurrentUser, get_current_user, require_roles
from app.modules.tickets import service
from app.modules.tickets.enums import TicketStatus
from app.modules.tickets.schemas import (
    TicketAssigneesUpdate,
    TicketCreate,
    TicketRead,
    TicketStatusUpdate,
)
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/tickets", tags=["tickets"])
DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[UserRead, Depends(get_current_user)]
CurrentObserver = Annotated[UserRead, Depends(require_roles(UserRole.OBSERVER))]


@router.get("", response_model=list[TicketRead])
def list_tickets(
    session: DatabaseSession,
    current_user: OptionalCurrentUser,
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
    после фильтрации. Начальник видит заявки, назначенные работникам его бригады.
    Фильтр brigade_id пересекается с доступными заявками. Если совпадений нет,
    возвращается пустой массив. Чтение без авторизации сохранено для совместимости.
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
def create_ticket(data: TicketCreate, session: DatabaseSession, response: Response) -> TicketRead:
    """Создать заявку на существующее место выполнения из адресного справочника."""
    try:
        ticket = service.create_ticket(session, data)
    except service.LocationNotFoundError as error:
        raise HTTPException(status_code=422, detail="Место выполнения не найдено") from error
    response.headers["Location"] = f"/api/v1/tickets/{ticket.id}"
    return ticket


@router.get(
    "/{id}", response_model=TicketRead, responses={404: {"description": "Заявка не найдена"}}
)
def get_ticket(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    session: DatabaseSession,
    current_user: OptionalCurrentUser,
) -> TicketRead:
    """Получить одну заявку вместе с адресом и координатами места выполнения."""
    try:
        return service.get_ticket(session, id, current_user)
    except service.TicketNotFoundError as error:
        raise HTTPException(status_code=404, detail="Заявка не найдена") from error


@router.put("/{id}/assignees", response_model=TicketRead)
def replace_ticket_assignees(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    data: TicketAssigneesUpdate,
    session: DatabaseSession,
    _current_user: CurrentObserver,
) -> TicketRead:
    """Replace the complete worker list; newly assigned workers receive an event."""
    try:
        return service.replace_assignees(session, id, data.worker_ids)
    except service.TicketNotFoundError as error:
        raise HTTPException(status_code=404, detail="Заявка не найдена") from error
    except service.WorkerNotFoundError as error:
        raise HTTPException(
            status_code=422, detail="Один или несколько исполнителей не найдены"
        ) from error


@router.patch("/{id}/status", response_model=TicketRead)
def update_ticket_status(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    data: TicketStatusUpdate,
    session: DatabaseSession,
    current_user: CurrentUser,
) -> TicketRead:
    """Change status as an observer or a worker assigned to this ticket."""
    try:
        return service.update_ticket_status(session, id, data.status, current_user)
    except service.TicketNotFoundError as error:
        raise HTTPException(status_code=404, detail="Заявка не найдена") from error
    except service.PermissionDeniedError as error:
        raise HTTPException(
            status_code=403, detail="Нет прав на изменение статуса заявки"
        ) from error

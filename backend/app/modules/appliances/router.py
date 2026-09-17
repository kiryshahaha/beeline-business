"""REST API routers for appliances, office warehouse stock, and ticket allocations."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.appliances import service
from app.modules.appliances.enums import ApplianceType
from app.modules.appliances.schemas import (
    ApplianceCreate,
    ApplianceRead,
    ApplianceUpdate,
    OfficeStockItemRead,
    OfficeStockSetRequest,
    TicketApplianceCreate,
    TicketApplianceRead,
    TicketApplianceUpdate,
)
from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead

DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[UserRead, Depends(get_current_user)]
RequireObserver = Annotated[UserRead, Depends(require_roles(UserRole.OBSERVER))]
PositiveIntPath = Annotated[int, Path(ge=1, le=2_147_483_647)]

appliances_router = APIRouter(prefix="/api/v1/appliances", tags=["appliances"])
office_stock_router = APIRouter(prefix="/api/v1/offices", tags=["office stock"])
ticket_appliances_router = APIRouter(prefix="/api/v1/tickets", tags=["ticket appliances"])


def _handle_service_error(error: Exception) -> None:
    if isinstance(error, service.ApplianceNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(error, service.OfficeNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(error, service.TicketNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(error, service.TicketApplianceNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(error, service.ApplianceAlreadyExistsError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if isinstance(error, service.ApplianceAlreadyAttachedError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if isinstance(error, (service.InsufficientStockError, service.CannotReduceStockBelowReservedError, service.TicketAlreadyClosedError)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    if isinstance(error, service.PermissionDeniedError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    raise error


# --- 1. APPLIANCES CATALOG ---

@appliances_router.post(
    "/",
    response_model=ApplianceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать позицию оборудования",
)
def create_appliance(
    data: ApplianceCreate,
    session: DatabaseSession,
    _admin: RequireObserver,
) -> ApplianceRead:
    try:
        with session.begin():
            return service.create_appliance(session, data)
    except Exception as err:
        _handle_service_error(err)


@appliances_router.get(
    "/",
    response_model=list[ApplianceRead],
    summary="Получить список оборудования с фильтрацией",
)
def list_appliances(
    session: DatabaseSession,
    _current_user: CurrentUser,
    type: ApplianceType | None = Query(None, description="Тип оборудования"),
    is_active: bool | None = Query(None, description="Флаг активности"),
    search: str | None = Query(None, description="Поиск по названию"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ApplianceRead]:
    return service.list_appliances(
        session,
        type=type,
        is_active=is_active,
        search=search,
        limit=limit,
        offset=offset,
    )


@appliances_router.get(
    "/{id}",
    response_model=ApplianceRead,
    summary="Получить позицию оборудования по ID",
)
def get_appliance(
    id: PositiveIntPath,
    session: DatabaseSession,
    _current_user: CurrentUser,
) -> ApplianceRead:
    try:
        return service.get_appliance(session, id)
    except Exception as err:
        _handle_service_error(err)


@appliances_router.patch(
    "/{id}",
    response_model=ApplianceRead,
    summary="Обновить позицию оборудования",
)
def update_appliance(
    id: PositiveIntPath,
    data: ApplianceUpdate,
    session: DatabaseSession,
    _admin: RequireObserver,
) -> ApplianceRead:
    try:
        with session.begin():
            return service.update_appliance(session, id, data)
    except Exception as err:
        _handle_service_error(err)


@appliances_router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Деактивировать/удалить позицию оборудования",
)
def delete_appliance(
    id: PositiveIntPath,
    session: DatabaseSession,
    _admin: RequireObserver,
) -> None:
    try:
        with session.begin():
            service.delete_appliance(session, id)
    except Exception as err:
        _handle_service_error(err)


# --- 2. OFFICE WAREHOUSE STOCK ---

@office_stock_router.get(
    "/{office_id}/stock",
    response_model=list[OfficeStockItemRead],
    summary="Ведомость складских остатков офиса",
)
def list_office_stocks(
    office_id: PositiveIntPath,
    session: DatabaseSession,
    _current_user: CurrentUser,
) -> list[OfficeStockItemRead]:
    try:
        return service.list_office_stocks(session, office_id)
    except Exception as err:
        _handle_service_error(err)


@office_stock_router.put(
    "/{office_id}/stock/{appliance_id}",
    response_model=OfficeStockItemRead,
    summary="Установить остаток оборудования на складе офиса",
)
def set_office_stock(
    office_id: PositiveIntPath,
    appliance_id: PositiveIntPath,
    data: OfficeStockSetRequest,
    session: DatabaseSession,
    _admin: RequireObserver,
) -> OfficeStockItemRead:
    try:
        with session.begin():
            return service.set_office_stock(session, office_id, appliance_id, data.stock)
    except Exception as err:
        _handle_service_error(err)


# --- 3. TICKET APPLIANCE ALLOCATIONS ---

@ticket_appliances_router.get(
    "/{ticket_id}/appliances",
    response_model=list[TicketApplianceRead],
    summary="Список оборудования, прикрепленного к заявке",
)
def list_ticket_appliances(
    ticket_id: PositiveIntPath,
    session: DatabaseSession,
    current_user: CurrentUser,
) -> list[TicketApplianceRead]:
    try:
        return service.list_ticket_appliances(session, ticket_id, current_user)
    except Exception as err:
        _handle_service_error(err)


@ticket_appliances_router.post(
    "/{ticket_id}/appliances",
    response_model=TicketApplianceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Назначить оборудование на заявку",
)
def add_ticket_appliance(
    ticket_id: PositiveIntPath,
    data: TicketApplianceCreate,
    session: DatabaseSession,
    current_user: CurrentUser,
) -> TicketApplianceRead:
    try:
        with session.begin():
            return service.add_ticket_appliance(session, ticket_id, data, current_user)
    except Exception as err:
        _handle_service_error(err)


@ticket_appliances_router.patch(
    "/{ticket_id}/appliances/{appliance_id}",
    response_model=TicketApplianceRead,
    summary="Изменить количество оборудования в заявке",
)
def update_ticket_appliance(
    ticket_id: PositiveIntPath,
    appliance_id: PositiveIntPath,
    data: TicketApplianceUpdate,
    session: DatabaseSession,
    current_user: CurrentUser,
) -> TicketApplianceRead:
    try:
        with session.begin():
            return service.update_ticket_appliance(session, ticket_id, appliance_id, data, current_user)
    except Exception as err:
        _handle_service_error(err)


@ticket_appliances_router.delete(
    "/{ticket_id}/appliances/{appliance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Снять оборудование с заявки",
)
def remove_ticket_appliance(
    ticket_id: PositiveIntPath,
    appliance_id: PositiveIntPath,
    session: DatabaseSession,
    current_user: CurrentUser,
) -> None:
    try:
        with session.begin():
            service.remove_ticket_appliance(session, ticket_id, appliance_id, current_user)
    except Exception as err:
        _handle_service_error(err)

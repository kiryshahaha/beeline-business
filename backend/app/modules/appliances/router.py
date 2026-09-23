"""REST API routers for appliances, office warehouse stock, and ticket allocations."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.core.planning_guard import lock_planning_mutation
from app.db.session import get_session
from app.modules.appliances import inventory, service
from app.modules.appliances.enums import ApplianceType
from app.modules.appliances.schemas import (
    ApplianceCreate,
    ApplianceRead,
    ApplianceUpdate,
    IssueRequest,
    KitReserveItemRead,
    KitReserveSetRequest,
    OfficeStockItemRead,
    OfficeStockSetRequest,
    OperationRead,
    RestoreRequest,
    ReturnRequest,
    TicketApplianceCreate,
    TicketApplianceRead,
    TicketApplianceUpdate,
    WorkerEquipmentRead,
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
worker_equipment_router = APIRouter(prefix="/api/v1/workers", tags=["worker equipment"])
equipment_journal_router = APIRouter(prefix="/api/v1/equipment", tags=["worker equipment"])


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
    if isinstance(
        error,
        (
            service.InsufficientStockError,
            service.CannotReduceStockBelowReservedError,
            service.TicketAlreadyClosedError,
        ),
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    if isinstance(error, service.AllocationLockedError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if isinstance(error, inventory.InventoryError):
        raise HTTPException(status_code=error.status, detail=error.detail()) from error
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
            lock_planning_mutation(session)
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
            lock_planning_mutation(session)
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
            lock_planning_mutation(session)
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
            lock_planning_mutation(session)
            return service.set_office_stock(session, office_id, appliance_id, data.stock)
    except Exception as err:
        _handle_service_error(err)


# --- 3. TICKET APPLIANCE ALLOCATIONS ---


@ticket_appliances_router.get(
    "/{id}/appliances",
    response_model=list[TicketApplianceRead],
    summary="Список оборудования, прикрепленного к заявке",
)
def list_ticket_appliances(
    id: PositiveIntPath,
    session: DatabaseSession,
    current_user: CurrentUser,
) -> list[TicketApplianceRead]:
    try:
        return service.list_ticket_appliances(session, id, current_user)
    except Exception as err:
        _handle_service_error(err)


@ticket_appliances_router.post(
    "/{id}/appliances",
    response_model=TicketApplianceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Назначить оборудование на заявку",
)
def add_ticket_appliance(
    id: PositiveIntPath,
    data: TicketApplianceCreate,
    session: DatabaseSession,
    current_user: CurrentUser,
) -> TicketApplianceRead:
    try:
        with session.begin():
            lock_planning_mutation(session)
            return service.add_ticket_appliance(session, id, data, current_user)
    except Exception as err:
        _handle_service_error(err)


@ticket_appliances_router.patch(
    "/{id}/appliances/{appliance_id}",
    response_model=TicketApplianceRead,
    summary="Изменить количество оборудования в заявке",
)
def update_ticket_appliance(
    id: PositiveIntPath,
    appliance_id: PositiveIntPath,
    data: TicketApplianceUpdate,
    session: DatabaseSession,
    current_user: CurrentUser,
) -> TicketApplianceRead:
    try:
        with session.begin():
            lock_planning_mutation(session)
            return service.update_ticket_appliance(session, id, appliance_id, data, current_user)
    except Exception as err:
        _handle_service_error(err)


@ticket_appliances_router.delete(
    "/{id}/appliances/{appliance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Снять оборудование с заявки",
)
def remove_ticket_appliance(
    id: PositiveIntPath,
    appliance_id: PositiveIntPath,
    session: DatabaseSession,
    current_user: CurrentUser,
) -> None:
    try:
        with session.begin():
            lock_planning_mutation(session)
            service.remove_ticket_appliance(session, id, appliance_id, current_user)
    except Exception as err:
        _handle_service_error(err)


# --- 4. UNITS ON HAND, KIT AND JOURNAL ---


def _inventory_error(error: inventory.InventoryError):
    raise HTTPException(status_code=error.status, detail=error.detail()) from error


@office_stock_router.get(
    "/{office_id}/kit-reserve",
    response_model=list[KitReserveItemRead],
    summary="Норма резерва комплекта инженера офиса",
)
def list_kit_reserve(
    office_id: PositiveIntPath, session: DatabaseSession, _current_user: CurrentUser
) -> list[KitReserveItemRead]:
    try:
        return inventory.kit_reserve(session, office_id)
    except inventory.InventoryError as error:
        _inventory_error(error)


@office_stock_router.put(
    "/{office_id}/kit-reserve/{appliance_id}",
    response_model=KitReserveItemRead,
    summary="Задать норму резерва комплекта (0 удаляет норму)",
)
def set_kit_reserve(
    office_id: PositiveIntPath,
    appliance_id: PositiveIntPath,
    data: KitReserveSetRequest,
    session: DatabaseSession,
    _admin: RequireObserver,
) -> KitReserveItemRead:
    try:
        with session.begin():
            lock_planning_mutation(session)
            return inventory.set_kit_reserve(session, office_id, appliance_id, data.quantity)
    except inventory.InventoryError as error:
        _inventory_error(error)


@worker_equipment_router.get(
    "/{worker_id}/equipment",
    response_model=WorkerEquipmentRead,
    summary="Оборудование на руках инженера и комплект к выдаче на дату",
)
def read_worker_equipment(
    worker_id: PositiveIntPath,
    session: DatabaseSession,
    current_user: CurrentUser,
    day: Annotated[date | None, Query(alias="date")] = None,
) -> WorkerEquipmentRead:
    allowed = (
        current_user.role == UserRole.OBSERVER
        or (current_user.role == UserRole.WORKER and current_user.id == worker_id)
        or (
            current_user.role == UserRole.FOREMAN
            and inventory.is_foreman_of(session, current_user.id, worker_id)
        )
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Нет доступа к оборудованию инженера")
    try:
        return inventory.worker_equipment(session, worker_id, day or inventory.today())
    except inventory.InventoryError as error:
        _inventory_error(error)


@worker_equipment_router.post(
    "/{worker_id}/equipment/issue",
    response_model=OperationRead,
    summary="Выдать комплект на день: оборудование назначенных заявок и резерв офиса",
)
def issue_worker_kit(
    worker_id: PositiveIntPath,
    data: IssueRequest,
    session: DatabaseSession,
    admin: RequireObserver,
) -> OperationRead:
    try:
        with session.begin():
            lock_planning_mutation(session)
            return inventory.issue_kit(session, worker_id, data.date, data.operation_key, admin.id)
    except inventory.InventoryError as error:
        _inventory_error(error)


@worker_equipment_router.post(
    "/{worker_id}/equipment/return",
    response_model=OperationRead,
    summary="Вернуть оборудование с рук инженера на склад офиса",
)
def return_worker_equipment(
    worker_id: PositiveIntPath,
    data: ReturnRequest,
    session: DatabaseSession,
    admin: RequireObserver,
) -> OperationRead:
    try:
        with session.begin():
            lock_planning_mutation(session)
            return inventory.return_equipment(session, worker_id, data, admin.id)
    except inventory.InventoryError as error:
        _inventory_error(error)


@ticket_appliances_router.post(
    "/{id}/equipment/restore",
    response_model=OperationRead,
    summary="Оформить возврат списанного оборудования заявки после переоткрытия",
)
def restore_ticket_equipment(
    id: PositiveIntPath,
    data: RestoreRequest,
    session: DatabaseSession,
    admin: RequireObserver,
) -> OperationRead:
    try:
        with session.begin():
            lock_planning_mutation(session)
            return inventory.restore_ticket_equipment(session, id, data, admin.id)
    except inventory.InventoryError as error:
        _inventory_error(error)


@equipment_journal_router.get(
    "/operations",
    response_model=list[OperationRead],
    summary="Журнал движения оборудования",
)
def list_equipment_operations(
    session: DatabaseSession,
    _admin: RequireObserver,
    worker_id: Annotated[int | None, Query(ge=1, le=2_147_483_647)] = None,
    ticket_id: Annotated[int | None, Query(ge=1, le=2_147_483_647)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[OperationRead]:
    return inventory.operations(session, worker_id=worker_id, ticket_id=ticket_id, limit=limit)

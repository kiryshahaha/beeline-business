"""Business logic and domain operations for appliances and warehouse stock."""

from sqlalchemy.orm import Session

from app.modules.appliances import inventory, repository
from app.modules.appliances.enums import ApplianceType
from app.modules.appliances.models import TicketApplianceState
from app.modules.appliances.schemas import (
    ApplianceCreate,
    ApplianceRead,
    ApplianceUpdate,
    OfficeStockItemRead,
    TicketApplianceCreate,
    TicketApplianceRead,
    TicketApplianceUpdate,
)
from app.modules.offices.models import Office
from app.modules.tickets import repository as tickets_repo
from app.modules.tickets.models import Ticket
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead


class ApplianceNotFoundError(Exception):
    pass


class ApplianceAlreadyExistsError(Exception):
    pass


class OfficeNotFoundError(Exception):
    pass


class TicketNotFoundError(Exception):
    pass


class InsufficientStockError(Exception):
    pass


class ApplianceAlreadyAttachedError(Exception):
    pass


class TicketApplianceNotFoundError(Exception):
    pass


class PermissionDeniedError(Exception):
    pass


class CannotReduceStockBelowReservedError(Exception):
    pass


class TicketAlreadyClosedError(Exception):
    pass


class AllocationLockedError(Exception):
    pass


def _check_allocation_in_office(session: Session, ticket_id: int, appliance_id: int) -> None:
    if session.get(TicketApplianceState, (ticket_id, appliance_id)) is not None:
        raise AllocationLockedError(
            "Оборудование заявки уже выдано инженеру или списано: сначала оформите возврат"
        )


def _check_foreman_ticket_access(
    session: Session, ticket_id: int, current_user: UserRead | None
) -> None:
    if current_user is None or current_user.role == UserRole.OBSERVER:
        return
    if current_user.role == UserRole.FOREMAN:
        if not tickets_repo.ticket_exists(session, ticket_id, foreman_id=current_user.id):
            raise PermissionDeniedError("Нет доступа к заявке")
        return
    if current_user.role == UserRole.WORKER:
        # Worker can view their assigned tickets
        row = tickets_repo.find_ticket(session, ticket_id)
        if row is None or current_user.id not in row["assignee_ids"]:
            raise PermissionDeniedError("Нет доступа к заявке")


def create_appliance(session: Session, data: ApplianceCreate) -> ApplianceRead:
    existing = repository.get_appliance_by_name(session, data.name)
    if existing is not None:
        if not existing.is_active:
            # Reactivate previously archived appliance and update its attributes
            existing.is_active = True
            existing.description = data.description
            existing.type = data.type
            existing.unit = data.unit
            session.flush()
            return ApplianceRead.model_validate(existing)
        raise ApplianceAlreadyExistsError(f"Оборудование с именем '{data.name}' уже существует")
    appliance = repository.create_appliance(session, data)
    return ApplianceRead.model_validate(appliance)


def get_appliance(session: Session, appliance_id: int) -> ApplianceRead:
    appliance = repository.get_appliance(session, appliance_id)
    if appliance is None:
        raise ApplianceNotFoundError(f"Оборудование с id={appliance_id} не найдено")
    return ApplianceRead.model_validate(appliance)


def list_appliances(
    session: Session,
    *,
    type: ApplianceType | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ApplianceRead]:
    items = repository.list_appliances(
        session,
        type=type,
        is_active=is_active,
        search=search,
        limit=limit,
        offset=offset,
    )
    return [ApplianceRead.model_validate(item) for item in items]


def update_appliance(session: Session, appliance_id: int, data: ApplianceUpdate) -> ApplianceRead:
    appliance = repository.get_appliance(session, appliance_id)
    if appliance is None:
        raise ApplianceNotFoundError(f"Оборудование с id={appliance_id} не найдено")

    if data.name is not None and data.name.strip().lower() != appliance.name.lower():
        existing = repository.get_appliance_by_name(session, data.name)
        if existing is not None and existing.id != appliance_id:
            raise ApplianceAlreadyExistsError(f"Оборудование с именем '{data.name}' уже существует")

    updated = repository.update_appliance(session, appliance, data)
    return ApplianceRead.model_validate(updated)


def delete_appliance(session: Session, appliance_id: int) -> None:
    appliance = repository.get_appliance(session, appliance_id)
    if appliance is None:
        raise ApplianceNotFoundError(f"Оборудование с id={appliance_id} не найдено")
    # Soft-delete if in use, or hard-delete if unreferenced
    appliance.is_active = False
    session.flush()


def list_office_stocks(session: Session, office_id: int) -> list[OfficeStockItemRead]:
    office = session.get(Office, office_id)
    if office is None:
        raise OfficeNotFoundError(f"Офис с id={office_id} не найден")
    items = repository.list_office_stocks(session, office_id)
    return [OfficeStockItemRead.model_validate(item) for item in items]


def set_office_stock(
    session: Session, office_id: int, appliance_id: int, stock: int
) -> OfficeStockItemRead:
    office = session.get(Office, office_id)
    if office is None:
        raise OfficeNotFoundError(f"Офис с id={office_id} не найден")

    appliance = repository.get_appliance(session, appliance_id)
    if appliance is None:
        raise ApplianceNotFoundError(f"Оборудование с id={appliance_id} не найдено")

    reserved = repository.get_reserved_stock_for_office(session, office_id, appliance_id)
    if stock < reserved:
        raise CannotReduceStockBelowReservedError(
            f"Нельзя установить остаток {stock}: "
            f"в открытых заявках уже задействовано {reserved} шт."
        )

    stock_row = repository.set_office_stock(session, office_id, appliance_id, stock)
    return OfficeStockItemRead(
        office_id=office_id,
        appliance_id=appliance_id,
        name=appliance.name,
        description=appliance.description,
        type=appliance.type,
        unit=appliance.unit,
        stock=stock_row.stock,
        reserved=reserved,
        available=stock_row.stock - reserved,
    )


def list_ticket_appliances(
    session: Session, ticket_id: int, current_user: UserRead | None = None
) -> list[TicketApplianceRead]:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise TicketNotFoundError(f"Заявка с id={ticket_id} не найдена")
    _check_foreman_ticket_access(session, ticket_id, current_user)
    items = repository.list_ticket_appliances(session, ticket_id)
    return [TicketApplianceRead.model_validate(item) for item in items]


def add_ticket_appliance(
    session: Session,
    ticket_id: int,
    data: TicketApplianceCreate,
    current_user: UserRead | None = None,
) -> TicketApplianceRead:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise TicketNotFoundError(f"Заявка с id={ticket_id} не найдена")
    _check_foreman_ticket_access(session, ticket_id, current_user)

    if ticket.status.value in ("completed", "wont_fix"):
        raise TicketAlreadyClosedError("Нельзя изменять оборудование закрытой заявки")

    appliance = repository.get_appliance(session, data.appliance_id)
    if appliance is None:
        raise ApplianceNotFoundError(f"Оборудование с id={data.appliance_id} не найдено")

    existing = repository.get_ticket_appliance(session, ticket_id, data.appliance_id)
    if existing is not None:
        raise ApplianceAlreadyAttachedError(
            f"Оборудование '{appliance.name}' уже прикреплено к этой заявке"
        )

    office_id = data.office_id
    if office_id is None:
        office_id = repository.find_ticket_default_office_id(session, ticket_id)
    if office_id is None:
        raise OfficeNotFoundError("Не удалось определить склад офиса для заявки")

    office = session.get(Office, office_id)
    if office is None:
        raise OfficeNotFoundError(f"Офис с id={office_id} не найден")

    # Lock stock row to avoid concurrent race condition on available stock
    stock_row = repository.get_office_stock(session, office_id, data.appliance_id, for_update=True)
    current_stock = stock_row.stock if stock_row is not None else 0
    reserved = repository.get_reserved_stock_for_office(session, office_id, data.appliance_id)
    available = current_stock - reserved

    if data.quantity > available:
        raise InsufficientStockError(
            f"Недостаточно доступного оборудования '{appliance.name}' "
            f"на складе офиса (доступно: {available}, запрошено: {data.quantity})"
        )

    created = repository.create_ticket_appliance(
        session, ticket_id, data.appliance_id, office_id, data.quantity
    )
    return TicketApplianceRead(
        ticket_id=ticket_id,
        appliance_id=appliance.id,
        appliance_name=appliance.name,
        appliance_type=appliance.type,
        unit=appliance.unit,
        office_id=office_id,
        quantity=created.quantity,
        created_at=created.created_at,
    )


def update_ticket_appliance(
    session: Session,
    ticket_id: int,
    appliance_id: int,
    data: TicketApplianceUpdate,
    current_user: UserRead | None = None,
) -> TicketApplianceRead:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise TicketNotFoundError(f"Заявка с id={ticket_id} не найдена")
    _check_foreman_ticket_access(session, ticket_id, current_user)

    if ticket.status.value in ("completed", "wont_fix"):
        raise TicketAlreadyClosedError("Нельзя изменять оборудование закрытой заявки")

    ta = repository.get_ticket_appliance(session, ticket_id, appliance_id)
    if ta is None:
        raise TicketApplianceNotFoundError("Оборудование не прикреплено к данной заявке")
    _check_allocation_in_office(session, ticket_id, appliance_id)

    appliance = repository.get_appliance(session, appliance_id)
    if appliance is None:
        raise ApplianceNotFoundError(f"Оборудование с id={appliance_id} не найдено")

    stock_row = repository.get_office_stock(session, ta.office_id, appliance_id, for_update=True)
    current_stock = stock_row.stock if stock_row is not None else 0
    reserved_excluding_this = repository.get_reserved_stock_for_office(
        session, ta.office_id, appliance_id, exclude_ticket_id=ticket_id
    )
    available_for_this = current_stock - reserved_excluding_this

    if data.quantity > available_for_this:
        raise InsufficientStockError(
            f"Недостаточно доступного оборудования '{appliance.name}' "
            f"на складе офиса (доступно: {available_for_this}, запрошено: {data.quantity})"
        )

    updated = repository.update_ticket_appliance_quantity(session, ta, data.quantity)
    return TicketApplianceRead(
        ticket_id=ticket_id,
        appliance_id=appliance.id,
        appliance_name=appliance.name,
        appliance_type=appliance.type,
        unit=appliance.unit,
        office_id=ta.office_id,
        quantity=updated.quantity,
        created_at=updated.created_at,
    )


def remove_ticket_appliance(
    session: Session,
    ticket_id: int,
    appliance_id: int,
    current_user: UserRead | None = None,
) -> None:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise TicketNotFoundError(f"Заявка с id={ticket_id} не найдена")
    _check_foreman_ticket_access(session, ticket_id, current_user)

    if ticket.status.value in ("completed", "wont_fix"):
        raise TicketAlreadyClosedError("Нельзя изменять оборудование закрытой заявки")

    ta = repository.get_ticket_appliance(session, ticket_id, appliance_id)
    if ta is None:
        raise TicketApplianceNotFoundError("Оборудование не прикреплено к данной заявке")
    _check_allocation_in_office(session, ticket_id, appliance_id)

    repository.delete_ticket_appliance(session, ta)


def on_ticket_status_completed(session: Session, ticket_id: int, actor_id: int) -> None:
    """Write off non-tool equipment exactly once, from the engineer's hands or the office."""
    inventory.consume_on_completion(session, ticket_id, actor_id)

"""Create and retrieve tickets without HTTP-specific exceptions."""

from sqlalchemy import RowMapping
from sqlalchemy.orm import Session

from app.core.planning_guard import lock_planning_mutation
from app.modules.locations.schemas import LocationRead
from app.modules.notifications.enums import NotificationKind
from app.modules.tickets import repository
from app.modules.tickets.enums import TicketStatus
from app.modules.tickets.schemas import TicketCreate, TicketFields, TicketRead
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead


class LocationNotFoundError(Exception):
    pass


class TicketNotFoundError(Exception):
    pass


class WorkerNotFoundError(Exception):
    pass


class WorkerOffLineError(Exception):
    pass


class PermissionDeniedError(Exception):
    pass


def _foreman_id(current_user: UserRead | None) -> int | None:
    return current_user.id if current_user and current_user.role == UserRole.FOREMAN else None


def get_ticket(
    session: Session, ticket_id: int, current_user: UserRead | None = None
) -> TicketRead:
    details = repository.find_ticket(session, ticket_id, foreman_id=_foreman_id(current_user))
    if details is None:
        raise TicketNotFoundError
    return _ticket_from_row(details)


def list_tickets(
    session: Session,
    *,
    status: TicketStatus | None,
    city_id: int | None,
    district_id: int | None,
    limit: int,
    offset: int,
    brigade_id: int | None = None,
    current_user: UserRead | None = None,
) -> list[TicketRead]:
    rows = repository.find_tickets(
        session,
        status=status.value if status is not None else None,
        city_id=city_id,
        district_id=district_id,
        limit=limit,
        offset=offset,
        brigade_id=brigade_id,
        foreman_id=_foreman_id(current_user),
    )
    return [_ticket_from_row(row) for row in rows]


def _ticket_from_row(details: RowMapping) -> TicketRead:
    """Build the same full response from either a single row or a row in a page."""
    return TicketRead(
        **TicketFields.model_validate(details).model_dump(),
        id=details["id"],
        created_at=details["created_at"],
        updated_at=details["updated_at"],
        assignee_ids=list(details["assignee_ids"]),
        location=LocationRead(
            id=details["location_id"],
            city_id=details["city_id"],
            city=details["city"],
            district_id=details["district_id"],
            district=details["district"],
            street_id=details["street_id"],
            street=details["street"],
            building_id=details["building_id"],
            building_number=details["building_number"],
            block=details["block"],
            entrance_id=details["entrance_id"],
            entrance_number=details["entrance_number"],
            floor=details["floor"],
            apartment=details["apartment"],
            latitude=details["latitude"],
            longitude=details["longitude"],
        ),
    )


def create_ticket(session: Session, data: TicketCreate) -> TicketRead:
    with session.begin():
        lock_planning_mutation(session)
        if repository.find_location_id(session, data.location_id) is None:
            raise LocationNotFoundError
        values = data.model_dump()
        values["status"] = data.status.value
        ticket_id = repository.add_ticket(session, values)
        # Build the response inside the transaction; a failed operation leaves no ticket.
        return get_ticket(session, ticket_id)


def replace_assignees(session: Session, ticket_id: int, worker_ids: list[int]) -> TicketRead:
    with session.begin():
        lock_planning_mutation(session)
        return replace_assignees_in_transaction(session, ticket_id, worker_ids)


def replace_assignees_in_transaction(
    session: Session, ticket_id: int, worker_ids: list[int]
) -> TicketRead:
    ticket = repository.lock_ticket(session, ticket_id)
    if ticket is None:
        raise TicketNotFoundError
    worker_line_statuses = repository.find_worker_line_statuses(session, worker_ids)
    if set(worker_line_statuses) != set(worker_ids):
        raise WorkerNotFoundError
    if not all(worker_line_statuses.values()):
        raise WorkerOffLineError
    from app.modules.appliances import inventory

    inventory.check_reassignment(session, ticket_id, worker_ids)
    new_worker_ids = repository.replace_assignees(session, ticket_id, worker_ids)
    for worker_id in new_worker_ids:
        repository.add_notification_events(
            session,
            [worker_id],
            kind=NotificationKind.TICKET_ASSIGNED,
            ticket_id=ticket_id,
            data={"title": ticket["title"], "worker_id": worker_id},
        )
    return get_ticket(session, ticket_id)


def update_ticket_status(
    session: Session,
    ticket_id: int,
    status: TicketStatus,
    current_user: UserRead,
) -> TicketRead:
    if current_user.role == UserRole.FOREMAN:
        raise PermissionDeniedError
    with session.begin():
        lock_planning_mutation(session)
        ticket = repository.lock_ticket(session, ticket_id)
        if ticket is None:
            raise TicketNotFoundError
        if current_user.role == UserRole.WORKER and not repository.is_worker_assigned(
            session, ticket_id, current_user.id
        ):
            raise PermissionDeniedError
        previous_status = ticket["status"]
        if previous_status == status.value:
            return get_ticket(session, ticket_id)
        repository.update_status(session, ticket_id, status.value)
        if status == TicketStatus.COMPLETED:
            from app.modules.appliances import service as appliances_service

            appliances_service.on_ticket_status_completed(session, ticket_id, current_user.id)
        repository.add_notification_events(
            session,
            repository.list_observer_ids(session),
            kind=NotificationKind.TICKET_STATUS_CHANGED,
            ticket_id=ticket_id,
            data={
                "title": ticket["title"],
                "previous_status": previous_status,
                "status": status.value,
                "actor_id": current_user.id,
            },
        )
        return get_ticket(session, ticket_id)

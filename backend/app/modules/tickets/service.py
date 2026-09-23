from datetime import UTC, datetime, timedelta

from sqlalchemy import RowMapping
from sqlalchemy.orm import Session

from app.core.planning_guard import lock_planning_mutation
from app.modules.locations.schemas import LocationRead
from app.modules.notifications.enums import NotificationKind
from app.modules.tickets import repository
from app.modules.tickets.enums import TicketCategory, TicketStatus
from app.modules.tickets.schemas import TicketCreate, TicketFields, TicketRead
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead
from app.modules.work_types import repository as work_types_repository


class LocationNotFoundError(Exception):
    pass


class TicketNotFoundError(Exception):
    pass


class WorkerNotFoundError(Exception):
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
    category = details.get("category")
    if category is not None and not isinstance(category, TicketCategory):
        category = TicketCategory(category)
    data = TicketFields.model_validate(details).model_dump()
    data.update(
        id=details["id"],
        work_type_id=details["work_type_id"],
        category=category or TicketCategory.REPAIR,
        priority=details.get("priority", 3),
        received_at=details.get("received_at") or details["created_at"],
        sla_deadline_at=details.get("sla_deadline_at"),
        required_transport_type=details.get("required_transport_type"),
        service_duration_source=details.get("service_duration_source"),
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
    return TicketRead(**data)


def create_ticket(session: Session, data: TicketCreate) -> TicketRead:
    with session.begin_nested() if session.in_transaction() else session.begin():
        lock_planning_mutation(session)
        if repository.find_location_id(session, data.location_id) is None:
            raise LocationNotFoundError
        values = data.model_dump()
        values["status"] = data.status.value

        # Resolve work_type_id and WorkType metadata
        work_type_id = data.work_type_id
        work_type_row = None
        if work_type_id is not None:
            work_type_row = work_types_repository.find_work_type(session, work_type_id)
            if work_type_row is None:
                raise ValueError("Вид работ не найден")
            if not values.get("work_type"):
                values["work_type"] = work_type_row["name"]
        elif data.work_type:
            work_type_id = work_types_repository.find_id_by_name(session, data.work_type)
            if work_type_id is None:
                work_type_id = work_types_repository.find_id_by_code(session, data.work_type)
            if work_type_id is not None:
                work_type_row = work_types_repository.find_work_type(session, work_type_id)
            else:
                # Create a dynamic work type for legacy/testing string
                category = "repair"
                lower_wt = data.work_type.lower()
                if "авар" in lower_wt:
                    category = "emergency"
                elif "подключ" in lower_wt or "настройк" in lower_wt:
                    category = "connection"
                elif "дозаказ" in lower_wt:
                    category = "additional"

                work_priority = (
                    1 if category == "emergency" else (2 if category == "connection" else 3)
                )
                work_type_id = work_types_repository.add_work_type(
                    session,
                    {
                        "name": data.work_type,
                        "travel_minutes": 20,
                        "work_minutes": 30,
                        "documents_minutes": 0,
                        "category": category,
                        "default_priority": work_priority,
                    },
                )
                work_type_row = work_types_repository.find_work_type(session, work_type_id)
            values["work_type_id"] = work_type_id

        # Defaults for category, priority, received_at, duration_source
        if not values.get("category"):
            values["category"] = (
                work_type_row["category"] if work_type_row else TicketCategory.REPAIR.value
            )
        elif isinstance(values["category"], TicketCategory):
            values["category"] = values["category"].value

        if not values.get("priority"):
            values["priority"] = work_type_row["default_priority"] if work_type_row else 3

        if not values.get("received_at"):
            values["received_at"] = datetime.now(UTC)

        if not values.get("sla_deadline_at") and values["category"] == "emergency":
            values["sla_deadline_at"] = values["received_at"] + timedelta(hours=24)

        if values.get("required_transport_type") is not None:
            values["required_transport_type"] = (
                values["required_transport_type"].value
                if hasattr(values["required_transport_type"], "value")
                else str(values["required_transport_type"])
            )

        ticket_id = repository.add_ticket(session, values)
        # Build the response inside the transaction; a failed operation leaves no ticket.
        return get_ticket(session, ticket_id)


def replace_assignees(session: Session, ticket_id: int, worker_ids: list[int]) -> TicketRead:
    with session.begin_nested() if session.in_transaction() else session.begin():
        lock_planning_mutation(session)
        return replace_assignees_in_transaction(session, ticket_id, worker_ids)


def replace_assignees_in_transaction(
    session: Session, ticket_id: int, worker_ids: list[int]
) -> TicketRead:
    ticket = repository.lock_ticket(session, ticket_id)
    if ticket is None:
        raise TicketNotFoundError
    if repository.find_worker_ids(session, worker_ids) != set(worker_ids):
        raise WorkerNotFoundError
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
    with session.begin_nested() if session.in_transaction() else session.begin():
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

            appliances_service.on_ticket_status_completed(session, ticket_id)
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

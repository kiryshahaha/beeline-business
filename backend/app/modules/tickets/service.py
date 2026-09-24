from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session

from app.core.planning_guard import lock_planning_mutation
from app.modules.execution import repository as execution_repository
from app.modules.execution import service as execution_service
from app.modules.execution.enums import TicketLifecycleState, WorkEventType
from app.modules.execution.schemas import ExecutionCommand
from app.modules.locations.schemas import LocationRead
from app.modules.notifications.enums import NotificationKind
from app.modules.tickets import repository
from app.modules.tickets.enums import TicketCategory, TicketStatus
from app.modules.tickets.schemas import TicketCreate, TicketFields, TicketRead
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead
from app.modules.work_types import repository as work_types_repository

MOSCOW = ZoneInfo("Europe/Moscow")


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


def _foreman_id(current_user: UserRead) -> int | None:
    return current_user.id if current_user.role == UserRole.FOREMAN else None


def _worker_id(current_user: UserRead) -> int | None:
    return current_user.id if current_user.role == UserRole.WORKER else None


def get_ticket(session: Session, ticket_id: int, current_user: UserRead) -> TicketRead:
    details = repository.find_ticket(
        session,
        ticket_id,
        foreman_id=_foreman_id(current_user),
        worker_id=_worker_id(current_user),
    )
    if details is None:
        raise TicketNotFoundError
    return _ticket_from_row(details)


def get_ticket_unscoped(session: Session, ticket_id: int) -> TicketRead:
    """Read a ticket inside a service path that already authorized its caller."""
    details = repository.find_ticket(session, ticket_id)
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
    current_user: UserRead,
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
        worker_id=_worker_id(current_user),
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
        state=details["state"],
        revision=details["revision"],
        execution_cycle=details["execution_cycle"],
        actual_started_at=details["actual_started_at"],
        actual_completed_at=details["actual_completed_at"],
        cancel_reason=details["cancel_reason"],
        last_event_id=details["last_event_id"],
        created_at=details["created_at"],
        updated_at=details["updated_at"],
        assigned_worker_id=details["assigned_worker_id"],
        is_pinned=details["is_pinned"],
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


def create_ticket(
    session: Session,
    data: TicketCreate,
    *,
    actor_id: int | None = None,
    idempotency_key: str | None = None,
) -> TicketRead:
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

        values["lifecycle_state"] = {
            TicketStatus.PLANNED: TicketLifecycleState.WAITING_ASSIGNMENT.value,
            TicketStatus.IN_PROGRESS: TicketLifecycleState.IN_PROGRESS.value,
            TicketStatus.COMPLETED: TicketLifecycleState.COMPLETED.value,
            TicketStatus.WONT_FIX: TicketLifecycleState.CANCELLED.value,
        }[data.status]
        ticket_id = repository.add_ticket(session, values)
        district_id = session.execute(
            text(
                """
                SELECT building.district_id
                FROM tickets AS ticket
                JOIN locations AS location ON location.id = ticket.location_id
                JOIN buildings AS building ON building.id = location.building_id
                WHERE ticket.id = :ticket_id
                """
            ),
            {"ticket_id": ticket_id},
        ).scalar_one()
        event_id = execution_repository.insert_work_event(
            session,
            event_type=WorkEventType.NEW_TICKET.value,
            ticket_id=ticket_id,
            worker_id=None,
            district_id=district_id,
            route_date=data.visit_window_start.astimezone(MOSCOW).date(),
            occurred_at=datetime.now(UTC),
            actor_id=actor_id,
            reason=None,
            previous_state=None,
            new_state=values["lifecycle_state"],
            before_revision=None,
            after_revision=1,
            idempotency_key=idempotency_key or f"ticket-create:{ticket_id}",
            payload={"source": "ticket_create"},
        )
        execution_repository.attach_last_event(session, ticket_id, event_id)
        # Build the response inside the transaction; a failed operation leaves no ticket.
        return get_ticket_unscoped(session, ticket_id)


def update_assignment(
    session: Session,
    ticket_id: int,
    worker_id: int | None,
    is_pinned: bool,
    *,
    actor_id: int | None = None,
) -> TicketRead:
    with session.begin_nested() if session.in_transaction() else session.begin():
        lock_planning_mutation(session)
        return update_assignment_in_transaction(
            session, ticket_id, worker_id, is_pinned, actor_id=actor_id
        )


def update_assignment_in_transaction(
    session: Session,
    ticket_id: int,
    worker_id: int | None,
    is_pinned: bool,
    *,
    actor_id: int | None = None,
) -> TicketRead:
    ticket = repository.lock_ticket(session, ticket_id)
    if ticket is None:
        raise TicketNotFoundError
    if worker_id is not None:
        worker_line_statuses = repository.find_worker_line_statuses(session, [worker_id])
        if worker_id not in worker_line_statuses:
            raise WorkerNotFoundError
        if not worker_line_statuses[worker_id]:
            raise WorkerOffLineError
    from app.modules.appliances import inventory

    inventory.check_reassignment(session, ticket_id, [worker_id] if worker_id else [])
    old_worker_id, new_worker_id = repository.update_assignment(
        session, ticket_id, worker_id, is_pinned
    )

    if new_worker_id is not None and new_worker_id != old_worker_id:
        repository.add_notification_events(
            session,
            [new_worker_id],
            kind=NotificationKind.TICKET_ASSIGNED,
            ticket_id=ticket_id,
            data={"title": ticket["title"], "worker_id": new_worker_id},
        )

    # Generate execution event if assignment changed
    if (
        new_worker_id != old_worker_id
        and TicketLifecycleState(ticket["lifecycle_state"])
        == TicketLifecycleState.WAITING_ASSIGNMENT
        and new_worker_id is not None
    ):
        command = ExecutionCommand.model_construct(
            expected_revision=ticket["revision"],
            occurred_at=datetime.now(UTC),
            reason=None,
            expected_available_at=None,
            payload={"worker_ids": [new_worker_id]},
        )
        assignment_key = f"assign:{ticket_id}:{ticket['revision']}:{new_worker_id}"
        execution_service.apply_ticket_event(
            session,
            ticket_id,
            WorkEventType.ASSIGN,
            command,
            actor_id=actor_id,
            idempotency_key=assignment_key,
        )
    return get_ticket_unscoped(session, ticket_id)


def update_ticket_status(
    session: Session,
    ticket_id: int,
    status: TicketStatus,
    current_user: UserRead,
    *,
    expected_revision: int | None = None,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> TicketRead:
    if current_user.role != UserRole.OBSERVER:
        raise PermissionDeniedError
    with session.begin_nested() if session.in_transaction() else session.begin():
        lock_planning_mutation(session)
        ticket = repository.lock_ticket(session, ticket_id)
        if ticket is None:
            raise TicketNotFoundError
        if ticket["status"] == status.value:
            return get_ticket_unscoped(session, ticket_id)
        event_type = {
            TicketStatus.IN_PROGRESS: WorkEventType.START,
            TicketStatus.COMPLETED: WorkEventType.COMPLETE,
        }.get(status)
        if event_type is None:
            raise PermissionDeniedError
        command = ExecutionCommand.model_construct(
            expected_revision=expected_revision,
            occurred_at=datetime.now(UTC),
            reason=reason,
            expected_available_at=None,
            payload={"legacy_status": status.value},
        )
        result = execution_service.apply_ticket_event(
            session,
            ticket_id,
            event_type,
            command,
            actor_id=current_user.id,
            idempotency_key=idempotency_key
            or f"legacy-status:{ticket_id}:{status.value}:{ticket['revision']}",
            compatibility=True,
        )
        return result.ticket


def preview_assignment(session: Session, ticket_id: int, worker_id: int):
    from datetime import datetime

    from app.core.config import get_settings
    from app.modules.planning.eligibility import MOSCOW, prepare
    from app.modules.planning.policy import execution_policy
    from app.modules.planning.repository import load_snapshot
    from app.modules.planning.schemas import PreviewRequest
    from app.modules.tickets.schemas import AssignmentPreviewResponse

    ticket = repository.lock_ticket(session, ticket_id)
    if ticket is None:
        raise TicketNotFoundError

    worker_line_statuses = repository.find_worker_line_statuses(session, [worker_id])
    if worker_id not in worker_line_statuses:
        raise WorkerNotFoundError

    district_id = session.execute(
        text(
            """
            SELECT building.district_id
            FROM locations AS location
            JOIN buildings AS building ON building.id = location.building_id
            WHERE location.id = :location_id
            """
        ),
        {"location_id": ticket["location_id"]},
    ).scalar()

    request = PreviewRequest(
        route_date=ticket["visit_window_start"].astimezone(MOSCOW).date().isoformat(),
        district_id=district_id,
        ticket_ids=[ticket_id],
        worker_ids=[worker_id],
        allow_partial=True,
    )

    settings = get_settings()
    policy = execution_policy(settings)
    snapshot = load_snapshot(
        session,
        request,
        policy_snapshot={
            "policy_version": policy.policy_version,
            "planning_policy": policy.model_dump(mode="json"),
        },
    )
    # Remove existing assignment of THIS ticket so prepare doesn't reject with 'already_assigned'
    snapshot["assignments"] = [a for a in snapshot["assignments"] if a["ticket_id"] != ticket_id]

    prepared = prepare(snapshot, datetime.now(UTC))

    violations = []

    worker_excluded = [
        w for w in prepared.get("excluded_workers", []) if w["worker_id"] == worker_id
    ]
    if worker_excluded:
        violations.append(worker_excluded[0]["reason"])

    ticket_unassigned = [t for t in prepared.get("unassigned", []) if t["ticket_id"] == ticket_id]
    if ticket_unassigned:
        violations.append(ticket_unassigned[0]["reason"])

    return AssignmentPreviewResponse(
        is_eligible=len(violations) == 0,
        violations=violations,
        route_shift_minutes=0,
        sla_violations_added=0,
    )

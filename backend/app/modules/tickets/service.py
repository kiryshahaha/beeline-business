import math
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session

from app.core.audit import set_assignment_origin
from app.core.planning_guard import lock_planning_mutation
from app.db.models import WorkType, WorkTypePlanningRule
from app.modules.execution import repository as execution_repository
from app.modules.execution import service as execution_service
from app.modules.execution.enums import TicketLifecycleState, WorkEventType
from app.modules.execution.schemas import ExecutionCommand
from app.modules.locations.schemas import LocationRead
from app.modules.notifications.enums import NotificationKind
from app.modules.tickets import repository
from app.modules.tickets.enums import TicketCategory, TicketStatus
from app.modules.tickets.schemas import (
    TicketCreate,
    TicketFields,
    TicketRead,
    TicketSlaEstimateRead,
)
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead
from app.modules.work_types import repository as work_types_repository

MOSCOW = ZoneInfo("Europe/Moscow")


class LocationNotFoundError(Exception):
    pass


class WorkTypeNotFoundError(Exception):
    pass


class InvalidSlaDeadlineError(Exception):
    pass


class SlaEstimationConfigurationError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class TicketNotFoundError(Exception):
    pass


class WorkerNotFoundError(Exception):
    pass


class WorkerOffLineError(Exception):
    pass


class PermissionDeniedError(Exception):
    pass


class ServiceAreaMismatchError(Exception):
    pass


def _foreman_id(current_user: UserRead | None) -> int | None:
    return current_user.id if current_user and current_user.role == UserRole.FOREMAN else None


def _worker_id(current_user: UserRead | None) -> int | None:
    return current_user.id if current_user and current_user.role == UserRole.WORKER else None


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


def estimate_sla(
    session: Session,
    ticket_id: int,
    current_user: UserRead,
    *,
    previous_ticket_end_at: datetime,
    travel_minutes: int,
) -> TicketSlaEstimateRead:
    ticket = get_ticket(session, ticket_id, current_user)
    if ticket.work_type_id is None:
        raise SlaEstimationConfigurationError("work_type_unlinked")
    work_type = session.get(WorkType, ticket.work_type_id)
    rule = session.get(WorkTypePlanningRule, ticket.work_type_id)
    if work_type is None:
        raise SlaEstimationConfigurationError("work_type_not_found")
    if rule is None:
        raise SlaEstimationConfigurationError("work_type_planning_rule_missing")

    duration_source = rule.service_duration_source
    if duration_source == "ticket_estimate":
        duration_minutes = ticket.estimated_duration_minutes
    elif duration_source == "work_norm":
        duration_minutes = work_type.work_minutes + work_type.documents_minutes
    else:
        raise SlaEstimationConfigurationError("invalid_service_duration_source")

    estimated_arrival_at = previous_ticket_end_at + timedelta(minutes=travel_minutes)
    estimated_service_start_at = max(
        estimated_arrival_at,
        ticket.visit_window_start,
        ticket.received_at,
    )
    estimated_service_end_at = estimated_service_start_at + timedelta(minutes=duration_minutes)
    arrival_late_minutes = max(
        0,
        math.ceil((estimated_arrival_at - ticket.visit_window_end).total_seconds() / 60),
    )
    sla_late_minutes = (
        max(
            0,
            math.ceil((estimated_service_end_at - ticket.sla_deadline_at).total_seconds() / 60),
        )
        if ticket.sla_deadline_at is not None
        else 0
    )

    return TicketSlaEstimateRead(
        ticket_id=ticket.id,
        estimated_arrival_at=estimated_arrival_at,
        estimated_service_start_at=estimated_service_start_at,
        estimated_service_end_at=estimated_service_end_at,
        visit_window_end_at=ticket.visit_window_end,
        arrival_status="late" if arrival_late_minutes else "within_window",
        arrival_late_minutes=arrival_late_minutes,
        sla_deadline_at=ticket.sla_deadline_at,
        sla_status=(
            "not_configured"
            if ticket.sla_deadline_at is None
            else "at_risk"
            if sla_late_minutes
            else "on_time"
        ),
        sla_late_minutes=sla_late_minutes,
        duration_minutes=duration_minutes,
        duration_source=duration_source,
    )


def list_tickets(
    session: Session,
    *,
    status: TicketStatus | None,
    city_id: int | None,
    service_area_id: int | None,
    limit: int,
    offset: int,
    brigade_id: int | None = None,
    current_user: UserRead,
) -> list[TicketRead]:
    rows = repository.find_tickets(
        session,
        status=status.value if status is not None else None,
        city_id=city_id,
        service_area_id=service_area_id,
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
        work_type=details["work_type"],
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
            service_area_id=details["service_area_id"],
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

        work_type_id = data.work_type_id
        work_type_row = work_types_repository.find_work_type(session, work_type_id)
        if work_type_row is None:
            raise WorkTypeNotFoundError
        values["work_type_id"] = work_type_id
        values["work_type"] = work_type_row["name"]
        values["service_duration_source"] = None

        # Defaults for category, priority, received_at, duration_source
        if values.get("category") is None:
            values["category"] = work_type_row["category"]
        elif isinstance(values["category"], TicketCategory):
            values["category"] = values["category"].value

        if values.get("priority") is None:
            values["priority"] = work_type_row["default_priority"]

        if not values.get("received_at"):
            values["received_at"] = datetime.now(UTC)
        if (
            values.get("sla_deadline_at") is not None
            and values["sla_deadline_at"] <= values["received_at"]
        ):
            raise InvalidSlaDeadlineError

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
        if not values.get("service_area_id"):
            resolved_area = session.execute(
                text(
                    """
                    SELECT b.service_area_id
                    FROM locations AS loc
                    JOIN buildings AS b ON b.id = loc.building_id
                    WHERE loc.id = :location_id
                    LIMIT 1
                    """
                ),
                {"location_id": values["location_id"]},
            ).scalar_one_or_none()
            values["service_area_id"] = resolved_area
        ticket_id = repository.add_ticket(session, values)
        service_area_id = session.execute(
            text(
                """
                SELECT building.service_area_id
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
            service_area_id=service_area_id,
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


async def update_assignment(
    session: Session,
    ticket_id: int,
    worker_id: int | None,
    is_pinned: bool,
    *,
    actor_id: int | None = None,
    engine, settings, provider, planner, clock
) -> TicketRead:
    # Validate assignment
    if worker_id is not None:
        preview_res = await preview_assignment(
            session, ticket_id, worker_id, engine, settings, provider, planner, clock
        )
        if not preview_res.is_eligible:
            raise ValueError(f"Assignment ineligible: {preview_res.violations}")

    from fastapi.concurrency import run_in_threadpool
    old_worker_id, new_worker_id, route_date, w_area, old_w_area = await run_in_threadpool(
        _update_assignment_sync_part, session, ticket_id, worker_id, is_pinned, actor_id
    )

    if new_worker_id is not None:
        await _recalculate_route(engine, settings, provider, planner, clock, new_worker_id, route_date, w_area, actor_id)
    if old_worker_id is not None and old_worker_id != new_worker_id:
        await _recalculate_route(engine, settings, provider, planner, clock, old_worker_id, route_date, old_w_area, actor_id)

    return await run_in_threadpool(get_ticket_unscoped, session, ticket_id)

def _update_assignment_sync_part(session, ticket_id, worker_id, is_pinned, actor_id):
    from app.modules.tickets.models import Ticket
    from datetime import datetime, timedelta, time
    from zoneinfo import ZoneInfo
    MOSCOW = ZoneInfo("Europe/Moscow")

    with session.begin_nested() if session.in_transaction() else session.begin():
        lock_planning_mutation(session)

        # Get old worker id before
        t = repository.lock_ticket(session, ticket_id)
        if t is None:
            raise TicketNotFoundError
        old_worker_id = t["assigned_worker_id"]
        route_date = t["visit_window_start"].astimezone(MOSCOW).date()
        
        # update assignment
        res = update_assignment_in_transaction(
            session, ticket_id, worker_id, is_pinned, actor_id=actor_id, source="manual"
        )
        # return worker areas
        def get_area(w_id):
            if w_id is None: return None
            w = session.execute(text("SELECT service_area_id FROM workers WHERE user_id = :user_id"), {"user_id": w_id}).mappings().first()
            if w and w["service_area_id"]: return w["service_area_id"]
            return session.execute(text("SELECT bld.service_area_id FROM brigade_members bm JOIN brigades b ON b.id = bm.brigade_id JOIN offices off ON off.id = b.office_id JOIN locations loc ON loc.id = off.location_id JOIN buildings bld ON bld.id = loc.building_id WHERE bm.worker_id = :wid LIMIT 1"), {"wid": w_id}).scalar_one_or_none()
        
        w_area = get_area(worker_id)
        old_w_area = get_area(old_worker_id)

        return old_worker_id, worker_id, route_date, w_area, old_w_area

async def _recalculate_route(engine, settings, provider, planner, clock, worker_id, route_date, service_area_id, actor_id):
    from sqlalchemy.orm import Session
    from sqlalchemy import select
    from datetime import datetime, timedelta, time, UTC
    from zoneinfo import ZoneInfo
    from app.modules.tickets.models import Ticket
    from app.modules.tickets.enums import TicketStatus
    from app.modules.planning.schemas import PreviewRequest
    from app.modules.planning.service import preview, publish_revision, build_plan_state, save_routes_in_transaction
    from app.modules.routing.schemas import RouteCreate

    MOSCOW = ZoneInfo("Europe/Moscow")
    start_of_day = datetime.combine(route_date, time.min, tzinfo=MOSCOW).astimezone(UTC)
    end_of_day = start_of_day + timedelta(days=1)

    def get_tickets():
        with Session(engine) as session:
            return list(session.scalars(
                select(Ticket.id)
                .where(
                    Ticket.assigned_worker_id == worker_id,
                    Ticket.visit_window_start >= start_of_day,
                    Ticket.visit_window_start < end_of_day,
                    Ticket.status.in_([TicketStatus.NEW.value, TicketStatus.ASSIGNED.value, TicketStatus.IN_PROGRESS.value])
                )
            ))

    from fastapi.concurrency import run_in_threadpool
    ticket_ids = await run_in_threadpool(get_tickets)

    if not ticket_ids:
        # publish empty route
        with Session(engine) as session, session.begin():
            publish_revision(
                session,
                service_area_id=service_area_id,
                route_date=route_date,
                actor_id=actor_id or 0,
                reason="manual_unassignment",
                fingerprint="recalculated",
                plan_state=build_plan_state({"routes": []}, {worker_id: None}),
                result={},
                at=clock(),
                plan_id=None
            )
        return

    request = PreviewRequest(
        route_date=route_date.isoformat(),
        service_area_id=service_area_id,
        ticket_ids=ticket_ids,
        worker_ids=[worker_id],
        allow_partial=True,
    )
    result = await preview(engine, request, actor_id or 0, settings, provider, planner, clock)
    if result.get("routes"):
        r = result["routes"][0]
        from pydantic import BaseModel
        stops_dump = [{"location_id": s["location_id"], "ticket_id": s.get("ticket_id"), "arrival_at": s["arrival_at"], "service_start_at": s["service_start_at"], "service_end_at": s["service_end_at"], "waiting_minutes": s["waiting_minutes"], "effective_service_minutes": s["effective_service_minutes"], "duration_source": s["duration_source"]} for s in r["stops"]]
        path_props = {"kind": "path", "source": "provided", "legs": r["legs"]} if r.get("legs") else None
        rc = RouteCreate.model_validate({"worker_id": r["worker_id"], "route_date": route_date, "stops": stops_dump, "geometry": r.get("geometry"), "path_properties": path_props})
        def save():
            with Session(engine) as session, session.begin():
                saved = save_routes_in_transaction(session, [rc])
                publish_revision(
                    session,
                    service_area_id=service_area_id,
                    route_date=route_date,
                    actor_id=actor_id or 0,
                    reason="manual_assignment",
                    fingerprint="recalculated",
                    plan_state=build_plan_state({"routes": [r]}, {worker_id: saved[0].id}),
                    result={},
                    at=clock(),
                    plan_id=None
                )
        await run_in_threadpool(save)


def update_assignment_in_transaction(
    session: Session,
    ticket_id: int,
    worker_id: int | None,
    is_pinned: bool,
    *,
    actor_id: int | None = None,
    source: str | None = None,
) -> TicketRead:
    """Change the assignee inside the caller's transaction.

    The manual endpoint states `source="manual"`; applying a plan is the only other
    caller, so an unstated source is recorded as `plan`.
    """
    ticket = repository.lock_ticket(session, ticket_id)
    if ticket is None:
        raise TicketNotFoundError
    if worker_id is not None:
        worker_line_statuses = repository.find_worker_line_statuses(session, [worker_id])
        if worker_id not in worker_line_statuses:
            raise WorkerNotFoundError
        if not worker_line_statuses[worker_id]:
            raise WorkerOffLineError

        t_area = ticket.get("service_area_id")
        if t_area is None and ticket.get("location_id"):
            t_area = session.execute(
                text(
                    """
                    SELECT b.service_area_id
                    FROM locations AS loc
                    JOIN buildings AS b ON b.id = loc.building_id
                    WHERE loc.id = :location_id
                    LIMIT 1
                    """
                ),
                {"location_id": ticket["location_id"]},
            ).scalar_one_or_none()

        worker_row = (
            session.execute(
                text("SELECT service_area_id FROM workers WHERE user_id = :user_id"),
                {"user_id": worker_id},
            )
            .mappings()
            .first()
        )
        w_area = worker_row["service_area_id"] if worker_row else None
        if w_area is None:
            w_area = session.execute(
                text(
                    """
                    SELECT bld.service_area_id
                    FROM brigade_members AS bm
                    JOIN brigades AS b ON b.id = bm.brigade_id
                    JOIN offices AS off ON off.id = b.office_id
                    JOIN locations AS loc ON loc.id = off.location_id
                    JOIN buildings AS bld ON bld.id = loc.building_id
                    WHERE bm.worker_id = :wid
                    LIMIT 1
                    """
                ),
                {"wid": worker_id},
            ).scalar_one_or_none()

        if t_area is not None and w_area is not None and t_area != w_area:
            raise ServiceAreaMismatchError
    from app.modules.appliances import inventory

    inventory.check_reassignment(session, ticket_id, [worker_id] if worker_id else [])
    set_assignment_origin(session, actor_id=actor_id, source=source or "plan")
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
            TicketStatus.WONT_FIX: WorkEventType.CANCEL_TICKET,
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


async def preview_assignment(
    session: Session, ticket_id: int, worker_id: int, engine, settings, provider, planner, clock
):
    from datetime import datetime, timedelta, time
    from zoneinfo import ZoneInfo
    from sqlalchemy import select, text
    from app.modules.planning.schemas import PreviewRequest
    from app.modules.tickets.schemas import AssignmentPreviewResponse
    from app.modules.tickets.models import Ticket
    from app.modules.tickets.enums import TicketStatus
    from app.modules.planning.service import preview

    ticket = repository.lock_ticket(session, ticket_id)
    if ticket is None:
        raise TicketNotFoundError

    worker_line_statuses = repository.find_worker_line_statuses(session, [worker_id])
    if worker_id not in worker_line_statuses:
        raise WorkerNotFoundError

    MOSCOW = ZoneInfo("Europe/Moscow")
    route_date = ticket["visit_window_start"].astimezone(MOSCOW).date()
    start_of_day = datetime.combine(route_date, time.min, tzinfo=MOSCOW).astimezone(UTC)
    end_of_day = start_of_day + timedelta(days=1)

    worker_ticket_ids = list(session.scalars(
        select(Ticket.id)
        .where(
            Ticket.assigned_worker_id == worker_id,
            Ticket.visit_window_start >= start_of_day,
            Ticket.visit_window_start < end_of_day,
            Ticket.status.in_([TicketStatus.NEW.value, TicketStatus.ASSIGNED.value, TicketStatus.IN_PROGRESS.value])
        )
    ))

    ticket_ids_to_plan = list(set(worker_ticket_ids + [ticket_id]))

    service_area_id = session.execute(
        text(
            """
            SELECT building.service_area_id
            FROM locations AS location
            JOIN buildings AS building ON building.id = location.building_id
            WHERE location.id = :location_id
            """
        ),
        {"location_id": ticket["location_id"]},
    ).scalar()

    request = PreviewRequest(
        route_date=route_date.isoformat(),
        service_area_id=service_area_id,
        ticket_ids=ticket_ids_to_plan,
        worker_ids=[worker_id],
        allow_partial=True,
    )

    result = await preview(engine, request, ticket["created_by"], settings, provider, planner, clock)

    unassigned = [u for u in result.get("unassigned", []) if u["ticket_id"] == ticket_id]
    is_eligible = len(unassigned) == 0
    violations = []
    if not is_eligible:
        for u in unassigned:
            violations.append(u["reason"]["code"])

    old_travel = 0
    old_service = 0
    old_sla = 0
    new_travel = 0
    new_service = 0
    new_sla = 0

    def count_sla_violations(r, ticket_ids_in_route):
        # r is PlannedRoute
        violations_count = 0
        # we need tickets sla
        tickets_sla = {
            t.id: t.sla_deadline_at
            for t in session.scalars(select(Ticket).where(Ticket.id.in_(ticket_ids_in_route)))
        }
        for stop in r['stops']:
            sla_deadline = tickets_sla.get(stop['ticket_id'])
            if sla_deadline and datetime.fromisoformat(stop['service_end_at']) and datetime.fromisoformat(stop['service_end_at']) > sla_deadline:
                violations_count += 1
        return violations_count

    if result.get("routes"):
        r = result["routes"][0]
        new_travel = r['travel_minutes']
        new_service = r['service_minutes']
        new_sla = count_sla_violations(r, ticket_ids_to_plan)

    if worker_ticket_ids and ticket_id not in worker_ticket_ids:
        old_req = PreviewRequest(
            route_date=route_date.isoformat(),
            service_area_id=service_area_id,
            ticket_ids=worker_ticket_ids,
            worker_ids=[worker_id],
            allow_partial=True,
        )
        old_res = await preview(engine, old_req, ticket["created_by"], settings, provider, planner, clock)
        if old_res.get("routes"):
            r = old_res["routes"][0]
            old_travel = r['travel_minutes']
            old_service = r['service_minutes']
            old_sla = count_sla_violations(r, worker_ticket_ids)

    new_duration = new_travel + new_service
    old_duration = old_travel + old_service
    route_shift_minutes = new_duration - old_duration
    sla_violations_added = max(0, new_sla - old_sla)

    return AssignmentPreviewResponse(
        is_eligible=is_eligible,
        violations=violations,
        route_shift_minutes=route_shift_minutes,
        sla_violations_added=sla_violations_added,
    )

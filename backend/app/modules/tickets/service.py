import math
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import RowMapping, select, text
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
from app.modules.routing.service import save_routes_in_transaction
from app.modules.tickets import repository
from app.modules.tickets.enums import TicketCategory, TicketStatus
from app.modules.tickets.models import Ticket
from app.modules.tickets.schemas import (
    AssignmentPreviewResponse,
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


class AssignmentValidationError(Exception):
    def __init__(self, violations: list[dict]):
        self.violations = violations
        super().__init__("manual_assignment_rejected")


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
    if session.in_transaction():
        session.rollback()
    with session.begin():
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
    engine,
    settings,
    provider,
    planner,
    clock,
) -> TicketRead:
    if not getattr(settings, "planning_enabled", False) or provider is None or planner is None:
        return _update_assignment_without_planner(
            session,
            ticket_id,
            worker_id,
            is_pinned,
            actor_id=actor_id,
        )

    ticket_info = _manual_assignment_ticket_info(session, ticket_id)
    if ticket_info is None:
        raise TicketNotFoundError

    old_worker_id = ticket_info["assigned_worker_id"]
    route_date = ticket_info["route_date"]
    service_area_id = ticket_info["service_area_id"]
    actor = actor_id or 0

    new_preview = None
    if worker_id is not None:
        new_preview = await preview_assignment(
            session,
            ticket_id,
            worker_id,
            engine,
            settings,
            provider,
            planner,
            clock,
            actor_id=actor,
        )
        if not new_preview.is_eligible:
            raise AssignmentValidationError(new_preview.violations)

    affected_workers = {worker for worker in (old_worker_id, worker_id) if worker is not None}
    route_publics: dict[int, dict | None] = {}
    route_creates = []
    for affected_worker_id in sorted(affected_workers):
        planned_ticket_ids = _manual_worker_ticket_ids(
            session,
            affected_worker_id,
            route_date,
            include_ticket_id=ticket_id if affected_worker_id == worker_id else None,
            exclude_ticket_id=(
                ticket_id
                if affected_worker_id == old_worker_id and old_worker_id != worker_id
                else None
            ),
        )
        if not planned_ticket_ids:
            route_publics[affected_worker_id] = None
            continue
        route_public = await _manual_route_preview(
            engine,
            settings,
            provider,
            planner,
            clock,
            actor,
            route_date,
            service_area_id,
            affected_worker_id,
            planned_ticket_ids,
        )
        route_publics[affected_worker_id] = route_public
        route_creates.extend(_route_creates_from_public(route_public))

    if session.in_transaction():
        session.rollback()
    with session.begin():
        lock_planning_mutation(session)
        result = update_assignment_in_transaction(
            session,
            ticket_id,
            worker_id,
            is_pinned,
            actor_id=actor_id,
            source="manual",
        )
        if worker_id is None:
            ticket = session.get(Ticket, ticket_id)
            if ticket is not None:
                ticket.planned_start_at = None
                ticket.planned_end_at = None
        saved_routes = save_routes_in_transaction(session, route_creates) if route_creates else []
        _apply_manual_route_times(session, route_publics)
        _publish_manual_assignment_revision(
            session,
            service_area_id=service_area_id,
            route_date=route_date,
            actor_id=actor,
            affected_workers=affected_workers,
            route_publics=route_publics,
            saved_routes=saved_routes,
            ticket_id=ticket_id,
            at=clock(),
        )
        return result


def _update_assignment_without_planner(
    session: Session,
    ticket_id: int,
    worker_id: int | None,
    is_pinned: bool,
    *,
    actor_id: int | None,
) -> TicketRead:
    if session.in_transaction():
        session.rollback()
    with session.begin():
        lock_planning_mutation(session)
        return update_assignment_in_transaction(
            session,
            ticket_id,
            worker_id,
            is_pinned,
            actor_id=actor_id,
            source="manual",
        )


def _manual_assignment_ticket_info(session: Session, ticket_id: int) -> dict | None:
    row = (
        session.execute(
            text(
                """
                SELECT
                    t.id,
                    t.assigned_worker_id,
                    COALESCE(t.service_area_id, building.service_area_id) AS service_area_id,
                    (COALESCE(t.planned_start_at, t.visit_window_start)
                        AT TIME ZONE 'Europe/Moscow')::date AS route_date
                FROM tickets AS t
                JOIN locations AS location ON location.id = t.location_id
                JOIN buildings AS building ON building.id = location.building_id
                WHERE t.id = :ticket_id
                """
            ),
            {"ticket_id": ticket_id},
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


def _manual_worker_ticket_ids(
    session: Session,
    worker_id: int,
    route_date,
    *,
    include_ticket_id: int | None,
    exclude_ticket_id: int | None,
) -> list[int]:
    start_of_day = datetime.combine(route_date, datetime.min.time(), MOSCOW).astimezone(UTC)
    end_of_day = start_of_day + timedelta(days=1)
    ids = set(
        session.scalars(
            select(Ticket.id)
            .where(
                Ticket.assigned_worker_id == worker_id,
                Ticket.visit_window_start >= start_of_day,
                Ticket.visit_window_start < end_of_day,
                Ticket.status.in_(
                    [
                        TicketStatus.PLANNED.value,
                        TicketStatus.IN_PROGRESS.value,
                    ]
                ),
            )
            .order_by(Ticket.id)
        )
    )
    if include_ticket_id is not None:
        ids.add(include_ticket_id)
    if exclude_ticket_id is not None:
        ids.discard(exclude_ticket_id)
    return sorted(ids)


def _manual_snapshot_transform(ticket_ids: list[int]):
    planned = set(ticket_ids)

    def transform(snapshot: dict) -> dict:
        snapshot = dict(snapshot)
        snapshot["assignments"] = [
            assignment
            for assignment in snapshot.get("assignments", [])
            if assignment["ticket_id"] not in planned
        ]
        snapshot["busy_tickets"] = [
            ticket for ticket in snapshot.get("busy_tickets", []) if ticket["id"] not in planned
        ]
        return snapshot

    return transform


async def _manual_route_preview(
    engine,
    settings,
    provider,
    planner,
    clock,
    actor_id: int,
    route_date,
    service_area_id: int | None,
    worker_id: int,
    ticket_ids: list[int],
) -> dict:
    from uuid import UUID

    from sqlalchemy.orm import Session

    from app.modules.planning.models import PlanningPlan
    from app.modules.planning.schemas import PreviewRequest
    from app.modules.planning.service import preview

    request = PreviewRequest(
        route_date=route_date,
        service_area_id=service_area_id,
        ticket_ids=ticket_ids,
        worker_ids=[worker_id],
        allow_partial=True,
    )
    public = await preview(
        engine,
        request,
        actor_id,
        settings,
        provider,
        planner,
        clock,
        snapshot_transform=_manual_snapshot_transform(ticket_ids),
    )
    with Session(engine) as session:
        stored = session.get(PlanningPlan, UUID(public["plan_id"]))
        route_creates = stored.result_snapshot["route_creates"] if stored is not None else []
    return {**public, "_route_creates": route_creates}


def _route_creates_from_public(public: dict | None):
    if public is None:
        return []
    if "_route_creates" in public:
        from app.modules.routing.schemas import RouteCreate

        return [RouteCreate.model_validate(route) for route in public["_route_creates"]]

    from app.modules.routing.schemas import RouteCreate

    creates = []
    for route in public.get("routes", []):
        path_properties = None
        if route.get("legs"):
            path_properties = {
                "kind": "path",
                "source": "geoapify",
                "mode": route["routing_mode"],
                "legs": route["legs"],
            }
        creates.append(
            RouteCreate.model_validate(
                {
                    "worker_id": route["worker_id"],
                    "route_date": public["route_date"],
                    "stops": [
                        {
                            "location_id": stop["location_id"],
                            "ticket_id": stop.get("ticket_id"),
                            "arrival_at": stop["arrival_at"],
                            "service_start_at": stop["service_start_at"],
                            "service_end_at": stop["service_end_at"],
                            "waiting_minutes": stop["waiting_minutes"],
                            "effective_service_minutes": stop["effective_service_minutes"],
                            "duration_source": stop["duration_source"],
                        }
                        for stop in route.get("stops", [])
                    ],
                    "geometry": route.get("geometry"),
                    "path_properties": path_properties,
                }
            )
        )
    return creates


def _apply_manual_route_times(session: Session, route_publics: dict[int, dict | None]) -> None:
    for public in route_publics.values():
        if public is None:
            continue
        for route in public.get("routes", []):
            for stop in route.get("stops", []):
                ticket_id = stop.get("ticket_id")
                if ticket_id is None:
                    continue
                ticket = session.get(Ticket, ticket_id)
                if ticket is None:
                    continue
                ticket.planned_start_at = datetime.fromisoformat(stop["service_start_at"])
                ticket.planned_end_at = datetime.fromisoformat(stop["service_end_at"])
                ticket.updated_at = datetime.now(UTC)


def _publish_manual_assignment_revision(
    session: Session,
    *,
    service_area_id: int | None,
    route_date,
    actor_id: int,
    affected_workers: set[int],
    route_publics: dict[int, dict | None],
    saved_routes,
    ticket_id: int,
    at: datetime,
) -> None:
    if service_area_id is None:
        return

    from app.modules.planning.day_models import DayPlanRevision
    from app.modules.planning.day_plans import build_plan_state, publish_revision

    saved_by_worker = {route.worker_id: route.id for route in saved_routes}
    new_public = {
        "route_date": route_date.isoformat() if hasattr(route_date, "isoformat") else route_date,
        "routes": [
            route
            for public in route_publics.values()
            if public is not None
            for route in public.get("routes", [])
        ],
        "unassigned": [
            item
            for public in route_publics.values()
            if public is not None
            for item in public.get("unassigned", [])
        ],
        "metrics": {},
    }
    new_state = build_plan_state(new_public, saved_by_worker)
    previous = session.scalar(
        select(DayPlanRevision)
        .where(
            DayPlanRevision.service_area_id == service_area_id,
            DayPlanRevision.route_date == route_date,
            DayPlanRevision.is_current.is_(True),
        )
        .with_for_update()
    )
    if previous is not None:
        old_state = previous.plan_state or {}
        kept_visits = [
            visit
            for visit in old_state.get("visits", [])
            if visit.get("worker_id") not in affected_workers
        ]
        new_state["visits"] = sorted(
            kept_visits + new_state.get("visits", []),
            key=lambda visit: (visit.get("worker_id") or 0, visit.get("sequence") or 0),
        )
        old_unassigned = set(old_state.get("unassigned_ticket_ids", []))
        new_unassigned = {item["ticket_id"] for item in new_public["unassigned"]}
        new_state["unassigned_ticket_ids"] = sorted((old_unassigned - {ticket_id}) | new_unassigned)
        new_state["metrics"] = old_state.get("metrics") or {}
    result = {
        "ticket_id": ticket_id,
        "routes": [
            {"id": route.id, "worker_id": route.worker_id, "route_number": route.route_number}
            for route in saved_routes
        ],
    }
    publish_revision(
        session,
        service_area_id=service_area_id,
        route_date=route_date,
        actor_id=actor_id,
        reason="manual_edit",
        fingerprint=f"manual-assignment:{ticket_id}:{at.isoformat()}",
        plan_state=new_state,
        result=result,
        at=at,
        plan_id=None,
    )


def update_assignment_in_transaction(
    session: Session,
    ticket_id: int,
    worker_id: int | None,
    is_pinned: bool,
    *,
    actor_id: int | None = None,
    source: str | None = None,
    planned_at: datetime | None = None,
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
            can_return_before_visit = False
            if source == "plan" and planned_at is not None:
                t_area = ticket.get("service_area_id")
                if t_area is None and ticket.get("location_id"):
                    t_area = session.execute(
                        text(
                            """
                            SELECT building.service_area_id
                            FROM locations AS location
                            JOIN buildings AS building ON building.id = location.building_id
                            WHERE location.id = :location_id
                            """
                        ),
                        {"location_id": ticket["location_id"]},
                    ).scalar_one_or_none()
                can_return_before_visit = session.execute(
                    text(
                        """
                        SELECT EXISTS (
                            SELECT 1 FROM worker_day_states
                            WHERE worker_id = :worker_id
                              AND service_area_id = :service_area_id
                              AND route_date = :route_date
                              AND NOT available
                              AND expected_available_at IS NOT NULL
                              AND expected_available_at <= :planned_at
                        )
                        """
                    ),
                    {
                        "worker_id": worker_id,
                        "service_area_id": t_area,
                        "route_date": planned_at.astimezone(MOSCOW).date(),
                        "planned_at": planned_at,
                    },
                ).scalar_one()
            if not can_return_before_visit:
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
    session: Session,
    ticket_id: int,
    worker_id: int,
    engine,
    settings,
    provider,
    planner,
    clock,
    *,
    actor_id: int | None = None,
) -> AssignmentPreviewResponse:
    ticket_info = _manual_assignment_ticket_info(session, ticket_id)
    if ticket_info is None:
        raise TicketNotFoundError

    worker_line_statuses = repository.find_worker_line_statuses(session, [worker_id])
    if worker_id not in worker_line_statuses:
        raise WorkerNotFoundError

    route_date = ticket_info["route_date"]
    service_area_id = ticket_info["service_area_id"]
    actor = actor_id or 0
    worker_ticket_ids = _manual_worker_ticket_ids(
        session,
        worker_id,
        route_date,
        include_ticket_id=None,
        exclude_ticket_id=None,
    )
    ticket_ids_to_plan = sorted({*worker_ticket_ids, ticket_id})

    result = await _manual_route_preview(
        engine,
        settings,
        provider,
        planner,
        clock,
        actor,
        route_date,
        service_area_id,
        worker_id,
        ticket_ids_to_plan,
    )

    unassigned = [item for item in result.get("unassigned", []) if item["ticket_id"] == ticket_id]
    excluded = [
        item for item in result.get("excluded_workers", []) if item["worker_id"] == worker_id
    ]
    violations = [item["reason"] for item in unassigned]
    if unassigned and excluded:
        violations.extend(item["reason"] for item in excluded)

    old_result = None
    old_ticket_ids = [item for item in worker_ticket_ids if item != ticket_id]
    if old_ticket_ids:
        old_result = await _manual_route_preview(
            engine,
            settings,
            provider,
            planner,
            clock,
            actor,
            route_date,
            service_area_id,
            worker_id,
            old_ticket_ids,
        )

    old_duration = _route_total_minutes(old_result)
    new_duration = _route_total_minutes(result)
    old_sla = _count_sla_violations(session, old_result)
    new_sla = _count_sla_violations(session, result)

    return AssignmentPreviewResponse(
        is_eligible=not violations,
        violations=violations,
        route_shift_minutes=new_duration - old_duration,
        sla_violations_added=max(0, new_sla - old_sla),
    )


def _route_total_minutes(public: dict | None) -> int:
    if public is None:
        return 0
    return sum(
        route.get("travel_minutes", 0) + route.get("service_minutes", 0)
        for route in public.get("routes", [])
    )


def _count_sla_violations(session: Session, public: dict | None) -> int:
    if public is None:
        return 0
    stops = [
        stop
        for route in public.get("routes", [])
        for stop in route.get("stops", [])
        if stop.get("ticket_id") is not None
    ]
    if not stops:
        return 0
    deadlines = {
        ticket.id: ticket.sla_deadline_at
        for ticket in session.scalars(
            select(Ticket).where(Ticket.id.in_([stop["ticket_id"] for stop in stops]))
        )
    }
    count = 0
    for stop in stops:
        deadline = deadlines.get(stop["ticket_id"])
        if deadline is None:
            continue
        service_end = (
            stop["service_end_at"]
            if isinstance(stop["service_end_at"], datetime)
            else datetime.fromisoformat(stop["service_end_at"])
        )
        if service_end > deadline:
            count += 1
    return count

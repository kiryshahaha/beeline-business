"""Bounded input selection directly from PostgreSQL, independent of paginated public APIs."""

from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.orm import Session

from app.core import oplog
from app.db.models import (
    Appliance,
    ApplianceStock,
    Brigade,
    BrigadeMember,
    Building,
    DayPlanRevision,
    Division,
    Location,
    Office,
    ServiceArea,
    Ticket,
    TicketAppliance,
    TicketApplianceState,
    User,
    Worker,
    WorkerDayState,
    WorkerShiftException,
    WorkerSkillAssignment,
    WorkEvent,
    WorkType,
    WorkTypePlanningRule,
    WorkTypeRequiredAppliance,
    WorkTypeRequiredSkill,
)
from app.modules.planning.day_plans import day_roster
from app.modules.planning.errors import PlanningError
from app.modules.planning.policy import execution_policy
from app.modules.planning.policy import policy_snapshot as current_policy_snapshot
from app.modules.planning.schemas import PreviewRequest
from app.modules.planning.snapshot import normalize
from app.modules.service_areas.resolve import MISMATCH, MISSING
from app.modules.service_areas.territory import resolve_tickets, resolve_workers


def rows(session: Session, model, *conditions):
    table = model.__table__
    return [
        dict(row)
        for row in session.execute(
            select(table).where(*conditions).order_by(*table.primary_key.columns)
        ).mappings()
    ]


# The day a ticket belongs to is its promised visit in Moscow time, the same
# boundary the warehouse already uses.
TICKET_LOCAL_DAY = (
    "(COALESCE(tickets.planned_start_at, tickets.visit_window_start) "
    "AT TIME ZONE 'Europe/Moscow')::date"
)


def load_area_scope(session: Session, service_area_id: int | None, route_date) -> dict:
    """Everything in this area-day that could invalidate the plan, not just chosen IDs.

    A fingerprint over the explicitly selected tickets and workers cannot notice a new
    emergency, a cancelled visit or a fresh work event elsewhere in the same area. This
    digest closes that gap, so apply refuses a proposal the day has already moved past.
    """
    if service_area_id is None:
        return {"tickets": [], "events": {"count": 0, "last_id": None}}
    area_tickets = (
        select(Ticket.id)
        .join(Location, Location.id == Ticket.location_id)
        .join(Building, Building.id == Location.building_id)
        .where(
            func.coalesce(Ticket.service_area_id, Building.service_area_id) == service_area_id,
            text(TICKET_LOCAL_DAY + " = :area_scope_date"),
        )
        .params(area_scope_date=route_date)
    )
    tickets = [
        {
            "id": row.id,
            "status": row.status,
            "lifecycle_state": row.lifecycle_state,
            "revision": row.revision,
            "assigned_worker_id": row.assigned_worker_id,
            "brigade_id": row.brigade_id,
        }
        for row in session.execute(
            select(
                Ticket.id,
                Ticket.status,
                Ticket.lifecycle_state,
                Ticket.revision,
                Ticket.assigned_worker_id,
                Ticket.brigade_id,
            )
            .where(Ticket.id.in_(area_tickets))
            .order_by(Ticket.id)
        )
    ]
    area_workers = (
        select(Worker.user_id)
        .outerjoin(BrigadeMember, BrigadeMember.worker_id == Worker.user_id)
        .outerjoin(Brigade, Brigade.id == BrigadeMember.brigade_id)
        .outerjoin(Division, Division.id == Brigade.division_id)
        .where(func.coalesce(Worker.service_area_id, Division.service_area_id) == service_area_id)
    )
    count, last_id = session.execute(
        select(func.count(WorkEvent.id), func.max(WorkEvent.id)).where(
            WorkEvent.route_date == route_date,
            or_(
                WorkEvent.ticket_id.in_(area_tickets),
                WorkEvent.worker_id.in_(area_workers),
            ),
        )
    ).one()
    return {"tickets": tickets, "events": {"count": count, "last_id": last_id}}


@oplog.timed("snapshot")
def load_snapshot(session: Session, request: PreviewRequest, *, policy_snapshot=None) -> dict:
    ticket_ids, worker_ids = request.ticket_ids, request.worker_ids
    tickets = rows(session, Ticket, Ticket.id.in_(ticket_ids))
    all_service_areas = rows(session, ServiceArea)
    ticket_service_areas, ticket_area_errors = resolve_tickets(session, ticket_ids)
    if ticket_area_errors:
        # An unknown area is never taken to be the area of this request.
        raise PlanningError(MISSING, subject="ticket", ticket_ids=sorted(ticket_area_errors))
    service_area_ids = set(ticket_service_areas.values())
    if request.service_area_id is not None and service_area_ids - {request.service_area_id}:
        raise PlanningError("ticket_service_area_mismatch", ticket_areas=sorted(service_area_ids))
    if len(service_area_ids) > 1:
        raise PlanningError("multiple_service_areas", service_areas=sorted(service_area_ids))
    service_area_id = request.service_area_id or next(iter(service_area_ids), None)

    service_area_brigades = {}
    if service_area_ids:
        area_brigade_rows = session.execute(
            select(Brigade.id, Division.service_area_id)
            .join(Division, Division.id == Brigade.division_id)
            .where(Division.service_area_id.in_(service_area_ids))
            .order_by(Brigade.id)
        ).all()
        for brigade_row in area_brigade_rows:
            service_area_brigades.setdefault(brigade_row.service_area_id, []).append(brigade_row.id)

    workers = rows(session, Worker, Worker.user_id.in_(worker_ids))
    roles = [
        dict(row)
        for row in session.execute(
            select(User.id, User.role).where(User.id.in_(worker_ids)).order_by(User.id)
        ).mappings()
    ]
    archived_worker_ids = list(
        session.scalars(
            select(User.id)
            .where(User.id.in_(worker_ids), User.archived_at.is_not(None))
            .order_by(User.id)
        )
    )
    active_tickets = select(Ticket.id).where(Ticket.status.in_(["planned", "in_progress"]))

    # Simulate assignments list of dicts for compatibility with planner
    assigned_tickets = rows(
        session,
        Ticket,
        or_(
            Ticket.id.in_(ticket_ids),
            and_(
                Ticket.assigned_worker_id.in_(worker_ids),
                Ticket.id.in_(active_tickets),
            ),
        ),
    )
    assignments = [
        {"ticket_id": t["id"], "worker_id": t["assigned_worker_id"], "assigned_at": t["updated_at"]}
        for t in assigned_tickets
        if t["assigned_worker_id"] is not None
    ]
    if request.replan:
        replan_ticket_ids = set(ticket_ids)
        assignments = [a for a in assignments if a["ticket_id"] not in replan_ticket_ids]
    busy_ids = {a["ticket_id"] for a in assignments if a["worker_id"] in worker_ids}
    busy = [
        t
        for t in assigned_tickets
        if t["id"] in busy_ids and t["status"] in ("planned", "in_progress")
    ]
    members = rows(session, BrigadeMember, BrigadeMember.worker_id.in_(worker_ids))
    brigades = rows(session, Brigade, Brigade.id.in_({m["brigade_id"] for m in members}))

    worker_service_areas, worker_area_errors = resolve_workers(session, worker_ids)
    worker_area_issues = {
        worker_id: error.details() for worker_id, error in sorted(worker_area_errors.items())
    }
    other_area_workers = sorted(
        worker_id
        for worker_id, area in worker_service_areas.items()
        if service_area_id is not None and area != service_area_id
    )
    # A dispatcher's own selection fails loudly; the replan roster keeps such an
    # engineer out of the calculation with a reason instead of stopping the whole day.
    if not request.replan:
        if worker_area_issues:
            code = (
                MISMATCH
                if any(issue["code"] == MISMATCH for issue in worker_area_issues.values())
                else MISSING
            )
            raise PlanningError(code, subject="worker", workers=list(worker_area_issues.values()))
        if other_area_workers:
            raise PlanningError("worker_service_area_mismatch", worker_ids=other_area_workers)

    worker_office_ids = {
        w["stock_office_id"] for w in workers if w.get("stock_office_id") is not None
    }
    offices = rows(
        session, Office, Office.id.in_({b["office_id"] for b in brigades} | worker_office_ids)
    )
    worker_day_states = rows(
        session,
        WorkerDayState,
        WorkerDayState.worker_id.in_(worker_ids),
        WorkerDayState.route_date == request.route_date,
        *(
            [WorkerDayState.service_area_id == service_area_id]
            if service_area_id is not None
            else []
        ),
    )
    state_location_ids = {
        state["last_location_id"]
        for state in worker_day_states
        if state["last_location_id"] is not None
    }
    state_location_ids.update(
        state["current_destination_id"]
        for state in worker_day_states
        if state["current_destination_id"] is not None
    )
    worker_location_ids = {
        w[loc_field]
        for w in workers
        for loc_field in ("start_location_id", "end_location_id")
        if w.get(loc_field) is not None
    }
    location_ids = (
        {t["location_id"] for t in tickets}
        | {o["location_id"] for o in offices}
        | state_location_ids
        | worker_location_ids
    )
    locations = rows(session, Location, Location.id.in_(location_ids))
    skills = rows(session, WorkerSkillAssignment, WorkerSkillAssignment.worker_id.in_(worker_ids))
    shift_exceptions = rows(
        session,
        WorkerShiftException,
        WorkerShiftException.worker_id.in_(worker_ids),
        WorkerShiftException.exception_date == request.route_date,
    )
    wt_ids = {t["work_type_id"] for t in tickets if t.get("work_type_id")}
    work_types = rows(
        session,
        WorkType,
        WorkType.id.in_(wt_ids) if wt_ids else (WorkType.id == -1),
    )
    type_ids = {t["id"] for t in work_types}

    rules = rows(session, WorkTypePlanningRule, WorkTypePlanningRule.work_type_id.in_(type_ids))
    required_skills = rows(
        session, WorkTypeRequiredSkill, WorkTypeRequiredSkill.work_type_id.in_(type_ids)
    )
    required_appliances = rows(
        session, WorkTypeRequiredAppliance, WorkTypeRequiredAppliance.work_type_id.in_(type_ids)
    )
    allocations = rows(session, TicketAppliance, TicketAppliance.ticket_id.in_(ticket_ids))
    appliance_ids = {a["appliance_id"] for a in allocations + required_appliances}
    office_ids = {o["id"] for o in offices} | {a["office_id"] for a in allocations}
    appliances = rows(session, Appliance, Appliance.id.in_(appliance_ids))
    stocks = rows(
        session,
        ApplianceStock,
        ApplianceStock.office_id.in_(office_ids),
        ApplianceStock.appliance_id.in_(appliance_ids),
    )
    reservations = [
        dict(row)
        for row in session.execute(
            select(
                TicketAppliance.office_id,
                TicketAppliance.appliance_id,
                func.sum(TicketAppliance.quantity).label("quantity"),
            )
            .join(Ticket, Ticket.id == TicketAppliance.ticket_id)
            .where(
                TicketAppliance.office_id.in_(office_ids),
                TicketAppliance.appliance_id.in_(appliance_ids),
                Ticket.status.in_(["planned", "in_progress"]),
                # Issued or written-off units have already left the office stock.
                ~exists().where(
                    TicketApplianceState.ticket_id == TicketAppliance.ticket_id,
                    TicketApplianceState.appliance_id == TicketAppliance.appliance_id,
                ),
            )
            .group_by(TicketAppliance.office_id, TicketAppliance.appliance_id)
            .order_by(TicketAppliance.office_id, TicketAppliance.appliance_id)
        ).mappings()
    ]
    current_day_revision = None
    current_day_state = {}
    current_roster = None
    if service_area_id is not None:
        current_revision = session.execute(
            select(DayPlanRevision.revision, DayPlanRevision.plan_state).where(
                DayPlanRevision.service_area_id == service_area_id,
                DayPlanRevision.route_date == request.route_date,
                DayPlanRevision.is_current.is_(True),
            )
        ).one_or_none()
        if current_revision is not None:
            current_day_revision, current_day_state = current_revision
            if request.replan:
                current_roster = day_roster(session, service_area_id, request.route_date)
    if request.replan and current_roster:
        # The remainder keeps the shift each engineer had when the day was published.
        shifts = {entry["worker_id"]: entry for entry in current_roster}
        for worker in workers:
            entry = shifts.get(worker["user_id"])
            if entry and entry.get("workshift_start") and entry.get("workshift_end"):
                worker["workshift_start"] = entry["workshift_start"]
                worker["workshift_end"] = entry["workshift_end"]
    area_scope = load_area_scope(session, service_area_id, request.route_date)
    return normalize(
        {
            "request": request.model_dump(mode="json"),
            **(
                current_policy_snapshot(execution_policy())
                if policy_snapshot is None
                else policy_snapshot
            ),
            "tickets": tickets,
            "workers": workers,
            "roles": roles,
            "assignments": assignments,
            "busy_tickets": busy,
            "members": members,
            "brigades": brigades,
            "offices": offices,
            "locations": locations,
            "skills": skills,
            "work_types": work_types,
            "rules": rules,
            "required_skills": required_skills,
            "required_appliances": required_appliances,
            "allocations": allocations,
            "appliances": appliances,
            "stocks": stocks,
            "reservations": reservations,
            "service_area_id": service_area_id,
            "service_area_brigades": service_area_brigades,
            "service_areas": all_service_areas,
            "ticket_service_areas": ticket_service_areas,
            "worker_service_areas": worker_service_areas,
            **({"worker_area_issues": worker_area_issues} if worker_area_issues else {}),
            "worker_day_states": worker_day_states,
            "shift_exceptions": shift_exceptions,
            "current_day_revision": current_day_revision,
            "current_day_state": current_day_state or {},
            **({"current_day_roster": current_roster} if request.replan else {}),
            # The whole area-day, not only the chosen IDs: a ticket that appeared or
            # changed after the preview must make this plan stale (T09).
            "area_scope": area_scope,
            # Only when present: snapshots of plans calculated before archiving existed,
            # and of plans without archived engineers, keep their fingerprints.
            **({"archived_worker_ids": archived_worker_ids} if archived_worker_ids else {}),
        }
    )

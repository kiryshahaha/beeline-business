"""Bounded input selection directly from PostgreSQL, independent of paginated public APIs."""

from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.orm import Session

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
    WorkerSkillAssignment,
    WorkEvent,
    WorkType,
    WorkTypePlanningRule,
    WorkTypeRequiredAppliance,
    WorkTypeRequiredSkill,
)
from app.modules.planning.errors import PlanningError
from app.modules.planning.policy import execution_policy
from app.modules.planning.schemas import PreviewRequest
from app.modules.planning.snapshot import normalize


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
        .where(
            Ticket.service_area_id == service_area_id,
            text(TICKET_LOCAL_DAY + " = :area_scope_date"),
        )
        .params(area_scope_date=route_date)
    )
    tickets = [
        {
            "id": row.id,
            "status": row.status,
            "revision": row.revision,
            "assigned_worker_id": row.assigned_worker_id,
        }
        for row in session.execute(
            select(Ticket.id, Ticket.status, Ticket.revision, Ticket.assigned_worker_id)
            .where(Ticket.id.in_(area_tickets))
            .order_by(Ticket.id)
        )
    ]
    area_workers = select(Worker.user_id).where(Worker.service_area_id == service_area_id)
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


def load_snapshot(session: Session, request: PreviewRequest, *, policy_snapshot=None) -> dict:
    ticket_ids, worker_ids = request.ticket_ids, request.worker_ids
    tickets = rows(session, Ticket, Ticket.id.in_(ticket_ids))
    ticket_districts = {
        row["id"]: row["district_id"]
        for row in session.execute(
            select(Ticket.id, Building.district_id)
            .join(Location, Location.id == Ticket.location_id)
            .join(Building, Building.id == Location.building_id)
            .where(Ticket.id.in_(ticket_ids))
        ).mappings()
    }
    all_service_areas = rows(session, ServiceArea)
    service_areas_by_code = {sa["code"]: sa["id"] for sa in all_service_areas}
    default_service_area_id = all_service_areas[0]["id"] if all_service_areas else None

    ticket_service_areas = {
        t["id"]: t["service_area_id"] for t in tickets if t.get("service_area_id") is not None
    }
    for t in tickets:
        if t["id"] not in ticket_service_areas and t["id"] in ticket_districts:
            dist_id = ticket_districts[t["id"]]
            ticket_service_areas[t["id"]] = service_areas_by_code.get(
                f"district_{dist_id}", default_service_area_id or dist_id
            )
    service_area_ids = set(ticket_service_areas.values())
    if request.service_area_id is not None and service_area_ids - {request.service_area_id}:
        raise PlanningError("ticket_service_area_mismatch", ticket_areas=sorted(service_area_ids))
    if len(service_area_ids) > 1:
        raise PlanningError("multiple_service_areas", service_areas=sorted(service_area_ids))
    service_area_id = request.service_area_id or next(iter(service_area_ids), None)

    district_ids = set(ticket_districts.values())
    if request.district_id is not None and district_ids - {request.district_id}:
        raise PlanningError("ticket_district_mismatch", ticket_districts=sorted(district_ids))
    if len(district_ids) > 1 and len(service_area_ids) <= 1:
        pass  # allow multiple administrative districts within a single service area
    elif len(district_ids) > 1:
        raise PlanningError("multiple_districts", districts=sorted(district_ids))
    district_id = request.district_id or next(iter(district_ids), None)
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
    busy_ids = {a["ticket_id"] for a in assignments if a["worker_id"] in worker_ids}
    busy = [
        t
        for t in assigned_tickets
        if t["id"] in busy_ids and t["status"] in ("planned", "in_progress")
    ]
    members = rows(session, BrigadeMember, BrigadeMember.worker_id.in_(worker_ids))
    brigades = rows(session, Brigade, Brigade.id.in_({m["brigade_id"] for m in members}))
    brigade_by_id = {brigade["id"]: brigade for brigade in brigades}
    member_by_worker = {m["worker_id"]: m for m in members}
    divisions = {
        row["id"]: row["district_id"]
        for row in rows(session, Division, Division.id.in_({b["division_id"] for b in brigades}))
    }

    worker_service_areas = {}
    for w in workers:
        wid = w["user_id"]
        if w.get("service_area_id") is not None:
            worker_service_areas[wid] = w["service_area_id"]
        else:
            mb = member_by_worker.get(wid)
            br = brigade_by_id.get(mb["brigade_id"]) if mb else None
            dist_id = divisions.get(br["division_id"]) if br else None
            worker_service_areas[wid] = (
                service_areas_by_code.get(f"district_{dist_id}", default_service_area_id or dist_id)
                if dist_id is not None
                else default_service_area_id
            )

    target_area = service_area_id
    if target_area is not None:
        invalid_area_workers = sorted(
            wid
            for wid, s_area in worker_service_areas.items()
            if s_area is not None and s_area != target_area
        )
        if invalid_area_workers:
            raise PlanningError("worker_service_area_mismatch", worker_ids=invalid_area_workers)
    elif district_id is not None:
        invalid_worker_ids = sorted(
            member["worker_id"]
            for member in members
            if divisions.get(brigade_by_id.get(member["brigade_id"], {}).get("division_id"))
            != district_id
        )
        if invalid_worker_ids:
            raise PlanningError("worker_district_mismatch", worker_ids=invalid_worker_ids)

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
        *([WorkerDayState.district_id == district_id] if district_id is not None else []),
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
    if service_area_id is not None:
        current_day_revision = session.execute(
            select(DayPlanRevision.revision).where(
                DayPlanRevision.service_area_id == service_area_id,
                DayPlanRevision.route_date == request.route_date,
                DayPlanRevision.is_current.is_(True),
            )
        ).scalar_one_or_none()
    area_scope = load_area_scope(session, service_area_id, request.route_date)
    return normalize(
        {
            "request": request.model_dump(mode="json"),
            **(
                {
                    "policy_version": 1,
                    "planning_policy": execution_policy().model_dump(mode="json"),
                }
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
            "ticket_districts": ticket_districts,
            "district_id": district_id,
            "service_areas": all_service_areas,
            "service_area_id": service_area_id,
            "ticket_service_areas": ticket_service_areas,
            "worker_service_areas": worker_service_areas,
            "worker_day_states": worker_day_states,
            "current_day_revision": current_day_revision,
            # The whole area-day, not only the chosen IDs: a ticket that appeared or
            # changed after the preview must make this plan stale (T09).
            "area_scope": area_scope,
            # Only when present: snapshots of plans calculated before archiving existed,
            # and of plans without archived engineers, keep their fingerprints.
            **({"archived_worker_ids": archived_worker_ids} if archived_worker_ids else {}),
        }
    )

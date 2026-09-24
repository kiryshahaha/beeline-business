"""Bounded input selection directly from PostgreSQL, independent of paginated public APIs."""

from sqlalchemy import and_, exists, func, or_, select
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
    Ticket,
    TicketAppliance,
    TicketApplianceState,
    TicketAssignment,
    User,
    Worker,
    WorkerDayState,
    WorkerSkillAssignment,
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
    district_ids = set(ticket_districts.values())
    if request.district_id is not None and district_ids - {request.district_id}:
        raise PlanningError("ticket_district_mismatch", ticket_districts=sorted(district_ids))
    if len(district_ids) > 1:
        raise PlanningError("multiple_districts", districts=sorted(district_ids))
    district_id = request.district_id or next(iter(district_ids), None)
    workers = rows(session, Worker, Worker.user_id.in_(worker_ids))
    roles = [
        dict(row)
        for row in session.execute(
            select(User.id, User.role).where(User.id.in_(worker_ids)).order_by(User.id)
        ).mappings()
    ]
    active_tickets = select(Ticket.id).where(Ticket.status.in_(["planned", "in_progress"]))
    assignments = rows(
        session,
        TicketAssignment,
        or_(
            TicketAssignment.ticket_id.in_(ticket_ids),
            and_(
                TicketAssignment.worker_id.in_(worker_ids),
                TicketAssignment.ticket_id.in_(active_tickets),
            ),
        ),
    )
    busy_ids = {a["ticket_id"] for a in assignments if a["worker_id"] in worker_ids}
    busy = rows(
        session, Ticket, Ticket.id.in_(busy_ids), Ticket.status.in_(["planned", "in_progress"])
    )
    members = rows(session, BrigadeMember, BrigadeMember.worker_id.in_(worker_ids))
    brigades = rows(session, Brigade, Brigade.id.in_({m["brigade_id"] for m in members}))
    if district_id is not None:
        divisions = {
            row["id"]: row["district_id"]
            for row in rows(
                session, Division, Division.id.in_({b["division_id"] for b in brigades})
            )
        }
        brigade_by_id = {brigade["id"]: brigade for brigade in brigades}
        invalid_worker_ids = sorted(
            member["worker_id"]
            for member in members
            if divisions.get(brigade_by_id.get(member["brigade_id"], {}).get("division_id"))
            != district_id
        )
        if invalid_worker_ids:
            raise PlanningError("worker_district_mismatch", worker_ids=invalid_worker_ids)
    offices = rows(session, Office, Office.id.in_({b["office_id"] for b in brigades}))
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
    location_ids = (
        {t["location_id"] for t in tickets}
        | {o["location_id"] for o in offices}
        | state_location_ids
    )
    locations = rows(session, Location, Location.id.in_(location_ids))
    skills = rows(session, WorkerSkillAssignment, WorkerSkillAssignment.worker_id.in_(worker_ids))
    wt_ids = {t["work_type_id"] for t in tickets if t.get("work_type_id")}
    wt_names = {t["work_type"].strip().lower() for t in tickets if t.get("work_type")}
    wt_conds = []
    if wt_ids:
        wt_conds.append(WorkType.id.in_(wt_ids))
    if wt_names:
        wt_conds.append(func.lower(WorkType.name).in_(wt_names))
    work_types = rows(
        session,
        WorkType,
        or_(*wt_conds) if wt_conds else (WorkType.id == -1),
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
    if district_id is not None:
        current_day_revision = session.execute(
            select(DayPlanRevision.revision).where(
                DayPlanRevision.district_id == district_id,
                DayPlanRevision.route_date == request.route_date,
                DayPlanRevision.is_current.is_(True),
            )
        ).scalar_one_or_none()
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
            "worker_day_states": worker_day_states,
            "current_day_revision": current_day_revision,
        }
    )

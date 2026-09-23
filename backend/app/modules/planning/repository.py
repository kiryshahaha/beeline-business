"""Bounded input selection directly from PostgreSQL, independent of paginated public APIs."""

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    Appliance,
    ApplianceStock,
    Brigade,
    BrigadeMember,
    Location,
    Office,
    Ticket,
    TicketAppliance,
    TicketAssignment,
    User,
    Worker,
    WorkerSkillAssignment,
    WorkType,
    WorkTypePlanningRule,
    WorkTypeRequiredAppliance,
    WorkTypeRequiredSkill,
)
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
    offices = rows(session, Office, Office.id.in_({b["office_id"] for b in brigades}))
    location_ids = {t["location_id"] for t in tickets} | {o["location_id"] for o in offices}
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
            )
            .group_by(TicketAppliance.office_id, TicketAppliance.appliance_id)
            .order_by(TicketAppliance.office_id, TicketAppliance.appliance_id)
        ).mappings()
    ]
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
        }
    )

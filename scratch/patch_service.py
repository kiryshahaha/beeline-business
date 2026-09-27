import re

with open("backend/app/modules/tickets/service.py", "r", encoding="utf-8") as f:
    content = f.read()

preview_old = """def preview_assignment(session: Session, ticket_id: int, worker_id: int):
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

    service_area_id = session.execute(
        text(
            \"\"\"
            SELECT building.service_area_id
            FROM locations AS location
            JOIN buildings AS building ON building.id = location.building_id
            WHERE location.id = :location_id
            \"\"\"
        ),
        {"location_id": ticket["location_id"]},
    ).scalar()

    request = PreviewRequest(
        route_date=ticket["visit_window_start"].astimezone(MOSCOW).date().isoformat(),
        service_area_id=service_area_id,
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
    )"""

preview_new = """async def preview_assignment(
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
            \"\"\"
            SELECT building.service_area_id
            FROM locations AS location
            JOIN buildings AS building ON building.id = location.building_id
            WHERE location.id = :location_id
            \"\"\"
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

    unassigned = [u for u in result.get("unassigned", []) if u.ticket_id == ticket_id]
    is_eligible = len(unassigned) == 0
    violations = []
    if not is_eligible:
        for u in unassigned:
            violations.append(u.reason.code)

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
        for stop in r.stops:
            sla_deadline = tickets_sla.get(stop.ticket_id)
            if sla_deadline and stop.service_end_at and stop.service_end_at > sla_deadline:
                violations_count += 1
        return violations_count

    if result.get("routes"):
        r = result["routes"][0]
        new_travel = r.travel_minutes
        new_service = r.service_minutes
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
            old_travel = r.travel_minutes
            old_service = r.service_minutes
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
    )"""

content = content.replace(preview_old, preview_new)

update_old = """def update_assignment(
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
            session, ticket_id, worker_id, is_pinned, actor_id=actor_id, source="manual"
        )"""

update_new = """async def update_assignment(
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
        rc = RouteCreate(worker_id=r.worker_id, transport_type=r.transport_type, stops=[{"ticket_id": s.ticket_id, "location_id": s.location_id, "sequence": s.sequence, "arrival_at": s.arrival_at, "service_start_at": s.service_start_at, "service_end_at": s.service_end_at} for s in r.stops], geometry=r.geometry, legs=r.legs)
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
                    plan_state=build_plan_state({"routes": [{"worker_id": worker_id, "stops": [{"ticket_id": s.ticket_id, "sequence": s.sequence, "arrival_at": s.arrival_at.isoformat(), "service_start_at": s.service_start_at.isoformat(), "service_end_at": s.service_end_at.isoformat()} for s in r.stops]}]}, {worker_id: saved[0].id}),
                    result={},
                    at=clock(),
                    plan_id=None
                )
        await run_in_threadpool(save)"""

content = content.replace(update_old, update_new)

with open("backend/app/modules/tickets/service.py", "w", encoding="utf-8") as f:
    f.write(content)

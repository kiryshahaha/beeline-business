"""Read a snapshot, calculate outside transactions, then apply one immutable proposal."""

import asyncio
import copy
import logging
import time
from datetime import UTC, datetime, timedelta
from math import ceil
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.planning_guard import lock_planning_mutation
from app.modules.notifications.enums import NotificationKind
from app.modules.execution.enums import WorkEventType
from app.modules.execution.models import WorkEvent
from app.modules.notifications.schedule_updates import publish_schedule_updated
from app.modules.planning.day_models import DayPlanRevision
from app.modules.planning.day_plans import (
    build_plan_state,
    build_replan_state,
    day_roster,
    diff_states,
    publish_revision,
    roster_from_snapshot,
    roster_ids,
    validate_immutable_route_invariants,
)
from app.modules.planning.diagnostics import (
    diagnose_dropped,
    estimate_resources,
    outcome,
    plan_metrics,
    visit_factors,
)
from app.modules.planning.eligibility import prepare
from app.modules.planning.errors import PlanningError
from app.modules.planning.geometry import apply_estimate_corrections, build_routes
from app.modules.planning.matrices import build_problem
from app.modules.planning.models import PlanningPlan, PlanningPlanRoute
from app.modules.planning.policy import execution_policy, policy_snapshot, snapshot_policy
from app.modules.planning.reasons import legacy_public
from app.modules.planning.repository import TICKET_LOCAL_DAY, load_snapshot
from app.modules.planning.schemas import PreviewRequest
from app.modules.planning.slot_finder import find_regular_ticket_slot
from app.modules.planning.snapshot import fingerprint, normalize
from app.modules.planning.validation import validate_solution
from app.modules.routing.client import GeoapifyRoutingError
from app.modules.routing.schemas import RouteCreate
from app.modules.routing.service import RouteValidationError, save_routes_in_transaction
from app.modules.routing.telemetry import RoutingTelemetry
from app.modules.tickets import repository as ticket_repository
from app.modules.tickets.enums import TicketCategory
from app.modules.tickets.models import Ticket
from app.modules.tickets.service import update_assignment_in_transaction
from app.modules.users.models import User

logger = logging.getLogger(__name__)
MOSCOW = ZoneInfo("Europe/Moscow")


def _notify_rescheduled_tickets(session: Session, revision: DayPlanRevision) -> None:
    """Notify assigned workers when a published service start moves by >= 15 minutes."""
    changes = (revision.diff or {}).get("changed", [])
    reason_text = (
        "Маршрут пересчитан из-за изменения условий"
        if revision.reason == "event_replan"
        else "Опубликован новый план маршрута"
    )
    for change in changes:
        fields = change.get("changes", {})
        start_change = fields.get("service_start_at")
        if not start_change or not start_change.get("from") or not start_change.get("to"):
            continue
        previous = datetime.fromisoformat(start_change["from"])
        current = datetime.fromisoformat(start_change["to"])
        if abs((current - previous).total_seconds()) < 15 * 60:
            continue
        ticket = session.get(Ticket, change["ticket_id"])
        if ticket is None or ticket.assigned_worker_id is None:
            continue
        ticket_repository.add_notification_events(
            session,
            [ticket.assigned_worker_id],
            kind=NotificationKind.TICKET_RESCHEDULED,
            ticket_id=ticket.id,
            data={
                "from": previous.isoformat(),
                "to": current.isoformat(),
                "reason_text": reason_text,
            },
        )


def ticket_event_policy(category: str) -> str:
    """Select the planning policy for a persisted ticket category."""
    """Select one event policy from the persisted ticket category."""
    try:
        normalized_category = TicketCategory(category)
    except (TypeError, ValueError) as error:
        raise PlanningError("ticket_category_invalid", 409, category=category) from error
    return (
        "emergency_replan" if normalized_category is TicketCategory.EMERGENCY else "regular_insert"
    )


def utc_now():
    return datetime.now(UTC)


def read_snapshot(engine, request, policy):
    with Session(engine) as session, session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        return load_snapshot(session, request, policy_snapshot=policy_snapshot(policy))


def validate_replan_limits(ticket_count, worker_count, *, max_tickets, max_workers):
    if ticket_count > max_tickets or worker_count > max_workers:
        raise PlanningError(
            "planning_limit_exceeded",
            requested_tickets=ticket_count,
            requested_workers=worker_count,
            max_tickets=max_tickets,
            max_workers=max_workers,
        )


def read_replan_snapshot(
    engine,
    service_area_id,
    route_date,
    command,
    policy,
    *,
    max_tickets=100,
    max_workers=20,
):
    """Select the area-day remainder and capture it with one repeatable-read snapshot."""
    with Session(engine) as session, session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        current_revision = session.execute(
            select(DayPlanRevision.revision).where(
                DayPlanRevision.service_area_id == service_area_id,
                DayPlanRevision.route_date == route_date,
                DayPlanRevision.is_current.is_(True),
            )
        ).scalar_one_or_none()
        if current_revision is None:
            raise PlanningError("day_plan_not_found", 404)
        if command.base_day_revision is not None and command.base_day_revision != current_revision:
            raise PlanningError("day_revision_stale", 409, current_revision=current_revision)
        ticket_ids = list(
            session.execute(
                text(
                    """
                    SELECT tickets.id
                    FROM tickets
                    JOIN locations AS location ON location.id = tickets.location_id
                    JOIN buildings AS building ON building.id = location.building_id
                    WHERE COALESCE(tickets.service_area_id, building.service_area_id) = :area_id
                      AND tickets.status = 'planned'
                      AND tickets.lifecycle_state <> 'en_route'
                    AND """
                    + TICKET_LOCAL_DAY
                    + " = :route_date ORDER BY tickets.id"
                ),
                {"area_id": service_area_id, "route_date": route_date},
            ).scalars()
        )
        # The remainder is recalculated for the engineers admitted to this day only; new
        # demand never pulls in the rest of the area.
        roster = day_roster(session, service_area_id, route_date)
        if roster is None:
            raise PlanningError("day_roster_unrecoverable", 409, current_revision=current_revision)
        worker_ids = roster_ids(roster)
        validate_replan_limits(
            len(ticket_ids),
            len(worker_ids),
            max_tickets=max_tickets,
            max_workers=max_workers,
        )
        request = PreviewRequest(
            route_date=route_date,
            service_area_id=service_area_id,
            base_day_revision=current_revision,
            ticket_ids=ticket_ids,
            worker_ids=worker_ids,
            allow_partial=command.allow_partial,
            replan=True,
        )
        snapshot = load_snapshot(session, request, policy_snapshot=policy_snapshot(policy))
        return request, snapshot


def read_ticket_event_snapshot(
    engine,
    service_area_id,
    route_date,
    ticket_id,
    command,
    policy,
    *,
    max_tickets=100,
    max_workers=20,
):
    """Read a new-ticket event and the matching area-day revision in one snapshot."""
    with Session(engine) as session, session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        revision = session.scalar(
            select(DayPlanRevision).where(
                DayPlanRevision.service_area_id == service_area_id,
                DayPlanRevision.route_date == route_date,
                DayPlanRevision.is_current.is_(True),
            )
        )
        if revision is None:
            raise PlanningError("day_plan_not_found", 404)
        if command.base_day_revision != revision.revision:
            raise PlanningError("day_revision_stale", 409, current_revision=revision.revision)

        ticket = session.get(Ticket, ticket_id)
        if ticket is None:
            raise PlanningError("ticket_not_found", 404, ticket_id=ticket_id)
        area_and_day = session.execute(
            text(
                """
                SELECT COALESCE(tickets.service_area_id, buildings.service_area_id) AS area_id,
                       (COALESCE(tickets.planned_start_at, tickets.visit_window_start)
                        AT TIME ZONE 'Europe/Moscow')::date AS route_date
                FROM tickets
                JOIN locations ON locations.id = tickets.location_id
                JOIN buildings ON buildings.id = locations.building_id
                WHERE tickets.id = :ticket_id
                """
            ),
            {"ticket_id": ticket_id},
        ).one_or_none()
        if area_and_day is None or area_and_day.area_id != service_area_id:
            raise PlanningError("ticket_service_area_mismatch", 409, ticket_id=ticket_id)
        if area_and_day.route_date != route_date:
            raise PlanningError(
                "ticket_route_date_mismatch",
                409,
                ticket_id=ticket_id,
                ticket_route_date=area_and_day.route_date,
            )
        if getattr(ticket.status, "value", ticket.status) != "planned":
            raise PlanningError(
                "ticket_event_state_conflict",
                409,
                ticket_id=ticket_id,
                status=getattr(ticket.status, "value", ticket.status),
            )
        lifecycle_state = getattr(ticket.lifecycle_state, "value", ticket.lifecycle_state)
        if lifecycle_state not in {"waiting_assignment", "assigned", "dispatched"}:
            raise PlanningError(
                "ticket_event_state_conflict",
                409,
                ticket_id=ticket_id,
                lifecycle_state=lifecycle_state,
            )
        current_visits = (revision.plan_state or {}).get("visits", [])
        if any(visit.get("ticket_id") == ticket_id for visit in current_visits):
            raise PlanningError("ticket_already_in_day_plan", 409, ticket_id=ticket_id)

        event = session.scalar(
            select(WorkEvent)
            .where(
                WorkEvent.ticket_id == ticket_id,
                WorkEvent.event_type == WorkEventType.NEW_TICKET,
            )
            .order_by(WorkEvent.id.desc())
            .limit(1)
        )
        if event is None:
            raise PlanningError("ticket_new_event_missing", 409, ticket_id=ticket_id)

        category = getattr(ticket.category, "value", ticket.category)
        emergency = category == "emergency"
        if emergency:
            selected_ids = list(
                session.execute(
                    text(
                        """
                        SELECT tickets.id
                        FROM tickets
                        JOIN locations ON locations.id = tickets.location_id
                        JOIN buildings ON buildings.id = locations.building_id
                        WHERE COALESCE(tickets.service_area_id, buildings.service_area_id)
                              = :area_id
                          AND tickets.status = 'planned'
                          AND tickets.lifecycle_state <> 'en_route'
                        AND """
                        + TICKET_LOCAL_DAY
                        + " = :route_date ORDER BY tickets.id"
                    ),
                    {"area_id": service_area_id, "route_date": route_date},
                ).scalars()
            )
        else:
            already_unassigned = set((revision.plan_state or {}).get("unassigned_ticket_ids", []))
            lifecycle = {
                row[0]: row[1]
                for row in session.execute(
                    text("SELECT id, lifecycle_state FROM tickets WHERE id = ANY(:ticket_ids)"),
                    {"ticket_ids": [visit["ticket_id"] for visit in current_visits] or [ticket_id]},
                )
            }
            selected_ids = sorted(
                {
                    visit["ticket_id"]
                    for visit in current_visits
                    if visit["ticket_id"] not in already_unassigned
                    and lifecycle.get(visit["ticket_id"]) != "en_route"
                }
                | {ticket_id}
            )

        roster = day_roster(session, service_area_id, route_date)
        if roster is None:
            raise PlanningError("day_roster_unrecoverable", 409, current_revision=revision.revision)
        worker_ids = roster_ids(roster)
        validate_replan_limits(
            len(selected_ids), len(worker_ids), max_tickets=max_tickets, max_workers=max_workers
        )
        request = PreviewRequest(
            route_date=route_date,
            service_area_id=service_area_id,
            base_day_revision=revision.revision,
            ticket_ids=selected_ids,
            worker_ids=worker_ids,
            replan=True,
        )
        snapshot = load_snapshot(session, request, policy_snapshot=policy_snapshot(policy))
        event_data = {
            "source_event_id": event.id,
            "event_type": "new_ticket",
            "ticket_id": ticket_id,
            "category": category,
            "request_type_hd": ticket.request_type_hd,
            "received_at": ticket.received_at,
            "response_deadline_at": ticket.response_deadline_at,
        }
        return request, snapshot, event_data


async def find_regular_ticket_insertion(
    snapshot, ticket_id, settings, provider_factory, clock=utc_now
):
    """Run shared eligibility and matrix checks, then choose one immutable route gap."""
    prepared = prepare(snapshot, clock())
    ticket = next((item for item in prepared["tickets"] if item["id"] == ticket_id), None)
    if ticket is None:
        rejection = next(
            (item for item in prepared["unassigned"] if item["ticket_id"] == ticket_id), None
        )
        return None, prepared, rejection

    try:
        async with asyncio.timeout(settings.planning_total_timeout_seconds):
            async with provider_factory() as provider:
                problem, nodes = await build_problem(prepared, provider, settings)
    except TimeoutError as error:
        raise PlanningError("planning_timeout", 504) from error
    except GeoapifyRoutingError as error:
        raise PlanningError("routing_invalid_response", 502) from error

    location_nodes = {}
    for index, node in enumerate(nodes):
        location_nodes.setdefault(node["location_id"], index)

    def travel_time(from_location_id, to_location_id, profile):
        from_node = location_nodes.get(from_location_id)
        to_node = location_nodes.get(to_location_id)
        if from_node is None or to_node is None:
            return 1_000_000
        matrix = problem.matrices.get(profile)
        minutes = matrix.time_minutes[from_node][to_node] if matrix else None
        return minutes if minutes is not None else 1_000_000

    raw_tickets = {item["id"]: item for item in snapshot["tickets"]}
    event_ticket = raw_tickets[ticket_id]
    ticket_window_start = max(
        datetime.fromisoformat(event_ticket["visit_window_start"]),
        datetime.fromisoformat(event_ticket["received_at"]),
    )
    slot_ticket = {
        "id": ticket_id,
        "location_id": ticket["location_id"],
        "estimated_duration_minutes": ticket["duration"],
        "visit_window_start": ticket_window_start,
        "visit_window_end": event_ticket["visit_window_end"],
        "required_transport_type": ticket.get("required_transport_type"),
        "required_skills": ticket.get("required_skill_ids", []),
        # `prepare` already applies reserved-equipment and issuing checks per worker.
        "required_appliances": {},
    }
    offices = {item["id"]: item for item in snapshot["offices"]}
    allowed = set(ticket["allowed"])
    candidate_workers = []
    for index, worker in enumerate(prepared["workers"]):
        if index not in allowed:
            continue
        office = offices.get(worker["office_id"])
        candidate_workers.append(
            {
                "user_id": worker["user_id"],
                "skills": worker["skill_ids"],
                "transport_type": worker["transport_type"],
                "transport_profile": worker["profile"],
                "available_appliances": {},
                "shift_start_at": worker["shift_start"],
                "shift_end_at": worker["shift_end"],
                "office_location_id": office["location_id"] if office else None,
            }
        )

    visits_by_id = {item["id"]: item for item in raw_tickets.values()}
    baseline_state = dict(snapshot.get("current_day_state") or {})
    enriched_visits = []
    for visit in baseline_state.get("visits", []):
        ticket_row = visits_by_id.get(visit["ticket_id"], {})
        enriched_visits.append(
            {
                **visit,
                "location_id": ticket_row.get("location_id"),
                "visit_window_start": ticket_row.get("visit_window_start"),
                "visit_window_end": ticket_row.get("visit_window_end"),
            }
        )
    baseline_state["visits"] = enriched_visits
    lifecycle_by_ticket = {
        item["id"]: item["lifecycle_state"] for item in snapshot["area_scope"]["tickets"]
    }
    lifecycle_by_ticket.update(
        {item["id"]: item["lifecycle_state"] for item in snapshot["tickets"]}
    )
    location_ids = [worker.get("office_location_id") for worker in candidate_workers]
    location_ids.extend(visit.get("location_id") for visit in enriched_visits)
    office_location_id = next((item for item in location_ids if item is not None), None)
    result = find_regular_ticket_slot(
        ticket=slot_ticket,
        candidate_workers=candidate_workers,
        baseline_state=baseline_state,
        lifecycle_by_ticket=lifecycle_by_ticket,
        travel_time_fn=travel_time,
        office_location_id=office_location_id,
        now=clock(),
    )
    return result, prepared, None


def _ordinary_insert_ticket_ids(snapshot):
    """Only newly arrived unassigned requests are candidates for insertion."""
    day_state = snapshot.get("current_day_state") or {}
    previous_ids = {visit["ticket_id"] for visit in day_state.get("visits", [])}
    previous_ids.update(day_state.get("unassigned_ticket_ids", []))
    area_scope_tickets = day_state.get("area_scope_tickets")
    if area_scope_tickets is not None:
        baseline = {ticket["id"]: ticket for ticket in area_scope_tickets}
        new_tickets = [
            ticket
            for ticket in snapshot["tickets"]
            if ticket["id"] not in previous_ids
            and (
                ticket["id"] not in baseline
                or ticket.get("assigned_worker_id")
                != baseline[ticket["id"]].get("assigned_worker_id")
            )
        ]
    else:
        # Legacy revisions do not record area demand. Fall back to the visible plan.
        new_tickets = [ticket for ticket in snapshot["tickets"] if ticket["id"] not in previous_ids]
    if not new_tickets:
        # The area query also sees older demand that was outside the original
        # preview. It is not a new arrival and must not turn this into insertion-only.
        return None
    if any(
        ticket.get("category") is not None
        and ticket_event_policy(ticket["category"]) == "emergency_replan"
        for ticket in new_tickets
    ):
        return None
    return {
        ticket["id"]
        for ticket in new_tickets
        if ticket.get("lifecycle_state") in {"waiting_assignment", "assigned", "dispatched"}
    }


def _pin_existing_visits_for_ordinary_insert(
    prepared, snapshot, new_ticket_ids, proposed_state=None
):
    """Keep each published future visit on its worker and at its promised start."""
    candidates = {ticket["id"]: ticket for ticket in prepared["tickets"]}
    eligible_new_ids = new_ticket_ids & candidates.keys()
    for ticket_id in sorted(new_ticket_ids - candidates.keys()):
        rejection = next(
            (item for item in prepared["unassigned"] if item["ticket_id"] == ticket_id), None
        )
        raise PlanningError(
            "ordinary_insert_ticket_ineligible",
            409,
            ticket_id=ticket_id,
            rejection=rejection["reason"] if rejection else None,
        )

    workers = {
        worker.get("user_id", worker.get("worker_id")): index
        for index, worker in enumerate(prepared["workers"])
    }
    lifecycle_by_ticket = {
        ticket["id"]: ticket["lifecycle_state"] for ticket in snapshot["tickets"]
    }
    proposed_visits = {
        visit["ticket_id"]: visit for visit in (proposed_state or {}).get("visits", [])
    }
    for visit in (snapshot.get("current_day_state") or {}).get("visits", []):
        ticket = candidates.get(visit["ticket_id"])
        if ticket is None:
            if lifecycle_by_ticket.get(visit["ticket_id"]) in {"assigned", "dispatched"}:
                raise PlanningError(
                    "ordinary_insert_existing_visit_conflict",
                    409,
                    ticket_id=min(new_ticket_ids) if new_ticket_ids else None,
                    conflicting_ticket_id=visit["ticket_id"],
                )
            continue
        worker_index = workers.get(visit.get("worker_id"))
        if worker_index is None or worker_index not in ticket["allowed"]:
            raise PlanningError(
                "ordinary_insert_existing_visit_conflict",
                409,
                ticket_id=min(new_ticket_ids) if new_ticket_ids else None,
                conflicting_ticket_id=visit["ticket_id"],
            )
        proposed_visit = proposed_visits.get(visit["ticket_id"], visit)
        service_start = proposed_visit.get("service_start_at")
        if not service_start:
            raise PlanningError(
                "ordinary_insert_existing_visit_conflict",
                409,
                ticket_id=min(new_ticket_ids) if new_ticket_ids else None,
                conflicting_ticket_id=visit["ticket_id"],
            )
        if isinstance(service_start, str):
            service_start = datetime.fromisoformat(service_start)
        fixed_start = ceil((service_start - prepared["epoch"]).total_seconds() / 60)
        if fixed_start < ticket["window"][0] or fixed_start > ticket["window"][1]:
            raise PlanningError(
                "ordinary_insert_existing_visit_conflict",
                409,
                ticket_id=min(new_ticket_ids) if new_ticket_ids else None,
                conflicting_ticket_id=visit["ticket_id"],
            )
        ticket["allowed"] = [worker_index]
        ticket["window"] = (fixed_start, fixed_start)
    for ticket_id in eligible_new_ids:
        ticket = candidates[ticket_id]
        worker_id = ticket.get("assigned_worker_id")
        if worker_id is None:
            continue
        worker_index = workers.get(worker_id)
        if worker_index is None or worker_index not in ticket["allowed"]:
            raise PlanningError(
                "ordinary_insert_ticket_ineligible",
                409,
                ticket_id=ticket_id,
                reason="manual_assignment_not_eligible",
            )
        ticket["allowed"] = [worker_index]
    return {
        visit["ticket_id"]
        for visit in (snapshot.get("current_day_state") or {}).get("visits", [])
        if visit["ticket_id"] in candidates
    }


def recorded_policy(snapshot):
    return {key: snapshot[key] for key in ("policy_version", "planning_policy") if key in snapshot}


async def preview(
    engine,
    request,
    actor,
    settings,
    provider_factory,
    planner,
    clock=utc_now,
    *,
    snapshot_override=None,
    persist=True,
    ticket_event=None,
    event_insertion=None,
):
    if (
        len(request.ticket_ids) > settings.planning_max_tickets
        or len(request.worker_ids) > settings.planning_max_workers
    ):
        raise PlanningError("planning_limit_exceeded")
    if snapshot_override is None:
        snapshot = await asyncio.to_thread(
            read_snapshot, engine, request, execution_policy(settings)
        )
    else:
        snapshot = snapshot_override
    prepared = prepare(snapshot, clock())
    ordinary_insert_ids = _ordinary_insert_ticket_ids(snapshot) if request.replan else None
    required_existing_ids = None
    if ordinary_insert_ids is not None:
        required_existing_ids = _pin_existing_visits_for_ordinary_insert(
            prepared,
            snapshot,
            ordinary_insert_ids,
            proposed_state=(event_insertion.selected.proposed_state if event_insertion else None),
        )
    if event_insertion is not None:
        selected = event_insertion.selected
        worker_indexes = {
            worker["user_id"]: index for index, worker in enumerate(prepared["workers"])
        }
        ticket = next(
            (item for item in prepared["tickets"] if item["id"] == event_insertion.ticket_id),
            None,
        )
        worker_index = worker_indexes.get(selected.worker_id)
        if ticket is None or worker_index is None or worker_index not in ticket["allowed"]:
            raise PlanningError(
                "ordinary_insert_slot_ineligible", 409, ticket_id=event_insertion.ticket_id
            )
        fixed_start = ceil((selected.service_start_at - prepared["epoch"]).total_seconds() / 60)
        ticket["allowed"] = [worker_index]
        ticket["window"] = (fixed_start, fixed_start)
    if not request.allow_partial and prepared["unassigned"]:
        raise PlanningError("incomplete_plan", unassigned=prepared["unassigned"])
    problem = solution = estimate = None
    telemetry = RoutingTelemetry()
    routes, creates, dropped = [], [], []
    # When nothing passed the precheck the empty plan needs no provider or solver call.
    if prepared["tickets"]:
        try:
            async with asyncio.timeout(settings.planning_total_timeout_seconds):
                async with provider_factory() as provider:
                    telemetry = getattr(provider, "telemetry", None) or telemetry
                    if hasattr(provider, "telemetry"):
                        provider.telemetry = telemetry

                    started = time.perf_counter()
                    try:
                        problem, nodes = await build_problem(prepared, provider, settings)
                    finally:
                        telemetry.record_stage("matrix_build", time.perf_counter() - started)

                    for attempt in range(2):
                        started = time.perf_counter()
                        try:
                            solution = await planner.solve(problem)
                        finally:
                            telemetry.record_stage("solver", time.perf_counter() - started)
                        validate_solution(problem, solution)
                        task_by_node = {
                            index: node["ticket"]["id"]
                            for index, node in enumerate(nodes)
                            if node["kind"] == "ticket"
                        }
                        if ordinary_insert_ids is not None:
                            served_ids = {
                                task_by_node[step.node]
                                for route in solution.routes
                                for step in route.steps
                                if step.node in task_by_node
                            }
                            missing_existing = required_existing_ids - served_ids
                            missing_new = ordinary_insert_ids - served_ids
                            if missing_new or missing_existing:
                                raise PlanningError(
                                    "ordinary_insert_no_gap",
                                    409,
                                    ticket_ids=sorted(missing_new),
                                    preserved_ticket_ids=sorted(required_existing_ids),
                                    missing_existing_ticket_ids=sorted(missing_existing),
                                    reason="no_feasible_gap_without_changing_published_visits",
                                )
                        if event_insertion is not None:
                            selected = event_insertion.selected
                            selected_worker = next(
                                index
                                for index, worker in enumerate(prepared["workers"])
                                if worker["user_id"] == selected.worker_id
                            )
                            selected_starts = {
                                step.arrival_time
                                for route in solution.routes
                                if route.vehicle_id == selected_worker
                                for step in route.steps
                                if step.node in task_by_node
                                and task_by_node[step.node] == event_insertion.ticket_id
                            }
                            expected_start = ceil(
                                (selected.service_start_at - prepared["epoch"]).total_seconds() / 60
                            )
                            if selected_starts != {expected_start}:
                                raise PlanningError(
                                    "ordinary_insert_slot_changed",
                                    409,
                                    ticket_id=event_insertion.ticket_id,
                                    worker_id=selected.worker_id,
                                )

                        started = time.perf_counter()
                        try:
                            route_result = await build_routes(
                                prepared, problem, nodes, solution, provider, settings
                            )
                        finally:
                            telemetry.record_stage("route_fetch", time.perf_counter() - started)
                        if route_result.corrections:
                            if attempt:
                                raise PlanningError("routing_estimate_changed", 502)
                            apply_estimate_corrections(
                                problem, prepared, nodes, route_result.corrections
                            )
                            continue
                        routes, creates = route_result.routes, route_result.creates
                        break

                    started = time.perf_counter()
                    try:
                        dropped = await asyncio.to_thread(
                            diagnose_dropped, prepared, problem, nodes, solution
                        )
                    finally:
                        telemetry.record_stage("diagnostics", time.perf_counter() - started)
                    if not request.allow_partial and dropped:
                        raise PlanningError(
                            "incomplete_plan", unassigned=prepared["unassigned"] + dropped
                        )
                    estimate = await asyncio.to_thread(
                        estimate_resources, prepared, problem, nodes, dropped
                    )
        except asyncio.CancelledError:
            telemetry.record_error("planning_cancelled")
            logger.warning("planning_cancelled routing_metrics=%s", telemetry.snapshot())
            raise
        except TimeoutError as error:
            telemetry.record_error("planning_timeout")
            logger.warning(
                "planning_failed reason=planning_timeout routing_metrics=%s", telemetry.snapshot()
            )
            raise PlanningError("planning_timeout", 504) from error
        except PlanningError as error:
            if not telemetry.snapshot()["error_reasons"].get(error.code):
                telemetry.record_error(error.code)
            logger.warning(
                "planning_failed reason=%s routing_metrics=%s", error.code, telemetry.snapshot()
            )
            raise
        except GeoapifyRoutingError as error:
            if not telemetry.snapshot()["error_reasons"].get("routing_invalid_response"):
                telemetry.record_error("routing_invalid_response")
            logger.warning(
                "planning_failed reason=routing_invalid_response routing_metrics=%s",
                telemetry.snapshot(),
            )
            raise PlanningError("routing_invalid_response", 502) from error
    unassigned = sorted(prepared["unassigned"] + dropped, key=lambda item: item["ticket_id"])
    visit_factors(prepared, routes)
    plan_id = uuid4()
    expires = clock() + timedelta(seconds=settings.planning_preview_ttl_seconds)
    public = normalize(
        {
            "plan_id": str(plan_id),
            "planning_policy": snapshot["planning_policy"],
            "case_policy_version": snapshot.get("policy_version"),
            "state": "ready",
            "outcome": outcome(routes, unassigned),
            "route_date": request.route_date,
            "service_area_id": snapshot.get("service_area_id"),
            "day_revision": snapshot.get("current_day_revision"),
            "timezone": "Europe/Moscow",
            "expires_at": expires,
            "solver_status": solution.status if solution else None,
            "objective_components": solution.objective_components.model_dump(mode="json")
            if solution and solution.objective_components
            else None,
            "metrics": {
                **plan_metrics(request, prepared, routes, unassigned),
                "routing": telemetry.snapshot(),
            },
            "routes": routes,
            "unassigned": unassigned,
            "excluded_workers": prepared["excluded_workers"],
            "resource_estimate": estimate,
            "warnings": ["estimated_transit"]
            if any(w["profile"] == "approximated_transit" for w in prepared["workers"])
            else [],
        }
    )
    if request.replan:
        if public["outcome"] == "empty" and public["unassigned"]:
            public["outcome"] = "partial"
        previous_state = snapshot.get("current_day_state") or {}
        lifecycle_by_ticket = {
            item["id"]: item["lifecycle_state"] for item in snapshot["area_scope"]["tickets"]
        }
        proposed_state = build_replan_state(public, previous_state, lifecycle_by_ticket)
        if event_insertion is not None:
            violations = validate_immutable_route_invariants(
                previous_state,
                proposed_state,
                inserted_ticket_id=event_insertion.ticket_id,
                lifecycle_by_ticket=lifecycle_by_ticket,
            )
            if violations:
                raise PlanningError(
                    "ordinary_insert_invariant_violation",
                    409,
                    ticket_id=event_insertion.ticket_id,
                    violations=violations,
                )
        tickets_meta = {
            ticket["id"]: {
                "category": ticket.get("category"),
                "received_at": ticket.get("received_at"),
                "response_deadline_at": ticket.get("response_deadline_at"),
            }
            for ticket in snapshot.get("tickets", [])
        }
        public["replan_diff"] = normalize(
            {
                "from_revision": snapshot.get("current_day_revision"),
                **diff_states(previous_state, proposed_state, tickets_metadata=tickets_meta),
                "emergency_response": emergency_response_estimates(snapshot, public),
            }
        )

    if ticket_event is not None:
        public["ticket_event"] = build_ticket_event_result(
            ticket_event, snapshot, prepared, public, event_insertion
        )
        if public.get("replan_diff") is not None:
            public["replan_diff"]["ticket_event"] = public["ticket_event"]

    if persist:

        def save_preview():
            with Session(engine) as session, session.begin():
                session.add(
                    PlanningPlan(
                        id=plan_id,
                        route_date=request.route_date,
                        created_by=actor,
                        expires_at=expires,
                        state="ready",
                        input_fingerprint=fingerprint(snapshot),
                        input_snapshot=snapshot,
                        result_snapshot={
                            "public": public,
                            "route_creates": creates,
                            "problem": problem.model_dump(mode="json") if problem else None,
                            "solution": solution.model_dump(mode="json") if solution else None,
                            "algorithm_version": 1,
                        },
                    )
                )

        await asyncio.to_thread(save_preview)
    return public


def snapshot_with_experimental_windows(snapshot: dict, windows, route_date) -> dict:
    """Copy a planning input and widen selected windows without touching live rows."""
    result = copy.deepcopy(snapshot)
    tickets = {ticket["id"]: ticket for ticket in result["tickets"]}
    local_date = route_date
    for override in windows:
        ticket = tickets.get(override.ticket_id)
        if ticket is None:
            raise PlanningError("experimental_ticket_not_in_day", ticket_id=override.ticket_id)
        original_start = datetime.fromisoformat(ticket["visit_window_start"])
        original_end = datetime.fromisoformat(ticket["visit_window_end"])
        proposed_start = override.visit_window_start
        proposed_end = override.visit_window_end
        if (
            proposed_start.astimezone(MOSCOW).date() != local_date
            or proposed_end.astimezone(MOSCOW).date() != local_date
        ):
            raise PlanningError("experimental_window_outside_day", ticket_id=override.ticket_id)
        if proposed_start > original_start or proposed_end < original_end:
            raise PlanningError(
                "experimental_window_must_only_expand", ticket_id=override.ticket_id
            )
        ticket["visit_window_start"] = proposed_start.isoformat()
        ticket["visit_window_end"] = proposed_end.isoformat()
    return result


def emergency_response_estimates(snapshot: dict, public: dict) -> list[dict]:
    """Expose arrival and service-start forecasts from the immutable receipt time."""
    scheduled = {
        stop["ticket_id"]: stop
        for route in public.get("routes", [])
        for stop in route.get("stops", [])
    }
    unassigned = {
        item["ticket_id"]: item.get("reason", {}).get("code")
        for item in public.get("unassigned", [])
    }
    estimates = []
    for ticket in snapshot.get("tickets", []):
        if ticket.get("category") != "emergency":
            continue
        stop = scheduled.get(ticket["id"])
        received = (
            datetime.fromisoformat(ticket["received_at"]) if ticket.get("received_at") else None
        )
        arrival = datetime.fromisoformat(stop["arrival_at"]) if stop else None
        service_start = datetime.fromisoformat(stop["service_start_at"]) if stop else None
        service_end = datetime.fromisoformat(stop["service_end_at"]) if stop else None
        deadline = (
            datetime.fromisoformat(ticket["sla_deadline_at"])
            if ticket.get("sla_deadline_at")
            else None
        )
        arrival_minutes = (
            max(0, ceil((arrival - received).total_seconds() / 60))
            if arrival is not None and received is not None
            else None
        )
        service_minutes = (
            max(0, ceil((service_start - received).total_seconds() / 60))
            if service_start is not None and received is not None
            else None
        )
        estimates.append(
            {
                "ticket_id": ticket["id"],
                "received_at": received,
                "arrival_at": arrival,
                "service_start_at": service_start,
                "service_end_at": service_end,
                "reaction_to_arrival_minutes": arrival_minutes,
                "reaction_to_service_start_minutes": service_minutes,
                "within_60_minutes_to_arrival": (
                    arrival_minutes <= 60 if arrival_minutes is not None else None
                ),
                "within_120_minutes_to_arrival": (
                    arrival_minutes <= 120 if arrival_minutes is not None else None
                ),
                "service_deadline_at": deadline,
                "service_deadline_met": (
                    service_end <= deadline
                    if service_end is not None and deadline is not None
                    else None
                ),
                "status": (
                    "scheduled"
                    if stop is not None
                    else "received_at_missing"
                    if received is None
                    else "unassigned"
                ),
                "unassigned_reason": unassigned.get(ticket["id"]),
            }
        )
    return estimates


def build_ticket_event_result(ticket_event, snapshot, prepared, public, event_insertion=None):
    """Build the dispatcher-facing event decision from the proposal and saved baseline."""
    ticket_id = ticket_event["ticket_id"]
    scheduled = {
        stop["ticket_id"]: {**stop, "worker_id": route["worker_id"]}
        for route in public.get("routes", [])
        for stop in route.get("stops", [])
    }
    stop = scheduled.get(ticket_id)
    diff = public.get("replan_diff") or {}
    forecast = next(
        (item for item in diff.get("emergency_response", []) if item["ticket_id"] == ticket_id),
        None,
    )
    category = ticket_event["category"]
    if category == "emergency":
        if stop is None:
            outcome_code = "emergency_unassigned"
            if not prepared["workers"] and any(
                item.get("reason", {}).get("code")
                in {"active_stage_not_completed", "active_work_eta_unknown"}
                for item in prepared["excluded_workers"]
            ):
                outcome_code = "waiting_safe_point"
            can_apply = False
        else:
            response_minutes = (forecast or {}).get("reaction_to_service_start_minutes")
            if (forecast or {}).get("service_deadline_met") is False:
                outcome_code = "sla_violation"
            elif response_minutes is not None and response_minutes > 120:
                outcome_code = "sla_violation"
            elif response_minutes is not None and response_minutes > 60:
                outcome_code = "sla_risk"
            else:
                outcome_code = "emergency_replan_ready"
            can_apply = True
    else:
        outcome_code = "insertion_ready"
        can_apply = stop is not None and event_insertion is not None

    selected_slot = None
    road_contribution = None
    if event_insertion is not None:
        candidate = event_insertion.selected
        placement = next(
            (item for item in diff.get("added", []) if item["ticket_id"] == ticket_id),
            None,
        )
        if (
            placement is None
            or placement["worker_id"] != candidate.worker_id
            or placement["sequence"] != candidate.insertion_sequence
            or datetime.fromisoformat(placement["service_start_at"]) != candidate.service_start_at
        ):
            raise PlanningError(
                "ordinary_insert_slot_changed",
                409,
                ticket_id=ticket_id,
                worker_id=candidate.worker_id,
            )
        service_duration = max(
            0,
            int(
                (
                    datetime.fromisoformat(placement["service_end_at"])
                    - datetime.fromisoformat(placement["service_start_at"])
                ).total_seconds()
                // 60
            ),
        )
        selected_slot = {
            "worker_id": candidate.worker_id,
            "sequence": placement["sequence"],
            "arrival_at": placement["arrival_at"],
            "service_start_at": placement["service_start_at"],
            "service_end_at": placement["service_end_at"],
            "service_minutes": service_duration,
        }
        road_contribution = {
            "inbound_minutes": candidate.travel_to_minutes,
            "outbound_minutes": candidate.travel_from_minutes,
            "replaced_leg_minutes": candidate.replaced_travel_minutes,
            "added_travel_minutes": candidate.added_travel_minutes,
            "service_minutes": service_duration,
        }
    elif stop is not None:
        event_route = next(
            route
            for route in public.get("routes", [])
            if any(item["ticket_id"] == ticket_id for item in route.get("stops", []))
        )
        local_sequence = stop["sequence"]
        inbound_leg = next(
            (
                leg
                for leg in event_route.get("legs", [])
                if leg["to_sequence"] == local_sequence + 1
            ),
            None,
        )
        outbound_leg = next(
            (
                leg
                for leg in event_route.get("legs", [])
                if leg["from_sequence"] == local_sequence + 1
            ),
            None,
        )
        selected_slot = {
            "worker_id": stop["worker_id"],
            "sequence": stop["sequence"],
            "arrival_at": stop["arrival_at"],
            "service_start_at": stop["service_start_at"],
            "service_end_at": stop["service_end_at"],
            "service_minutes": stop["effective_service_minutes"],
        }
        travel_change = (diff.get("metrics") or {}).get("travel_minutes") or {}
        road_contribution = {
            "inbound_minutes": (
                ceil(inbound_leg["duration_seconds"] / 60) if inbound_leg else None
            ),
            "outbound_minutes": (
                ceil(outbound_leg["duration_seconds"] / 60) if outbound_leg else None
            ),
            "replan_travel_delta_minutes": travel_change.get("delta"),
            "service_minutes": stop["effective_service_minutes"],
        }

    changed_ids = {
        item["ticket_id"] for item in diff.get("changed", []) if item["ticket_id"] != ticket_id
    }
    changed_ids.update(
        item["ticket_id"] for item in diff.get("removed", []) if item["ticket_id"] != ticket_id
    )
    lifecycle_by_ticket = {
        item["id"]: item["lifecycle_state"] for item in snapshot["area_scope"]["tickets"]
    }
    frozen = [
        visit
        for visit in (snapshot.get("current_day_state") or {}).get("visits", [])
        if lifecycle_by_ticket.get(visit["ticket_id"]) in {"en_route", "in_progress"}
    ]
    rejection = next(
        (item for item in public.get("unassigned", []) if item["ticket_id"] == ticket_id), None
    )
    candidates = (rejection or {}).get("candidates", [])
    return normalize(
        {
            **ticket_event,
            "outcome": outcome_code,
            "can_apply": can_apply,
            "selected_slot": selected_slot,
            "road_contribution": road_contribution,
            "shifted_ticket_ids": sorted(changed_ids),
            "preserved_current_stage": frozen,
            "candidate_reasons": candidates,
            "sla_forecast": forecast,
            "reason": (rejection or {}).get("reason", {}).get("code"),
        }
    )


def _experiment_summary(public: dict) -> dict:
    return {
        "outcome": public["outcome"],
        "metrics": public["metrics"],
        "routes": public["routes"],
        "unassigned": public["unassigned"],
        "warnings": public["warnings"],
        "replan_diff": public.get("replan_diff"),
    }


async def compare_window_experiment(
    engine,
    request,
    windows,
    actor,
    settings,
    provider_factory,
    planner,
    clock=utc_now,
    *,
    snapshot,
):
    """Run two non-persisted calculations over the same captured input snapshot."""
    scenario_snapshot = snapshot_with_experimental_windows(snapshot, windows, request.route_date)
    original_tickets = {ticket["id"]: ticket for ticket in snapshot["tickets"]}
    baseline = await preview(
        engine,
        request,
        actor,
        settings,
        provider_factory,
        planner,
        clock,
        snapshot_override=snapshot,
        persist=False,
    )
    experiment = await preview(
        engine,
        request,
        actor,
        settings,
        provider_factory,
        planner,
        clock,
        snapshot_override=scenario_snapshot,
        persist=False,
    )
    return {
        "experimental": True,
        "applied": False,
        "service_area_id": request.service_area_id,
        "route_date": request.route_date,
        "base_day_revision": snapshot.get("current_day_revision"),
        "window_overrides": [
            {
                "ticket_id": window.ticket_id,
                "original_visit_window_start": original_tickets[window.ticket_id][
                    "visit_window_start"
                ],
                "original_visit_window_end": original_tickets[window.ticket_id]["visit_window_end"],
                "scenario_visit_window_start": window.visit_window_start,
                "scenario_visit_window_end": window.visit_window_end,
            }
            for window in windows
        ],
        "baseline": _experiment_summary(baseline),
        "experiment": _experiment_summary(experiment),
    }


def plan_workers(session: Session, snapshot: dict) -> list[dict]:
    """Brigade and office come from the plan's snapshot, so later membership changes,
    a new role or archiving never rewrite whom the plan belonged to."""
    brigades = {row["id"]: row for row in snapshot.get("brigades", [])}
    members = {row["worker_id"]: row["brigade_id"] for row in snapshot.get("members", [])}
    workers = sorted(snapshot.get("workers", []), key=lambda row: row["user_id"])
    users = {
        row.id: row
        for row in session.execute(
            select(
                User.id, User.surname, User.name, User.lastname, User.role, User.archived_at
            ).where(User.id.in_([row["user_id"] for row in workers]))
        )
    }
    result = []
    for worker in workers:
        brigade = brigades.get(members.get(worker["user_id"]))
        user = users.get(worker["user_id"])
        result.append(
            {
                "worker_id": worker["user_id"],
                "full_name": " ".join(
                    part for part in (user.surname, user.name, user.lastname) if part
                )
                if user
                else None,
                "brigade_id": brigade["id"] if brigade else None,
                "brigade_name": brigade["name"] if brigade else None,
                "office_id": worker.get("stock_office_id")
                or (brigade["office_id"] if brigade else None),
                "role": user.role if user else None,
                "archived_at": user.archived_at if user else None,
            }
        )
    return result


def plan_state(session: Session, plan: PlanningPlan, clock=utc_now) -> dict:
    """Public stored plan and its live state; the caller owns one read-only snapshot."""
    result = {**legacy_public(plan.result_snapshot["public"]), "state": plan.state}
    result["planning_policy"] = plan.input_snapshot.get("planning_policy")
    if plan.state == "ready" and plan.expires_at <= clock():
        result["state"] = "expired"
    if plan.state == "applied":
        request = PreviewRequest.model_validate(plan.input_snapshot["request"])
        result["is_current"] = (
            fingerprint(
                load_snapshot(
                    session, request, policy_snapshot=recorded_policy(plan.input_snapshot)
                )
            )
            == plan.applied_fingerprint
        )
        result["apply_result"] = plan.apply_result
    return result


def read_plan(engine, plan_id: UUID, clock=utc_now):
    with Session(engine) as session, session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        plan = session.get(PlanningPlan, plan_id)
        if plan is None:
            raise PlanningError("plan_not_found", 404)
        result = {**legacy_public(plan.result_snapshot["public"]), "state": plan.state}
        result["planning_policy"] = plan.input_snapshot.get("planning_policy")
        if plan.state == "ready" and plan.expires_at <= clock():
            result["state"] = "expired"
        if plan.state == "applied":
            request = PreviewRequest.model_validate(plan.input_snapshot["request"])
            result["is_current"] = (
                fingerprint(
                    load_snapshot(
                        session, request, policy_snapshot=recorded_policy(plan.input_snapshot)
                    )
                )
                == plan.applied_fingerprint
            )
            result["apply_result"] = plan.apply_result
        result["workers"] = plan_workers(session, plan.input_snapshot)
        return result


def apply_plan(engine, plan_id: UUID, clock=utc_now):
    error = None
    with Session(engine) as session, session.begin():
        lock_planning_mutation(session)
        plan = session.scalar(
            select(PlanningPlan).where(PlanningPlan.id == plan_id).with_for_update()
        )
        if plan is None:
            raise PlanningError("plan_not_found", 404)
        if plan.state == "applied":
            return {**plan.apply_result, "already_applied": True}
        snapshot_policy(plan.input_snapshot)
        request = PreviewRequest.model_validate(plan.input_snapshot["request"])
        ticket_event = plan.result_snapshot.get("public", {}).get("ticket_event")
        if ticket_event is not None and not ticket_event.get("can_apply", False):
            raise PlanningError(
                "ticket_event_preview_not_applicable",
                409,
                ticket_id=ticket_event.get("ticket_id"),
                outcome=ticket_event.get("outcome"),
            )
        if not plan.result_snapshot["route_creates"] and not request.replan:
            raise PlanningError("plan_has_no_assignments", 409)
        current = load_snapshot(
            session, request, policy_snapshot=recorded_policy(plan.input_snapshot)
        )
        apply_at = clock()
        if plan.state == "expired" or plan.expires_at <= apply_at:
            plan.state = "expired"
            error = PlanningError("plan_expired", 409)
        elif (
            request.base_day_revision is not None
            and current.get("current_day_revision") != request.base_day_revision
        ):
            plan.state = "stale"
            error = PlanningError(
                "day_revision_stale",
                409,
                current_revision=current.get("current_day_revision"),
            )
        elif plan.state != "ready" or fingerprint(current) != plan.input_fingerprint:
            plan.state = "stale"
            error = PlanningError("plan_stale", 409)
        elif request.replan and not set(request.worker_ids) <= set(
            roster_ids(current.get("current_day_roster"))
        ):
            plan.state = "stale"
            error = PlanningError(
                "day_roster_expanded",
                409,
                worker_ids=sorted(
                    set(request.worker_ids) - set(roster_ids(current.get("current_day_roster")))
                ),
            )
        else:
            prepared = prepare(current, apply_at)
            selected = {r["worker_id"] for r in plan.result_snapshot["route_creates"]}
            if selected & {w["worker_id"] for w in prepared["excluded_workers"]}:
                plan.state = "stale"
                error = PlanningError("shift_already_started", 409)
            elif request.replan and any(
                datetime.fromisoformat(route["departure_at"]) < apply_at
                for route in plan.result_snapshot["public"]["routes"]
            ):
                plan.state = "stale"
                error = PlanningError("plan_stale", 409, reason="replan_departure_elapsed")
        if error is None:
            data = [RouteCreate.model_validate(r) for r in plan.result_snapshot["route_creates"]]
            ticket_ids = sorted(s.ticket_id for r in data for s in r.stops if s.ticket_id)
            session.scalars(
                select(Ticket)
                .where(Ticket.id.in_(ticket_ids))
                .order_by(Ticket.id)
                .with_for_update()
            ).all()
            try:
                saved = save_routes_in_transaction(session, data)
            except RouteValidationError as route_error:
                raise PlanningError(
                    "plan_routes_rejected",
                    409,
                    reason=route_error.code,
                    message=str(route_error),
                ) from route_error
            visits = {
                s["ticket_id"]: s
                for r in plan.result_snapshot["public"]["routes"]
                for s in r["stops"]
            }
            for route, stored in zip(data, saved, strict=True):
                for stop in route.stops:
                    if stop.ticket_id is None:
                        continue
                    update_assignment_in_transaction(
                        session,
                        stop.ticket_id,
                        route.worker_id,
                        is_pinned=False,
                        actor_id=plan.created_by,
                        source="plan",
                        planned_at=datetime.fromisoformat(
                            visits[stop.ticket_id]["service_start_at"]
                        ),
                    )
                    ticket = session.get(Ticket, stop.ticket_id)
                    ticket.planned_start_at = datetime.fromisoformat(
                        visits[stop.ticket_id]["service_start_at"]
                    )
                    ticket.planned_end_at = datetime.fromisoformat(
                        visits[stop.ticket_id]["service_end_at"]
                    )
                    ticket.updated_at = clock()
                session.add(
                    PlanningPlanRoute(
                        plan_id=plan_id, worker_id=route.worker_id, route_id=stored.id
                    )
                )
            session.flush()
            if request.replan:
                assigned_ids = set(ticket_ids)
                unassigned_reasons = {
                    item["ticket_id"]: item["reason"].get("code")
                    for item in plan.result_snapshot["public"].get("unassigned", [])
                }
                from app.modules.execution import service as execution_service
                from app.modules.execution.enums import TicketLifecycleState, WorkEventType
                from app.modules.execution.schemas import ExecutionCommand

                for ticket_id in sorted(set(request.ticket_ids) - assigned_ids):
                    ticket = session.get(Ticket, ticket_id)
                    if ticket is None or ticket.lifecycle_state not in {
                        TicketLifecycleState.ASSIGNED,
                        TicketLifecycleState.DISPATCHED,
                    }:
                        continue
                    command = ExecutionCommand.model_construct(
                        expected_revision=ticket.revision,
                        occurred_at=clock(),
                        reason="remaining_day_replan",
                        expected_available_at=None,
                        payload={
                            "assignment_source": "plan",
                            "plan_id": str(plan_id),
                            "unassigned_reason": unassigned_reasons.get(ticket_id),
                        },
                    )
                    execution_service.apply_ticket_event(
                        session,
                        ticket_id,
                        WorkEventType.UNASSIGN,
                        command,
                        actor_id=plan.created_by,
                        idempotency_key=(
                            f"replan-unassign:{plan_id}:{ticket_id}:{ticket.revision}"
                        ),
                    )
            result = {
                "plan_id": str(plan_id),
                "state": "applied",
                "already_applied": False,
                "routes": [
                    {"id": r.id, "worker_id": r.worker_id, "route_number": r.route_number}
                    for r in saved
                ],
                "assigned_ticket_ids": ticket_ids,
            }
            service_area_id = current.get("service_area_id")
            revision_row = None
            if service_area_id is not None:
                # One revision of the area-day is current; publishing hands the marker
                # over inside this transaction, so two applies never both look current.
                revision_row = publish_revision(
                    session,
                    service_area_id=current.get("service_area_id"),
                    route_date=request.route_date,
                    actor_id=plan.created_by,
                    reason=(
                        "ticket_inserted"
                        if ticket_event and ticket_event["category"] != "emergency"
                        else "emergency_replan"
                        if ticket_event
                        else "event_replan"
                        if request.replan
                        else "plan_applied"
                    ),
                    fingerprint="pending",
                    plan_state=(
                        build_replan_state(
                            plan.result_snapshot["public"],
                            current.get("current_day_state") or {},
                            {
                                item["id"]: item["lifecycle_state"]
                                for item in current["area_scope"]["tickets"]
                            },
                            {
                                route.worker_id: stored.id
                                for route, stored in zip(data, saved, strict=True)
                            },
                            current["area_scope"]["tickets"],
                        )
                        if request.replan
                        else build_plan_state(
                            plan.result_snapshot["public"],
                            {
                                route.worker_id: stored.id
                                for route, stored in zip(data, saved, strict=True)
                            },
                            current["area_scope"]["tickets"],
                        )
                    ),
                    result=result,
                    at=clock(),
                    plan_id=plan_id,
                    event_id=ticket_event["source_event_id"] if ticket_event else None,
                    # A replan keeps the day's roster; a dispatcher's own selection is
                    # admitted with everyone selected, including engineers left idle.
                    roster_additions=(
                        ()
                        if request.replan
                        else roster_from_snapshot(current, current["service_area_id"])
                    ),
                )
                result["day_revision"] = revision_row.revision
                revision_row.result = result
                plan.result_snapshot = {
                    **plan.result_snapshot,
                    "public": {
                        **plan.result_snapshot["public"],
                        "day_revision": revision_row.revision,
                    },
                }
                session.flush()
                _notify_rescheduled_tickets(session, revision_row)
            applied_fingerprint = fingerprint(
                load_snapshot(
                    session, request, policy_snapshot=recorded_policy(plan.input_snapshot)
                )
            )
            if revision_row is not None:
                revision_row.fingerprint = applied_fingerprint
            plan.applied_at = clock()
            plan.applied_fingerprint = applied_fingerprint
            plan.apply_result = result
            plan.state = "applied"
            publish_schedule_updated(session)
    if error is not None:
        raise error
    return result

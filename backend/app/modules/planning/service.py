"""Read a snapshot, calculate outside transactions, then apply one immutable proposal."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.planning_guard import lock_planning_mutation
from app.modules.planning.day_models import DayPlanRevision
from app.modules.planning.diagnostics import (
    diagnose_dropped,
    estimate_resources,
    outcome,
    plan_metrics,
    visit_factors,
)
from app.modules.planning.eligibility import prepare
from app.modules.planning.errors import PlanningError
from app.modules.planning.geometry import build_routes
from app.modules.planning.matrices import build_problem
from app.modules.planning.models import PlanningPlan, PlanningPlanRoute
from app.modules.planning.policy import execution_policy, snapshot_policy
from app.modules.planning.reasons import legacy_public
from app.modules.planning.repository import load_snapshot
from app.modules.planning.schemas import PreviewRequest
from app.modules.planning.snapshot import fingerprint, normalize
from app.modules.planning.validation import validate_solution
from app.modules.routing.client import GeoapifyRoutingError
from app.modules.routing.schemas import RouteCreate
from app.modules.routing.service import save_routes_in_transaction
from app.modules.tickets.models import Ticket
from app.modules.tickets.service import replace_assignees_in_transaction


def utc_now():
    return datetime.now(UTC)


def read_snapshot(engine, request, policy):
    with Session(engine) as session, session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        return load_snapshot(
            session,
            request,
            policy_snapshot={
                "policy_version": policy.policy_version,
                "planning_policy": policy.model_dump(mode="json"),
            },
        )


def recorded_policy(snapshot):
    return {key: snapshot[key] for key in ("policy_version", "planning_policy") if key in snapshot}


async def preview(engine, request, actor, settings, provider_factory, planner, clock=utc_now):
    if (
        len(request.ticket_ids) > settings.planning_max_tickets
        or len(request.worker_ids) > settings.planning_max_workers
    ):
        raise PlanningError("planning_limit_exceeded")
    snapshot = await asyncio.to_thread(read_snapshot, engine, request, execution_policy(settings))
    prepared = prepare(snapshot, clock())
    if not request.allow_partial and prepared["unassigned"]:
        raise PlanningError("incomplete_plan", unassigned=prepared["unassigned"])
    problem = solution = estimate = None
    routes, creates, dropped = [], [], []
    # When nothing passed the precheck the empty plan needs no provider or solver call.
    if prepared["tickets"]:
        try:
            async with asyncio.timeout(settings.planning_total_timeout_seconds):
                async with provider_factory() as provider:
                    problem, nodes = await build_problem(prepared, provider, settings)
                    solution = await planner.solve(problem)
                    validate_solution(problem, solution)
                    dropped = await asyncio.to_thread(
                        diagnose_dropped, prepared, problem, nodes, solution
                    )
                    if not request.allow_partial and dropped:
                        raise PlanningError(
                            "incomplete_plan", unassigned=prepared["unassigned"] + dropped
                        )
                    routes, creates = await build_routes(
                        prepared,
                        problem,
                        nodes,
                        solution,
                        provider,
                        settings,
                    )
                    estimate = await asyncio.to_thread(
                        estimate_resources, prepared, problem, nodes, dropped
                    )
        except TimeoutError as error:
            raise PlanningError("planning_timeout", 504) from error
        except GeoapifyRoutingError as error:
            raise PlanningError("routing_invalid_response", 502) from error
    unassigned = sorted(prepared["unassigned"] + dropped, key=lambda item: item["ticket_id"])
    visit_factors(prepared, routes)
    plan_id = uuid4()
    expires = clock() + timedelta(seconds=settings.planning_preview_ttl_seconds)
    public = normalize(
        {
            "plan_id": str(plan_id),
            "planning_policy": snapshot["planning_policy"],
            "state": "ready",
            "outcome": outcome(routes, unassigned),
            "route_date": request.route_date,
            "district_id": snapshot.get("district_id"),
            "day_revision": snapshot.get("current_day_revision"),
            "timezone": "Europe/Moscow",
            "expires_at": expires,
            "solver_status": solution.status if solution else None,
            "metrics": plan_metrics(request, prepared, routes, unassigned),
            "routes": routes,
            "unassigned": unassigned,
            "excluded_workers": prepared["excluded_workers"],
            "resource_estimate": estimate,
            "warnings": ["estimated_transit"]
            if any(w["profile"] == "approximated_transit" for w in prepared["workers"])
            else [],
        }
    )

    def persist():
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

    await asyncio.to_thread(persist)
    return public


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
        if not plan.result_snapshot["route_creates"]:
            raise PlanningError("plan_has_no_assignments", 409)
        snapshot_policy(plan.input_snapshot)
        request = PreviewRequest.model_validate(plan.input_snapshot["request"])
        current = load_snapshot(
            session, request, policy_snapshot=recorded_policy(plan.input_snapshot)
        )
        if plan.state == "expired" or plan.expires_at <= clock():
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
        else:
            prepared = prepare(current, clock())
            selected = {r["worker_id"] for r in plan.result_snapshot["route_creates"]}
            if selected & {w["worker_id"] for w in prepared["excluded_workers"]}:
                plan.state = "stale"
                error = PlanningError("shift_already_started", 409)
        if error is None:
            data = [RouteCreate.model_validate(r) for r in plan.result_snapshot["route_creates"]]
            ticket_ids = sorted(s.ticket_id for r in data for s in r.stops if s.ticket_id)
            session.scalars(
                select(Ticket)
                .where(Ticket.id.in_(ticket_ids))
                .order_by(Ticket.id)
                .with_for_update()
            ).all()
            saved = save_routes_in_transaction(session, data)
            visits = {
                s["ticket_id"]: s
                for r in plan.result_snapshot["public"]["routes"]
                for s in r["stops"]
            }
            for route, stored in zip(data, saved, strict=True):
                for stop in route.stops:
                    if stop.ticket_id is None:
                        continue
                    replace_assignees_in_transaction(
                        session,
                        stop.ticket_id,
                        [route.worker_id],
                        actor_id=plan.created_by,
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
            district_id = current.get("district_id")
            revision_row = None
            if district_id is not None:
                previous_revision = current.get("current_day_revision") or 0
                session.execute(
                    text(
                        """
                        UPDATE day_plan_revisions
                        SET is_current = false
                        WHERE district_id = :district_id
                          AND route_date = :route_date
                          AND is_current
                        """
                    ),
                    {"district_id": district_id, "route_date": request.route_date},
                )
                revision_row = DayPlanRevision(
                    district_id=district_id,
                    route_date=request.route_date,
                    revision=previous_revision + 1,
                    previous_revision=previous_revision or None,
                    actor_id=plan.created_by,
                    fingerprint="pending",
                    diff={"assigned_ticket_ids": ticket_ids},
                    result=result,
                    is_current=True,
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
                session.add(revision_row)
                session.flush()
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
    if error is not None:
        raise error
    return result

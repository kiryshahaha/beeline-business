"""Observer commands for calculating, inspecting and atomically applying day plans."""

import asyncio
from datetime import date
from threading import BoundedSemaphore
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_engine, get_session
from app.modules.auth.dependencies import require_roles
from app.modules.execution import day_state
from app.modules.execution.schemas import RedirectCommand, WorkerDayStateRead
from app.modules.planning import service
from app.modules.planning.case_policy import case_policy
from app.modules.planning.errors import PlanningError
from app.modules.planning.planner_client import PlannerClient
from app.modules.planning.policy import execution_policy
from app.modules.planning.schemas import (
    ApplyRequest,
    ApplyResult,
    PlanRead,
    PolicyRead,
    PreviewRequest,
)
from app.modules.routing.client import AsyncGeoapifyRoutingClient
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead

_preview_slots = BoundedSemaphore(2)

router = APIRouter(prefix="/api/v1/planning", tags=["planning"])
Observer = Annotated[UserRead, Depends(require_roles(UserRole.OBSERVER))]
DatabaseSession = Annotated[Session, Depends(get_session)]
IdempotencyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


def get_clock():
    return service.utc_now


def get_planning_engine():
    return get_engine()


def planning_settings():
    settings = get_settings()
    if not settings.planning_enabled:
        raise HTTPException(503, detail={"code": "planning_disabled"})
    return settings


def get_planner_client(settings=Depends(planning_settings)):
    if not settings.planner_base_url or not settings.planner_service_token.get_secret_value():
        raise HTTPException(503, detail={"code": "planner_not_configured"})
    return PlannerClient(settings)


def get_provider_factory(settings=Depends(planning_settings)):
    if not settings.geoapify_api_key:
        raise HTTPException(503, detail={"code": "routing_not_configured"})
    return lambda: AsyncGeoapifyRoutingClient(
        settings.geoapify_api_key, timeout=settings.geoapify_timeout_seconds
    )


def fail(error):
    if isinstance(error, PlanningError):
        raise HTTPException(error.status, detail={"code": error.code, **error.details}) from error
    raise HTTPException(503, detail={"code": "planning_database_unavailable"}) from error


@router.get("/policy", response_model=PolicyRead)
def read_policy(_: Observer):
    return PolicyRead(execution=execution_policy(get_settings()), case_contract=case_policy())


@router.post(
    "/preview", status_code=201, response_model=PlanRead, response_model_exclude_unset=True
)
async def preview(
    data: PreviewRequest,
    actor: Observer,
    response: Response,
    engine=Depends(get_planning_engine),
    settings=Depends(planning_settings),
    provider=Depends(get_provider_factory),
    planner=Depends(get_planner_client),
    clock=Depends(get_clock),
):
    if not _preview_slots.acquire(blocking=False):
        raise HTTPException(503, detail={"code": "planning_busy"}, headers={"Retry-After": "5"})
    try:
        result = await service.preview(engine, data, actor.id, settings, provider, planner, clock)
        response.headers["Location"] = f"/api/v1/planning/plans/{result['plan_id']}"
        return result
    except (PlanningError, OperationalError) as error:
        fail(error)
    finally:
        _preview_slots.release()


@router.post(
    "/days/{district_id}/{route_date}/redirect",
    response_model=WorkerDayStateRead,
)
def redirect_worker(
    district_id: int,
    route_date: date,
    data: RedirectCommand,
    actor: Observer,
    session: DatabaseSession,
    idempotency_key: IdempotencyHeader = None,
) -> WorkerDayStateRead:
    if idempotency_key is None or not idempotency_key.strip() or len(idempotency_key) > 128:
        raise HTTPException(422, detail="Требуется непустой Idempotency-Key длиной до 128 символов")
    try:
        return day_state.redirect_worker(
            session,
            district_id,
            route_date,
            data,
            actor_id=actor.id,
            idempotency_key=idempotency_key.strip(),
        )
    except day_state.DayStateRevisionConflict as error:
        raise HTTPException(
            409,
            detail={"code": error.code, "current_revision": error.current_revision},
        ) from error
    except day_state.IdempotencyConflict as error:
        raise HTTPException(
            409,
            detail={"code": "idempotency_conflict", "event_id": error.event_id},
        ) from error
    except day_state.DistrictNotFound as error:
        raise HTTPException(404, detail="Район не найден") from error
    except day_state.UnsafeRedirect as error:
        raise HTTPException(422, detail=str(error)) from error


@router.get("/plans/{plan_id}", response_model=PlanRead, response_model_exclude_unset=True)
def read_plan(
    plan_id: UUID, _: Observer, engine=Depends(get_planning_engine), clock=Depends(get_clock)
):
    try:
        return service.read_plan(engine, plan_id, clock)
    except (PlanningError, OperationalError) as error:
        fail(error)


@router.post("/plans/{plan_id}/apply", response_model=ApplyResult)
async def apply_plan(
    plan_id: UUID,
    _: Observer,
    data: ApplyRequest | None = None,
    engine=Depends(get_planning_engine),
    _settings=Depends(planning_settings),
    clock=Depends(get_clock),
):
    try:
        return await asyncio.to_thread(service.apply_plan, engine, plan_id, clock)
    except (PlanningError, OperationalError) as error:
        fail(error)

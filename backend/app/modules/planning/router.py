"""Observer commands for calculating, inspecting and atomically applying day plans."""

import asyncio
from threading import BoundedSemaphore
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.db.session import get_engine
from app.modules.appliances.inventory import InventoryError
from app.modules.auth.dependencies import require_roles
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
    if isinstance(error, InventoryError):
        raise HTTPException(error.status, detail=error.detail()) from error
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
    except (PlanningError, InventoryError, OperationalError) as error:
        fail(error)

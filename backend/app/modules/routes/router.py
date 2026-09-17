"""Authorized route history and GeoJSON downloads."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.routes import service
from app.modules.routes.schemas import RouteBatchCreate, RouteCreate, RouteRead
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/routes", tags=["routes"])
DatabaseSession = Annotated[Session, Depends(get_session)]
Viewer = Annotated[UserRead, Depends(get_current_user)]
Observer = Annotated[UserRead, Depends(require_roles(UserRole.OBSERVER))]
RouteId = Annotated[int, Path(ge=1, le=2_147_483_647)]


@router.post("", response_model=RouteRead, status_code=201)
def create_route(data: RouteCreate, session: DatabaseSession, _viewer: Observer):
    try:
        return service.save_routes(session, [data])[0]
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/batch", response_model=list[RouteRead], status_code=201)
def create_routes(data: RouteBatchCreate, session: DatabaseSession, _viewer: Observer):
    try:
        return service.save_routes(session, data.routes)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("", response_model=list[RouteRead])
def list_routes(
    session: DatabaseSession,
    viewer: Viewer,
    worker_id: Annotated[int | None, Query(ge=1, le=2_147_483_647)] = None,
    route_date: date | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=2_147_483_647)] = 0,
):
    return service.list_routes(session, viewer, worker_id, route_date, limit, offset)


@router.get("/{route_id}", response_model=RouteRead)
def get_route(route_id: RouteId, session: DatabaseSession, viewer: Viewer):
    route = service.get_route(session, viewer, route_id)
    if route is None:
        raise HTTPException(404, "Маршрут не найден")
    return route


@router.get("/{route_id}/geojson")
def get_geojson(route_id: RouteId, session: DatabaseSession, viewer: Viewer):
    route = get_route(route_id, session, viewer)
    return Response(
        content=route.geojson.model_dump_json(),
        media_type="application/geo+json",
        headers={"Content-Disposition": f'attachment; filename="route-{route.id}.geojson"'},
    )

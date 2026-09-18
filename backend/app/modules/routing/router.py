"""Observer-only route calculation and authorized route persistence."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_session
from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.routing import service
from app.modules.routing.client import GeoapifyRoutingClient, GeoapifyRoutingError
from app.modules.routing.schemas import (
    RouteBatchCreate,
    RouteCreate,
    RouteRead,
    RouteRequest,
    RouteResult,
)
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/routes", tags=["routing"])

DatabaseSession = Annotated[Session, Depends(get_session)]
Viewer = Annotated[UserRead, Depends(get_current_user)]
Observer = Annotated[UserRead, Depends(require_roles(UserRole.OBSERVER))]
RouteId = Annotated[int, Path(ge=1, le=2_147_483_647)]


def get_geoapify_routing_client() -> GeoapifyRoutingClient:
    """Build the provider boundary only after the server has its secret configuration."""

    settings = get_settings()
    if not settings.geoapify_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Сервис построения маршрутов не настроен",
        )
    return GeoapifyRoutingClient(
        api_key=settings.geoapify_api_key,
        timeout_seconds=settings.geoapify_timeout_seconds,
    )


def resolve_routing_client(request: Request) -> GeoapifyRoutingClient:
    override = request.app.dependency_overrides.get(get_geoapify_routing_client)
    if override is not None:
        return override()
    return get_geoapify_routing_client()


def _raise_route_error(error: GeoapifyRoutingError) -> None:
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Сервис построения маршрутов временно недоступен",
    ) from error


@router.post("", response_model=RouteResult | RouteRead)
def handle_route(
    data: dict[str, Any],
    request: Request,
    response: Response,
    session: DatabaseSession,
    _viewer: Observer,
):
    """Построить маршрут через Geoapify или сохранить снимок маршрута в БД."""

    if "origin" in data or "destination" in data or "mode" in data:
        try:
            route_req = RouteRequest.model_validate(data)
        except ValidationError as err:
            raise RequestValidationError(err.errors()) from err

        client = resolve_routing_client(request)
        try:
            result = client.build_route(
                origin=route_req.origin,
                destination=route_req.destination,
                mode=route_req.mode,
            )
            response.status_code = status.HTTP_200_OK
            return result
        except GeoapifyRoutingError as error:
            _raise_route_error(error)

    try:
        route_create = RouteCreate.model_validate(data)
    except (ValidationError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error

    try:
        saved = service.save_routes(session, [route_create])[0]
        response.status_code = status.HTTP_201_CREATED
        return saved
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error


@router.post("/calculate", response_model=RouteResult)
def calculate_route(
    data: RouteRequest,
    request: Request,
    _current_user: Observer,
) -> RouteResult:
    """Рассчитать маршрут между координатами в выбранном режиме."""

    client = resolve_routing_client(request)
    try:
        return client.build_route(
            origin=data.origin,
            destination=data.destination,
            mode=data.mode,
        )
    except GeoapifyRoutingError as error:
        _raise_route_error(error)


@router.post("/batch", response_model=list[RouteRead], status_code=201)
def create_routes(data: RouteBatchCreate, session: DatabaseSession, _viewer: Observer):
    """Пакетное сохранение снимков маршрутов."""

    try:
        return service.save_routes(session, data.routes)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error


@router.get("", response_model=list[RouteRead])
def list_routes(
    session: DatabaseSession,
    viewer: Viewer,
    worker_id: Annotated[int | None, Query(ge=1, le=2_147_483_647)] = None,
    route_date: date | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=2_147_483_647)] = 0,
):
    """Список сохранённых маршрутов с фильтрацией."""

    return service.list_routes(session, viewer, worker_id, route_date, limit, offset)


@router.get("/{route_id}", response_model=RouteRead)
def get_route(route_id: RouteId, session: DatabaseSession, viewer: Viewer):
    """Получить сохранённый маршрут по ID."""

    route = service.get_route(session, viewer, route_id)
    if route is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Маршрут не найден")
    return route


@router.get("/{route_id}/geojson")
def get_geojson(route_id: RouteId, session: DatabaseSession, viewer: Viewer):
    """Скачать снимок маршрута в формате GeoJSON."""

    route = get_route(route_id, session, viewer)
    return Response(
        content=route.geojson.model_dump_json(),
        media_type="application/geo+json",
        headers={"Content-Disposition": f'attachment; filename="route-{route.id}.geojson"'},
    )

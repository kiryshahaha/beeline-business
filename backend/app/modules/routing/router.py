"""Observer-only HTTP API for a single route calculation."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import get_settings
from app.modules.auth.dependencies import require_roles
from app.modules.routing.client import GeoapifyRoutingClient, GeoapifyRoutingError
from app.modules.routing.schemas import RouteRequest, RouteResult
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/routes", tags=["routing"])
CurrentObserver = Annotated[UserRead, Depends(require_roles(UserRole.OBSERVER))]


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


RoutingClient = Annotated[GeoapifyRoutingClient, Depends(get_geoapify_routing_client)]


def _raise_route_error(error: GeoapifyRoutingError) -> None:
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Сервис построения маршрутов временно недоступен",
    ) from error


@router.post("", response_model=RouteResult)
def build_route(
    data: RouteRequest,
    _current_user: CurrentObserver,
    client: RoutingClient,
) -> RouteResult:
    """Построить автомобильный маршрут для наблюдателя."""

    try:
        return client.build_route(
            origin=data.origin,
            destination=data.destination,
            mode=data.mode,
        )
    except GeoapifyRoutingError as error:
        _raise_route_error(error)

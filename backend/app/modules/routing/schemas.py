"""Provider-neutral contracts for route calculation."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RouteMode = Literal[
    "drive",
    "transit",
    "approximated_transit",
    "walk",
    "bicycle",
    "scooter",
    "motorcycle",
]
SUPPORTED_ROUTE_MODES: tuple[RouteMode, ...] = (
    "drive",
    "transit",
    "approximated_transit",
    "walk",
    "bicycle",
    "scooter",
    "motorcycle",
)


class GeoPoint(BaseModel):
    """A geographic point in the domain's latitude/longitude order."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class RouteResult(BaseModel):
    """The stable response exposed by the routing boundary."""

    distance_meters: float
    duration_seconds: float
    geometry: dict[str, Any]


class RouteRequest(BaseModel):
    """An observer's request for one route in the selected travel mode."""

    model_config = ConfigDict(extra="forbid")

    origin: GeoPoint
    destination: GeoPoint
    mode: RouteMode = "drive"


class RouteMatrixCell(BaseModel):
    """Time and distance for one source-to-target pair."""

    distance_meters: float | None
    duration_seconds: float | None


class RouteMatrixResult(BaseModel):
    """A matrix whose rows retain the source and target request ordering."""

    cells: list[list[RouteMatrixCell]]

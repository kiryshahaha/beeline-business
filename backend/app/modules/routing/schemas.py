"""Provider-neutral contracts for route calculation and persisted route snapshots."""

from datetime import date, timedelta, timezone
from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.modules.users.schemas import PositiveInt32

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


# Persisted routes (WGS84 lon, lat GeoJSON)

MOSCOW = timezone(timedelta(hours=3))
Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False, strict=True)]
Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False, strict=True)]
Position = tuple[Longitude, Latitude]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RouteStop(StrictModel):
    location_id: PositiveInt32
    ticket_id: PositiveInt32 | None = None
    arrival_at: AwareDatetime


class LineString(StrictModel):
    type: Literal["LineString"] = "LineString"
    coordinates: list[Position] = Field(min_length=2, max_length=20000)


class RouteCreate(StrictModel):
    worker_id: PositiveInt32
    route_date: date
    stops: list[RouteStop] = Field(min_length=1, max_length=1000)
    geometry: LineString | None = None

    @model_validator(mode="after")
    def validate_schedule(self) -> Self:
        if self.stops[0].arrival_at.astimezone(MOSCOW).date() != self.route_date:
            raise ValueError("Первая точка должна относиться к дате маршрута (Europe/Moscow)")
        if any(b.arrival_at < a.arrival_at for a, b in zip(self.stops, self.stops[1:])):
            raise ValueError("Время прибытия должно идти в порядке посещения")
        if self.stops[-1].arrival_at - self.stops[0].arrival_at > timedelta(days=1):
            raise ValueError("Маршрут не может длиться более 24 часов")
        tickets = [stop.ticket_id for stop in self.stops if stop.ticket_id is not None]
        if len(tickets) != len(set(tickets)):
            raise ValueError("Заявка не может повторяться в одном маршруте")
        return self


class StopProperties(RouteStop):
    sequence: PositiveInt32


class Point(StrictModel):
    type: Literal["Point"] = "Point"
    coordinates: Position


class StopFeature(StrictModel):
    type: Literal["Feature"] = "Feature"
    geometry: Point
    properties: StopProperties


class PathProperties(StrictModel):
    kind: Literal["path"] = "path"
    source: Literal["provided", "straight_lines"]


class PathFeature(StrictModel):
    type: Literal["Feature"] = "Feature"
    geometry: LineString
    properties: PathProperties


class RouteProperties(StrictModel):
    worker_id: PositiveInt32
    route_date: date
    route_number: PositiveInt32


class RouteGeoJSON(StrictModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    properties: RouteProperties
    features: list[StopFeature | PathFeature] = Field(min_length=1, max_length=1001)

    @model_validator(mode="after")
    def validate_features(self) -> Self:
        stops = [f for f in self.features if isinstance(f, StopFeature)]
        paths = [f for f in self.features if isinstance(f, PathFeature)]
        if not stops or len(paths) > 1:
            raise ValueError("Нужны точки посещения и не более одной линии")
        if [f.properties.sequence for f in stops] != list(range(1, len(stops) + 1)):
            raise ValueError("Порядок точек должен быть непрерывным, начиная с 1")
        RouteCreate(
            worker_id=self.properties.worker_id,
            route_date=self.properties.route_date,
            stops=[RouteStop(**f.properties.model_dump(exclude={"sequence"})) for f in stops],
        )
        if paths:
            line = paths[0].geometry.coordinates
            if (
                line[0] != stops[0].geometry.coordinates
                or line[-1] != stops[-1].geometry.coordinates
            ):
                raise ValueError("Концы линии должны совпадать с первой и последней точками")
        return self


class RouteRead(StrictModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    id: PositiveInt32
    worker_id: PositiveInt32
    route_date: date
    route_number: PositiveInt32
    geojson: RouteGeoJSON
    created_at: AwareDatetime


class RouteBatchCreate(StrictModel):
    routes: list[RouteCreate] = Field(min_length=1, max_length=100)

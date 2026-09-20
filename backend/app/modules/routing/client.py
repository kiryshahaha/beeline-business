"""HTTP boundary for Geoapify Routing API."""

import math
from typing import Any

import httpx

from app.core.http_limits import bounded_request
from app.modules.routing.schemas import GeoPoint, RouteMatrixCell, RouteMatrixResult, RouteResult

ROUTING_URL = "https://api.geoapify.com/v1/routing"
ROUTE_MATRIX_URL = "https://api.geoapify.com/v1/routematrix"
MAX_ROUTE_MATRIX_CELLS = 1_000


class GeoapifyRoutingError(RuntimeError):
    """Base error for failures that should not expose provider details."""


class GeoapifyUpstreamError(GeoapifyRoutingError):
    """Geoapify returned a non-success HTTP response."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Geoapify returned HTTP {status_code}")


class GeoapifyMalformedResponseError(GeoapifyRoutingError):
    """Geoapify returned a success status without a usable route."""


class GeoapifyRequestError(GeoapifyRoutingError):
    """A network failure prevented route calculation."""


class GeoapifyMatrixSizeError(GeoapifyRoutingError):
    """The requested synchronous matrix exceeds Geoapify's cell limit."""


class GeoapifyMatrixInputError(GeoapifyRoutingError):
    """The requested matrix lacks at least one source or one target."""


class GeoapifyRoutingClient:
    """Build provider-neutral routes while keeping the API key server-side."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def build_route(
        self,
        *,
        origin: GeoPoint,
        destination: GeoPoint,
        mode: str = "drive",
    ) -> RouteResult:
        params = {
            "apiKey": self._api_key,
            "waypoints": self._waypoints(origin, destination),
            "mode": mode,
            "format": "geojson",
            "units": "metric",
        }
        try:
            with httpx.Client(timeout=self._timeout_seconds, transport=self._transport) as client:
                response = client.get(ROUTING_URL, params=params)
        except httpx.RequestError as error:
            raise GeoapifyRequestError("Could not reach Geoapify") from error

        if response.is_error:
            raise GeoapifyUpstreamError(response.status_code)

        return self._parse_route(response)

    def build_route_matrix(
        self,
        *,
        sources: list[GeoPoint],
        targets: list[GeoPoint],
        mode: str = "drive",
    ) -> RouteMatrixResult:
        if not sources or not targets:
            raise GeoapifyMatrixInputError("Geoapify matrix needs at least one source and target")
        if len(sources) * len(targets) > MAX_ROUTE_MATRIX_CELLS:
            raise GeoapifyMatrixSizeError("Geoapify supports at most 1000 matrix cells")

        payload = {
            "mode": mode,
            "units": "metric",
            "sources": [{"location": [point.longitude, point.latitude]} for point in sources],
            "targets": [{"location": [point.longitude, point.latitude]} for point in targets],
        }
        try:
            with httpx.Client(timeout=self._timeout_seconds, transport=self._transport) as client:
                response = client.post(
                    ROUTE_MATRIX_URL,
                    params={"apiKey": self._api_key},
                    json=payload,
                )
        except httpx.RequestError as error:
            raise GeoapifyRequestError("Could not reach Geoapify") from error

        if response.is_error:
            raise GeoapifyUpstreamError(response.status_code)

        return self._parse_matrix(
            response,
            source_count=len(sources),
            target_count=len(targets),
        )

    @staticmethod
    def _waypoints(origin: GeoPoint, destination: GeoPoint) -> str:
        origin_waypoint = f"{origin.latitude},{origin.longitude}"
        destination_waypoint = f"{destination.latitude},{destination.longitude}"
        return f"{origin_waypoint}|{destination_waypoint}"

    @staticmethod
    def _parse_route(response: httpx.Response) -> RouteResult:
        try:
            payload: Any = response.json()
            feature = payload["features"][0]
            properties = feature["properties"]
            distance = properties["distance"]
            duration = properties["time"]
            geometry = feature["geometry"]
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise GeoapifyMalformedResponseError("Geoapify route response is malformed") from error

        if (
            isinstance(distance, bool)
            or not isinstance(distance, (int, float))
            or isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not GeoapifyRoutingClient._is_route_geometry(geometry)
        ):
            raise GeoapifyMalformedResponseError("Geoapify route response is malformed")

        return RouteResult(
            distance_meters=float(distance),
            duration_seconds=float(duration),
            geometry=geometry,
        )

    @staticmethod
    def _is_route_geometry(geometry: Any) -> bool:
        if not isinstance(geometry, dict) or geometry.get("type") != "MultiLineString":
            return False
        coordinates = geometry.get("coordinates")
        return (
            isinstance(coordinates, list)
            and bool(coordinates)
            and all(isinstance(line, list) and len(line) >= 2 for line in coordinates)
        )

    @staticmethod
    def _parse_matrix(
        response: httpx.Response,
        *,
        source_count: int,
        target_count: int,
    ) -> RouteMatrixResult:
        try:
            rows: Any = response.json()["sources_to_targets"]
        except (KeyError, TypeError, ValueError) as error:
            raise GeoapifyMalformedResponseError("Geoapify matrix response is malformed") from error

        if not isinstance(rows, list) or len(rows) != source_count:
            raise GeoapifyMalformedResponseError("Geoapify matrix response is malformed")

        cells: list[list[RouteMatrixCell]] = []
        for i, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != target_count:
                raise GeoapifyMalformedResponseError("Geoapify matrix response is malformed")
            for j, cell in enumerate(row):
                if isinstance(cell, dict) and (
                    cell.get("source_index", i) != i or cell.get("target_index", j) != j
                ):
                    raise GeoapifyMalformedResponseError("Matrix index does not match its position")
            cells.append([GeoapifyRoutingClient._parse_matrix_cell(cell) for cell in row])
        return RouteMatrixResult(cells=cells)

    @staticmethod
    def _parse_matrix_cell(cell: Any) -> RouteMatrixCell:
        if not isinstance(cell, dict):
            raise GeoapifyMalformedResponseError("Geoapify matrix response is malformed")

        distance = cell.get("distance")
        duration = cell.get("time")
        if (distance is None) != (duration is None):
            raise GeoapifyMalformedResponseError("Incomplete unreachable matrix cell")
        if not (
            GeoapifyRoutingClient._is_optional_number(distance)
            and GeoapifyRoutingClient._is_optional_number(duration)
        ):
            raise GeoapifyMalformedResponseError("Geoapify matrix response is malformed")
        return RouteMatrixCell(
            distance_meters=float(distance) if distance is not None else None,
            duration_seconds=float(duration) if duration is not None else None,
        )

    @staticmethod
    def _is_optional_number(value: Any) -> bool:
        return value is None or (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
        )


class AsyncGeoapifyRoutingClient:
    """Pooled async variant using the same provider parsing as the existing routing API."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 10,
        transport=None,
        base_url: str = "https://api.geoapify.com/v1",
    ):
        self._key = api_key
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs):
        from app.modules.planning.errors import PlanningError

        try:
            response = await bounded_request(self._client, method, path, **kwargs)
        except ValueError as error:
            raise PlanningError("routing_invalid_response", 502) from error
        except httpx.TimeoutException as error:
            raise PlanningError("routing_timeout", 504) from error
        except httpx.RequestError as error:
            raise PlanningError("routing_unavailable", 502) from error
        if response.status_code != 200:
            raise PlanningError("routing_unavailable", 502)
        return response

    async def build_route_matrix(self, *, sources, targets, mode):
        if not sources or not targets or len(sources) * len(targets) > MAX_ROUTE_MATRIX_CELLS:
            raise GeoapifyMatrixSizeError("Invalid matrix dimensions")
        response = await self._request(
            "POST",
            "routematrix",
            params={"apiKey": self._key},
            json={
                "mode": mode,
                "units": "metric",
                "type": "balanced",
                "traffic": "free_flow",
                "sources": [{"location": list(p)} for p in sources],
                "targets": [{"location": list(p)} for p in targets],
            },
        )
        return GeoapifyRoutingClient._parse_matrix(
            response, source_count=len(sources), target_count=len(targets)
        )

    async def build_route(self, *, origin, destination, mode):
        response = await self._request(
            "GET",
            "routing",
            params={
                "apiKey": self._key,
                "waypoints": f"{origin[1]},{origin[0]}|{destination[1]},{destination[0]}",
                "mode": mode,
                "format": "geojson",
                "units": "metric",
                "type": "balanced",
                "traffic": "free_flow",
            },
        )
        return GeoapifyRoutingClient._parse_route(response)

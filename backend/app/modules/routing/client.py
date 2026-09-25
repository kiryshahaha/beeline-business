"""HTTP boundary for Geoapify Routing API."""

import asyncio
import hashlib
import json
import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.core.http_limits import bounded_request
from app.modules.routing.cache import GeoapifyResultCache
from app.modules.routing.schemas import GeoPoint, RouteMatrixCell, RouteMatrixResult, RouteResult
from app.modules.routing.telemetry import RoutingTelemetry

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

        return self._parse_route(response, expected_mode=mode)

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
    def _parse_route(response: httpx.Response, *, expected_mode: str | None = None) -> RouteResult:
        try:
            payload: Any = response.json()
            feature = payload["features"][0]
            properties = feature["properties"]
            distance = properties["distance"]
            duration = properties["time"]
            geometry = feature["geometry"]
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise GeoapifyMalformedResponseError("Geoapify route response is malformed") from error

        reported_modes = (
            payload.get("properties", {}).get("mode")
            if isinstance(payload.get("properties"), dict)
            else None,
            properties.get("mode"),
        )
        if expected_mode and any(
            reported is not None and reported != expected_mode for reported in reported_modes
        ):
            raise GeoapifyMalformedResponseError("Geoapify route profile does not match request")

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
        max_retries: int = 2,
        cache: GeoapifyResultCache | None = None,
        cache_ttl_seconds: float = 300,
        coordinate_precision: int = 6,
        telemetry: RoutingTelemetry | None = None,
        transport=None,
        base_url: str = "https://api.geoapify.com/v1",
    ):
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if not 0 <= coordinate_precision <= 12:
            raise ValueError("coordinate_precision must be between 0 and 12")
        self._key = api_key
        self._max_retries = max_retries
        self._cache = cache
        self._cache_ttl_seconds = cache_ttl_seconds
        self._coordinate_precision = coordinate_precision
        self._provider_scope = hashlib.sha256(api_key.encode()).hexdigest()
        self._base_url = base_url.rstrip("/")
        self.telemetry = telemetry or RoutingTelemetry()
        self._client = httpx.AsyncClient(
            base_url=self._base_url + "/",
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

        stage = kwargs.pop("stage")
        for attempt in range(self._max_retries + 1):
            self.telemetry.record_provider_request(stage)
            try:
                response = await bounded_request(self._client, method, path, **kwargs)
            except ValueError as error:
                self.telemetry.record_error("routing_invalid_response")
                raise PlanningError("routing_invalid_response", 502) from error
            except httpx.TimeoutException as error:
                self.telemetry.record_error("routing_timeout")
                raise PlanningError("routing_timeout", 504) from error
            except httpx.RequestError as error:
                self.telemetry.record_error("routing_unavailable")
                raise PlanningError("routing_unavailable", 502) from error

            if response.status_code == 200:
                return response
            retryable = response.status_code == 429 or 500 <= response.status_code <= 599
            if not retryable or attempt == self._max_retries:
                error = self._upstream_error(response.status_code)
                self.telemetry.record_error(error.code)
                raise error
            self.telemetry.record_retry()
            await asyncio.sleep(self._retry_delay(response.headers.get("Retry-After"), attempt))

        raise PlanningError("routing_unavailable", 502)

    @staticmethod
    def _retry_delay(retry_after: str | None, attempt: int) -> float:
        if retry_after is not None:
            try:
                seconds = float(retry_after)
                if math.isfinite(seconds):
                    return max(0.0, seconds)
            except ValueError:
                pass
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
        return min(0.25 * (2**attempt), 2.0)

    @staticmethod
    def _upstream_error(status_code: int):
        from app.modules.planning.errors import PlanningError

        if status_code in (401, 403):
            return PlanningError("routing_authentication_failed", 502)
        if status_code in (400, 404, 422):
            return PlanningError("routing_invalid_request", 502)
        if status_code == 429:
            return PlanningError("routing_rate_limited", 503)
        return PlanningError("routing_unavailable", 502)

    async def build_route_matrix(self, *, sources, targets, mode):
        self.telemetry.record_operation(
            "matrix", mode, cells=len(sources) * len(targets), source="geoapify_matrix"
        )
        if not sources or not targets or len(sources) * len(targets) > MAX_ROUTE_MATRIX_CELLS:
            raise GeoapifyMatrixSizeError("Invalid matrix dimensions")
        params = {
            "mode": mode,
            "units": "metric",
            "type": "balanced",
            "traffic": "free_flow",
        }
        key = self._cache_key(
            "matrix",
            mode,
            coordinates={
                "sources": [list(point) for point in sources],
                "targets": [list(point) for point in targets],
            },
            params=params,
        )
        if self._cache is not None:
            cached = self._cache.get(key)
            if cached is not None:
                self.telemetry.record_cache_hit("matrix")
                return RouteMatrixResult.model_validate(json.loads(cached.payload))
        response = await self._request(
            "POST",
            "routematrix",
            stage="matrix",
            params={"apiKey": self._key},
            json={
                **params,
                "sources": [{"location": list(p)} for p in sources],
                "targets": [{"location": list(p)} for p in targets],
            },
        )
        try:
            result = GeoapifyRoutingClient._parse_matrix(
                response, source_count=len(sources), target_count=len(targets)
            )
        except GeoapifyRoutingError:
            self.telemetry.record_error("routing_invalid_response")
            raise
        self._cache_result(key, result, "geoapify_matrix")
        return result

    async def build_route(self, *, origin, destination, mode):
        self.telemetry.record_operation("route", mode, cells=0, source="geoapify_route")
        params = {
            "waypoints": f"{origin[1]},{origin[0]}|{destination[1]},{destination[0]}",
            "mode": mode,
            "format": "geojson",
            "units": "metric",
            "type": "balanced",
            "traffic": "free_flow",
        }
        key = self._cache_key(
            "route",
            mode,
            coordinates={"origin": origin, "destination": destination},
            params={key: value for key, value in params.items() if key != "waypoints"},
        )
        if self._cache is not None:
            cached = self._cache.get(key)
            if cached is not None:
                self.telemetry.record_cache_hit("route")
                return RouteResult.model_validate(json.loads(cached.payload))
        response = await self._request(
            "GET",
            "routing",
            stage="route",
            params={"apiKey": self._key, **params},
        )
        try:
            result = GeoapifyRoutingClient._parse_route(response, expected_mode=mode)
        except GeoapifyRoutingError:
            self.telemetry.record_error("routing_invalid_response")
            raise
        self._cache_result(key, result, "geoapify_route")
        return result

    def _cache_key(self, operation, profile, *, coordinates, params) -> str:
        def normalize(value):
            if isinstance(value, dict):
                return {key: normalize(item) for key, item in sorted(value.items())}
            if isinstance(value, (list, tuple)):
                return [normalize(item) for item in value]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return round(float(value), self._coordinate_precision)
            return value

        material = {
            "provider": self._base_url,
            "provider_scope": self._provider_scope,
            "operation": operation,
            "profile": profile,
            "coordinate_precision": self._coordinate_precision,
            "coordinates": normalize(coordinates),
            "params": normalize(params),
        }
        serialized = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()

    def _cache_result(self, key, result, source) -> None:
        if self._cache is None:
            return
        payload = json.dumps(result.model_dump(mode="json"), separators=(",", ":")).encode()
        self._cache.put(key, payload, source, self._cache_ttl_seconds)

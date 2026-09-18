"""Boundary tests for Geoapify route calculation."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.routing.client import (
    GeoapifyMalformedResponseError,
    GeoapifyMatrixInputError,
    GeoapifyMatrixSizeError,
    GeoapifyRoutingClient,
)
from app.modules.routing.router import get_geoapify_routing_client
from app.modules.routing.schemas import SUPPORTED_ROUTE_MODES, GeoPoint, RouteResult
from app.modules.users.enums import UserRole


class GeoapifyRoutingClientTests(unittest.TestCase):
    def test_build_route_uses_documented_waypoint_order_and_normalizes_geojson(self):
        """Catch swapped latitude/longitude or leaking provider-specific response fields."""

        captured_requests: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {
                                "mode": "drive",
                                "units": "metric",
                                "distance": 11_057,
                                "time": 968,
                                "legs": [],
                            },
                            "geometry": {
                                "type": "MultiLineString",
                                "coordinates": [[[37.6173, 55.7558], [37.5312, 55.7903]]],
                            },
                        }
                    ],
                },
            )

        client = GeoapifyRoutingClient(
            api_key="test-api-key",
            transport=httpx.MockTransport(respond),
        )

        route = client.build_route(
            origin=GeoPoint(latitude=55.7558, longitude=37.6173),
            destination=GeoPoint(latitude=55.7903, longitude=37.5312),
        )

        self.assertEqual(route.distance_meters, 11_057)
        self.assertEqual(route.duration_seconds, 968)
        self.assertEqual(
            route.geometry,
            {
                "type": "MultiLineString",
                "coordinates": [[[37.6173, 55.7558], [37.5312, 55.7903]]],
            },
        )

        self.assertEqual(len(captured_requests), 1)
        request = captured_requests[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.url.host, "api.geoapify.com")
        self.assertEqual(request.url.path, "/v1/routing")
        params = parse_qs(request.url.query.decode())
        self.assertEqual(params["waypoints"], ["55.7558,37.6173|55.7903,37.5312"])
        self.assertEqual(params["mode"], ["drive"])
        self.assertEqual(params["format"], ["geojson"])
        self.assertEqual(params["units"], ["metric"])
        self.assertEqual(params["apiKey"], ["test-api-key"])

    def test_build_route_matrix_uses_geojson_coordinate_order_and_keeps_unroutable_cells(self):
        """Catch swapped matrix coordinates or turning an unreachable pair into zero."""

        captured_requests: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return httpx.Response(
                200,
                json={
                    "sources": [
                        {
                            "original_location": [37.6173, 55.7558],
                            "location": [37.6174, 55.7559],
                        }
                    ],
                    "targets": [
                        {
                            "original_location": [37.5312, 55.7903],
                            "location": [37.5313, 55.7904],
                        },
                        {
                            "original_location": [37.6300, 55.8000],
                            "location": [37.6301, 55.8001],
                        },
                    ],
                    "sources_to_targets": [
                        [
                            {
                                "distance": 11_057,
                                "time": 968,
                                "source_index": 0,
                                "target_index": 0,
                            },
                            {
                                "distance": None,
                                "time": None,
                                "source_index": 0,
                                "target_index": 1,
                            },
                        ]
                    ],
                },
            )

        client = GeoapifyRoutingClient(
            api_key="test-api-key",
            transport=httpx.MockTransport(respond),
        )

        matrix = client.build_route_matrix(
            sources=[GeoPoint(latitude=55.7558, longitude=37.6173)],
            targets=[
                GeoPoint(latitude=55.7903, longitude=37.5312),
                GeoPoint(latitude=55.8000, longitude=37.6300),
            ],
        )

        self.assertEqual(matrix.cells[0][0].distance_meters, 11_057)
        self.assertEqual(matrix.cells[0][0].duration_seconds, 968)
        self.assertIsNone(matrix.cells[0][1].distance_meters)
        self.assertIsNone(matrix.cells[0][1].duration_seconds)

        self.assertEqual(len(captured_requests), 1)
        request = captured_requests[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.url.path, "/v1/routematrix")
        self.assertEqual(parse_qs(request.url.query.decode())["apiKey"], ["test-api-key"])
        self.assertEqual(
            json.loads(request.content),
            {
                "mode": "drive",
                "units": "metric",
                "sources": [{"location": [37.6173, 55.7558]}],
                "targets": [
                    {"location": [37.5312, 55.7903]},
                    {"location": [37.63, 55.8]},
                ],
            },
        )

    def test_build_route_matrix_rejects_more_than_one_thousand_cells_before_network_call(self):
        """Catch spending Geoapify credits on a request over the documented synchronous limit."""

        request_count = 0

        def respond(_request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return httpx.Response(500)

        client = GeoapifyRoutingClient(
            api_key="test-api-key",
            transport=httpx.MockTransport(respond),
        )
        sources = [GeoPoint(latitude=55.7558, longitude=37.6173) for _ in range(1_001)]
        target = GeoPoint(latitude=55.7903, longitude=37.5312)

        with self.assertRaises(GeoapifyMatrixSizeError):
            client.build_route_matrix(sources=sources, targets=[target])

        self.assertEqual(request_count, 0)

    def test_build_route_matrix_requires_at_least_one_source_and_target(self):
        """Catch a matrix shape that cannot produce a useful planning input."""

        client = GeoapifyRoutingClient(api_key="test-api-key")
        point = GeoPoint(latitude=55.7558, longitude=37.6173)

        with self.assertRaises(GeoapifyMatrixInputError):
            client.build_route_matrix(sources=[], targets=[point])
        with self.assertRaises(GeoapifyMatrixInputError):
            client.build_route_matrix(sources=[point], targets=[])

    def test_build_route_rejects_feature_without_multilinestring_geometry(self):
        """Catch treating an arbitrary GeoJSON feature as a route geometry."""

        def respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"distance": 11_057, "time": 968},
                            "geometry": {"type": "Point", "coordinates": [37.6173, 55.7558]},
                        }
                    ],
                },
            )

        client = GeoapifyRoutingClient(
            api_key="test-api-key",
            transport=httpx.MockTransport(respond),
        )

        with self.assertRaises(GeoapifyMalformedResponseError):
            client.build_route(
                origin=GeoPoint(latitude=55.7558, longitude=37.6173),
                destination=GeoPoint(latitude=55.7903, longitude=37.5312),
            )

    def test_build_route_matrix_rejects_response_with_wrong_shape(self):
        """Catch passing a truncated time matrix to the planner as if every pair had a value."""

        def respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "sources_to_targets": [
                        [
                            {
                                "distance": 11_057,
                                "time": 968,
                                "source_index": 0,
                                "target_index": 0,
                            }
                        ]
                    ]
                },
            )

        client = GeoapifyRoutingClient(
            api_key="test-api-key",
            transport=httpx.MockTransport(respond),
        )
        source = GeoPoint(latitude=55.7558, longitude=37.6173)
        targets = [
            GeoPoint(latitude=55.7903, longitude=37.5312),
            GeoPoint(latitude=55.8000, longitude=37.6300),
        ]

        with self.assertRaises(GeoapifyMalformedResponseError):
            client.build_route_matrix(sources=[source], targets=targets)


class RoutesApiTests(unittest.TestCase):
    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_post_builds_a_route_for_observer(self):
        """Catch an unregistered route or a wrapper that bypasses the real Geoapify boundary."""

        def respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {
                                "mode": "drive",
                                "units": "metric",
                                "distance": 11_057,
                                "time": 968,
                                "legs": [],
                            },
                            "geometry": {
                                "type": "MultiLineString",
                                "coordinates": [[[37.6173, 55.7558], [37.5312, 55.7903]]],
                            },
                        }
                    ],
                },
            )

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=UserRole.OBSERVER)
        app.dependency_overrides[get_geoapify_routing_client] = lambda: GeoapifyRoutingClient(
            api_key="test-api-key",
            transport=httpx.MockTransport(respond),
        )

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/routes",
                json={
                    "origin": {"latitude": 55.7558, "longitude": 37.6173},
                    "destination": {"latitude": 55.7903, "longitude": 37.5312},
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {
                "distance_meters": 11_057.0,
                "duration_seconds": 968.0,
                "geometry": {
                    "type": "MultiLineString",
                    "coordinates": [[[37.6173, 55.7558], [37.5312, 55.7903]]],
                },
            },
        )

    def test_post_accepts_each_supported_route_mode(self):
        """Pass every supported travel profile to the Geoapify boundary."""

        requested_modes: list[str] = []

        class StubRoutingClient:
            def build_route(self, *, origin, destination, mode):
                requested_modes.append(mode)
                return RouteResult(
                    distance_meters=1_000,
                    duration_seconds=120,
                    geometry={
                        "type": "MultiLineString",
                        "coordinates": [[[37.6173, 55.7558], [37.5312, 55.7903]]],
                    },
                )

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=UserRole.OBSERVER)
        app.dependency_overrides[get_geoapify_routing_client] = StubRoutingClient

        with TestClient(app) as client:
            for mode in SUPPORTED_ROUTE_MODES:
                response = client.post(
                    "/api/v1/routes",
                    json={
                        "origin": {"latitude": 55.7558, "longitude": 37.6173},
                        "destination": {"latitude": 55.7903, "longitude": 37.5312},
                        "mode": mode,
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)

        self.assertEqual(requested_modes, list(SUPPORTED_ROUTE_MODES))

    def test_post_rejects_unknown_route_mode(self):
        """Reject a mode that Geoapify and the public route contract do not define."""

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=UserRole.OBSERVER)
        app.dependency_overrides[get_geoapify_routing_client] = lambda: object()

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/routes",
                json={
                    "origin": {"latitude": 55.7558, "longitude": 37.6173},
                    "destination": {"latitude": 55.7903, "longitude": 37.5312},
                    "mode": "scoot",
                },
            )

        self.assertEqual(response.status_code, 422, response.text)

    def test_post_rejects_worker_before_route_calculation(self):
        """Catch accidentally exposing a paid arbitrary-coordinate proxy to workers."""

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=UserRole.WORKER)
        app.dependency_overrides[get_geoapify_routing_client] = lambda: object()

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/routes",
                json={
                    "origin": {"latitude": 55.7558, "longitude": 37.6173},
                    "destination": {"latitude": 55.7903, "longitude": 37.5312},
                },
            )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], "Недостаточно прав для выполнения операции")

    def test_post_hides_geoapify_server_failure_from_observer(self):
        """Catch leaking provider payloads or converting their outage into an application crash."""

        def respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "internal provider detail"})

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=UserRole.OBSERVER)
        app.dependency_overrides[get_geoapify_routing_client] = lambda: GeoapifyRoutingClient(
            api_key="test-api-key",
            transport=httpx.MockTransport(respond),
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/api/v1/routes",
                json={
                    "origin": {"latitude": 55.7558, "longitude": 37.6173},
                    "destination": {"latitude": 55.7903, "longitude": 37.5312},
                },
            )

        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(
            response.json(),
            {"detail": "Сервис построения маршрутов временно недоступен"},
        )

    def test_post_reports_missing_geoapify_key_without_exposing_configuration(self):
        """Catch a missing deployment secret becoming a 500 or a sensitive error response."""

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=UserRole.OBSERVER)

        with patch(
            "app.modules.routing.router.get_settings",
            return_value=SimpleNamespace(geoapify_api_key=None),
        ):
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/routes",
                    json={
                        "origin": {"latitude": 55.7558, "longitude": 37.6173},
                        "destination": {"latitude": 55.7903, "longitude": 37.5312},
                    },
                )

        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json(), {"detail": "Сервис построения маршрутов не настроен"})


if __name__ == "__main__":
    unittest.main()

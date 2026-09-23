"""Provider/client failures, matrix chunking, conservative times and hostile bodies."""

import asyncio
import copy
import unittest

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.http_limits import bounded_request
from app.main import app
from app.modules.planning.async_utils import bounded_map
from app.modules.planning.errors import PlanningError
from app.modules.planning.matrices import build_problem
from app.modules.planning.planner_client import PlannerClient
from app.modules.routing.client import AsyncGeoapifyRoutingClient, GeoapifyMalformedResponseError
from app.modules.routing.schemas import RouteGeoJSON
from tests.planning_fakes import FeasiblePlanner, geoapify_response, provider_factory


def prepared(unique=52):
    workers = [
        {"location_id": 0, "profile": "drive", "window": [0, 1000]},
        {"location_id": 1, "profile": "walk", "window": [0, 1000]},
    ]
    return {
        "workers": workers,
        "horizon": 1000,
        "tickets": [
            {"location_id": i, "window": [0, 990], "duration": 10, "allowed": [0, 1]}
            for i in range(2, unique)
        ],
        "locations": {i: {"longitude": 37.0 + i / 10000, "latitude": 55.0} for i in range(unique)},
    }


class PlanningBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def settings(self):
        return Settings(
            database_url="postgresql://unused/isolated_test", planner_service_token="internal"
        )

    async def test_matrix_blocks_cover_all_directed_pairs_for_each_profile(self):
        calls = []

        def handler(request):
            import json

            payload = json.loads(request.content)
            calls.append(payload)
            return geoapify_response(request)

        async with AsyncGeoapifyRoutingClient(
            "test", transport=httpx.MockTransport(handler)
        ) as provider:
            problem, nodes = await build_problem(prepared(), provider, self.settings())
        self.assertEqual(len(nodes), 52)
        self.assertEqual(len(calls), 18)
        self.assertEqual(sum(len(c["sources"]) * len(c["targets"]) for c in calls), 2 * 52 * 52)
        for matrix in problem.matrices.values():
            self.assertTrue(all(value is not None for row in matrix.time_minutes for value in row))
        self.assertEqual(problem.penalties[2], 2001)
        self.assertEqual(problem.vehicle_fixed_cost, 0)

    async def test_duplicate_coordinates_stay_distinct_logical_visits(self):
        data = prepared(5)
        data["locations"][3] = dict(data["locations"][2])
        async with provider_factory() as provider:
            problem, nodes = await build_problem(data, provider, self.settings())
        self.assertEqual(len(nodes), 5)
        self.assertEqual(problem.matrices["drive"].time_minutes[2][3], 0)
        self.assertEqual(problem.service_times[2:4], [10, 10])

    async def test_provider_errors_and_index_corruption(self):
        for payload in (
            {"sources_to_targets": [[{"source_index": 1, "time": 1, "distance": 1}]]},
            {"sources_to_targets": [[{"time": -1, "distance": 1}]]},
        ):
            async with AsyncGeoapifyRoutingClient(
                "secret", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
            ) as provider:
                with self.assertRaises(GeoapifyMalformedResponseError):
                    await provider.build_route_matrix(
                        sources=[(37, 55)], targets=[(38, 55)], mode="drive"
                    )
        async with AsyncGeoapifyRoutingClient(
            "secret",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(429, text="secret-provider-error")
            ),
        ) as provider:
            with self.assertRaises(PlanningError) as result:
                await provider.build_route(origin=(37, 55), destination=(38, 55), mode="drive")
            self.assertEqual(result.exception.code, "routing_unavailable")
            self.assertNotIn("secret", str(result.exception))

    async def test_planner_client_validates_schema_and_error_mapping(self):
        async with provider_factory() as provider:
            problem, _ = await build_problem(prepared(4), provider, self.settings())
        solution = await FeasiblePlanner().solve(problem)
        seen = []

        def success(request):
            seen.append(request)
            return httpx.Response(200, json=solution.model_dump(mode="json"))

        client = PlannerClient(self.settings(), transport=httpx.MockTransport(success))
        self.assertEqual((await client.solve(problem)).total_cost, solution.total_cost)
        self.assertEqual(seen[0].url.path, "/api/v1/solve")
        self.assertEqual(seen[0].headers["X-Planner-Token"], "internal")
        for status, payload, code in (
            (200, {}, "planner_invalid_response"),
            (503, {}, "planner_failure"),
        ):
            client = PlannerClient(
                self.settings(),
                transport=httpx.MockTransport(lambda _: httpx.Response(status, json=payload)),
            )
            with self.assertRaises(PlanningError) as result:
                await client.solve(problem)
            self.assertEqual(result.exception.code, code)

    async def test_upstream_size_limit_and_cancellation(self):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"a" * 1025))
        ) as client:
            with self.assertRaises(ValueError):
                await bounded_request(client, "GET", "http://test", max_bytes=1024)
        completed = []

        async def work(i):
            if i == 0:
                await asyncio.sleep(0)
                raise RuntimeError("stop")
            try:
                await asyncio.sleep(10)
            finally:
                completed.append(i)

        with self.assertRaises(RuntimeError):
            await bounded_map(work, [0, 1, 2], 3)
        self.assertEqual(sorted(completed), [1, 2])

    def test_planning_body_limit(self):
        with TestClient(app) as client:
            response = client.post("/api/v1/planning/preview", content=b"a" * 65537)
        self.assertEqual(response.status_code, 413)

    def test_disconnected_geoapify_lines_are_not_connected_artificially(self):
        geo = {
            "type": "FeatureCollection",
            "properties": {"worker_id": 1, "route_date": "2030-01-15", "route_number": 1},
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [37.0, 55.0]},
                    "properties": {
                        "location_id": 1,
                        "sequence": 1,
                        "arrival_at": "2030-01-15T09:00:00+03:00",
                    },
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [38.0, 55.0]},
                    "properties": {
                        "location_id": 2,
                        "sequence": 2,
                        "arrival_at": "2030-01-15T12:00:00+03:00",
                    },
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "MultiLineString",
                        "coordinates": [[[37.0, 55.0], [37.1, 55.0]], [[37.9, 55.0], [38.0, 55.0]]],
                    },
                    "properties": {
                        "kind": "path",
                        "source": "geoapify",
                        "mode": "drive",
                        "legs": [
                            {
                                "from_sequence": 1,
                                "to_sequence": 2,
                                "geometry_start": 0,
                                "geometry_end": 2,
                                "distance_meters": 10000,
                                "duration_seconds": 600,
                            }
                        ],
                    },
                },
            ],
        }
        result = RouteGeoJSON.model_validate(geo)
        self.assertEqual(len(result.features[-1].geometry.coordinates), 2)
        invalid = copy.deepcopy(geo)
        invalid["features"][-1]["geometry"]["coordinates"][0][0] = [30.0, 55.0]
        with self.assertRaises(ValueError):
            RouteGeoJSON.model_validate(invalid)

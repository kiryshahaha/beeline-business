"""Opt-in smoke check against the configured Geoapify account; never asserts exact ETA."""

import asyncio
import json
import os
import unittest
from urllib.parse import parse_qs

import httpx

from app.modules.routing.client import AsyncGeoapifyRoutingClient
from app.modules.routing.schemas import MultiLineString


@unittest.skipUnless(
    os.getenv("GEOAPIFY_LIVE_SMOKE") == "1" and os.getenv("GEOAPIFY_API_KEY"),
    "set GEOAPIFY_LIVE_SMOKE=1 and GEOAPIFY_API_KEY to run the live smoke check",
)
class GeoapifyLiveSmokeTests(unittest.TestCase):
    def test_drive_matrix_and_geojson_route_use_the_requested_profile(self):
        class ObserveTransport(httpx.AsyncBaseTransport):
            def __init__(self):
                self.delegate = httpx.AsyncHTTPTransport()
                self.modes = []

            async def handle_async_request(self, request):
                if request.url.path.endswith("routematrix"):
                    self.modes.append(json.loads(request.content)["mode"])
                else:
                    self.modes.append(parse_qs(request.url.query.decode())["mode"][0])
                return await self.delegate.handle_async_request(request)

            async def aclose(self):
                await self.delegate.aclose()

        async def smoke():
            transport = ObserveTransport()
            async with AsyncGeoapifyRoutingClient(
                os.environ["GEOAPIFY_API_KEY"], transport=transport
            ) as provider:
                matrix = await provider.build_route_matrix(
                    sources=[(37.6173, 55.7558)],
                    targets=[(37.5312, 55.7903)],
                    mode="drive",
                )
                route = await provider.build_route(
                    origin=(37.6173, 55.7558),
                    destination=(37.5312, 55.7903),
                    mode="drive",
                )
            self.assertEqual(len(matrix.cells), 1)
            self.assertEqual(len(matrix.cells[0]), 1)
            self.assertIsNotNone(matrix.cells[0][0].duration_seconds)
            self.assertIsNotNone(matrix.cells[0][0].distance_meters)
            self.assertGreater(route.duration_seconds, 0)
            self.assertGreater(route.distance_meters, 0)
            geometry = MultiLineString.model_validate(route.geometry)
            self.assertTrue(geometry.coordinates)
            self.assertEqual(transport.modes, ["drive", "drive"])

        asyncio.run(smoke())

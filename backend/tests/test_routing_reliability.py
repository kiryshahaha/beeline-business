"""Deterministic reliability tests for the existing async Geoapify client."""

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx

from app.core.http_limits import bounded_request
from app.modules.planning.errors import PlanningError
from app.modules.routing.cache import GeoapifyResultCache
from app.modules.routing.client import AsyncGeoapifyRoutingClient, GeoapifyMalformedResponseError

ROUTE_RESPONSE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"distance": 1_000, "time": 600},
            "geometry": {
                "type": "MultiLineString",
                "coordinates": [[[37.0, 55.0], [38.0, 55.0]]],
            },
        }
    ],
}


class GeoapifyRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limit_retries_after_the_provider_delay(self):
        calls, delays = [], []

        def handler(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "4"})
            return httpx.Response(200, json=ROUTE_RESPONSE)

        async def skip_sleep(seconds):
            delays.append(seconds)

        with patch("app.modules.routing.client.asyncio.sleep", new=skip_sleep):
            async with AsyncGeoapifyRoutingClient(
                "fixture-key", max_retries=1, transport=httpx.MockTransport(handler)
            ) as provider:
                route = await provider.build_route(
                    origin=(37.0, 55.0), destination=(38.0, 55.0), mode="drive"
                )
                metrics = provider.telemetry.snapshot()

        self.assertEqual(len(calls), 2)
        self.assertEqual(delays, [4.0])
        self.assertEqual(route.duration_seconds, 600)
        self.assertEqual(metrics["retry_attempts"], 1)
        self.assertEqual(metrics["provider_requests"], {"route": 2})

    async def test_server_errors_stop_at_the_finite_retry_limit(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(503, headers={"Retry-After": "0"})

        async with AsyncGeoapifyRoutingClient(
            "fixture-key", max_retries=2, transport=httpx.MockTransport(handler)
        ) as provider:
            with self.assertRaises(PlanningError) as caught:
                await provider.build_route(
                    origin=(37.0, 55.0), destination=(38.0, 55.0), mode="drive"
                )
            metrics = provider.telemetry.snapshot()

        self.assertEqual(len(calls), 3)
        self.assertEqual(caught.exception.code, "routing_unavailable")
        self.assertEqual(metrics["error_reasons"], {"routing_unavailable": 1})

    async def test_auth_and_invalid_request_responses_do_not_retry(self):
        for status, expected_code in (
            (401, "routing_authentication_failed"),
            (403, "routing_authentication_failed"),
            (400, "routing_invalid_request"),
        ):
            with self.subTest(status=status):
                calls = []

                def handler(request):
                    calls.append(request)
                    return httpx.Response(status, headers={"Retry-After": "0"})

                async with AsyncGeoapifyRoutingClient(
                    "fixture-key", max_retries=3, transport=httpx.MockTransport(handler)
                ) as provider:
                    with self.assertRaises(PlanningError) as caught:
                        await provider.build_route(
                            origin=(37.0, 55.0), destination=(38.0, 55.0), mode="drive"
                        )

                self.assertEqual(caught.exception.code, expected_code)
                self.assertEqual(len(calls), 1)

    async def test_cancellation_during_retry_delay_stops_the_provider_call(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(429, headers={"Retry-After": "4"})

        async def cancel_sleep(_seconds):
            raise asyncio.CancelledError

        with patch("app.modules.routing.client.asyncio.sleep", new=cancel_sleep):
            async with AsyncGeoapifyRoutingClient(
                "fixture-key", max_retries=2, transport=httpx.MockTransport(handler)
            ) as provider:
                with self.assertRaises(asyncio.CancelledError):
                    await provider.build_route(
                        origin=(37.0, 55.0), destination=(38.0, 55.0), mode="drive"
                    )

        self.assertEqual(len(calls), 1)

    async def test_bounded_response_keeps_retry_after_header(self):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(429, headers={"Retry-After": "7"})
            )
        ) as client:
            response = await bounded_request(client, "GET", "https://provider.test/route")

        self.assertEqual(response.headers["Retry-After"], "7")

    async def test_reported_profile_mismatch_is_rejected(self):
        payload = {
            **ROUTE_RESPONSE,
            "properties": {"mode": "walk"},
        }
        async with AsyncGeoapifyRoutingClient(
            "fixture-key",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
        ) as provider:
            with self.assertRaises(GeoapifyMalformedResponseError):
                await provider.build_route(
                    origin=(37.0, 55.0), destination=(38.0, 55.0), mode="drive"
                )


class GeoapifyCacheTests(unittest.TestCase):
    def test_cache_records_source_and_expiry_then_drops_expired_value(self):
        monotonic = [10.0]
        now = datetime(2030, 1, 1, tzinfo=UTC)
        cache = GeoapifyResultCache(
            max_entries=2,
            max_bytes=8,
            monotonic=lambda: monotonic[0],
            utc_now=lambda: now,
        )

        self.assertTrue(cache.put("route", b"route", "geoapify_route", 5))
        entry = cache.get("route")
        self.assertEqual(entry.payload, b"route")
        self.assertEqual(entry.source, "geoapify_route")
        self.assertEqual(entry.expires_at, now + timedelta(seconds=5))
        monotonic[0] = 15.0
        self.assertIsNone(cache.get("route"))

    def test_cache_enforces_payload_and_entry_bounds_with_lru_eviction(self):
        cache = GeoapifyResultCache(max_entries=2, max_bytes=5)
        self.assertTrue(cache.put("first", b"a", "matrix", 30))
        self.assertTrue(cache.put("second", b"b", "matrix", 30))
        self.assertEqual(cache.get("first").payload, b"a")
        self.assertTrue(cache.put("third", b"c", "route", 30))
        self.assertIsNone(cache.get("second"))
        self.assertEqual(cache.get("first").payload, b"a")
        self.assertFalse(cache.put("oversized", b"123456", "route", 30))
        self.assertEqual(cache.get("third").payload, b"c")


class GeoapifyClientCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_identity_includes_provider_precision_and_route_options(self):
        coordinates = {"origin": (37.0, 55.0), "destination": (38.0, 55.0)}
        async with (
            AsyncGeoapifyRoutingClient("fixture-key", base_url="https://first.test/v1") as first,
            AsyncGeoapifyRoutingClient("fixture-key", base_url="https://second.test/v1") as second,
            AsyncGeoapifyRoutingClient(
                "fixture-key", base_url="https://first.test/v1", coordinate_precision=5
            ) as lower_precision,
        ):
            key = first._cache_key(
                "route", "drive", coordinates=coordinates, params={"traffic": "free_flow"}
            )
            other_provider = second._cache_key(
                "route", "drive", coordinates=coordinates, params={"traffic": "free_flow"}
            )
            other_precision = lower_precision._cache_key(
                "route", "drive", coordinates=coordinates, params={"traffic": "free_flow"}
            )
            other_option = first._cache_key(
                "route", "drive", coordinates=coordinates, params={"traffic": "approximated"}
            )

        self.assertEqual(len({key, other_provider, other_precision, other_option}), 4)

    async def test_route_cache_separates_profiles_and_reuses_rounded_coordinates(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=ROUTE_RESPONSE)

        cache = GeoapifyResultCache(max_entries=8, max_bytes=4096)
        async with AsyncGeoapifyRoutingClient(
            "fixture-key",
            cache=cache,
            cache_ttl_seconds=60,
            coordinate_precision=6,
            transport=httpx.MockTransport(handler),
        ) as provider:
            first = await provider.build_route(
                origin=(37.0, 55.0), destination=(38.0000001, 55.0), mode="drive"
            )
            cached = await provider.build_route(
                origin=(37.0, 55.0), destination=(38.0000002, 55.0), mode="drive"
            )
            await provider.build_route(origin=(37.0, 55.0), destination=(38.0, 55.0), mode="walk")
            await provider.build_route(origin=(38.0, 55.0), destination=(37.0, 55.0), mode="drive")
            metrics = provider.telemetry.snapshot()

        self.assertEqual(first, cached)
        self.assertEqual(len(calls), 3)
        self.assertEqual([call.url.params["mode"] for call in calls], ["drive", "walk", "drive"])
        self.assertEqual(metrics["provider_requests"], {"route": 3})
        self.assertEqual(metrics["cache_hits"], {"route": 1})
        self.assertEqual(metrics["profiles"], {"drive": 3, "walk": 1})

    async def test_matrix_cache_preserves_direction_and_provider_scope(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(
                200,
                json={
                    "sources_to_targets": [
                        [{"source_index": 0, "target_index": 0, "distance": 1_000, "time": 600}]
                    ]
                },
            )

        cache = GeoapifyResultCache(max_entries=8, max_bytes=4096)
        transport = httpx.MockTransport(handler)
        metrics_by_call = []
        for api_key, source, target in (
            ("key-one", (37.0, 55.0), (38.0, 55.0)),
            ("key-one", (37.0, 55.0), (38.0, 55.0)),
            ("key-one", (38.0, 55.0), (37.0, 55.0)),
            ("key-two", (37.0, 55.0), (38.0, 55.0)),
        ):
            async with AsyncGeoapifyRoutingClient(
                api_key,
                cache=cache,
                cache_ttl_seconds=60,
                transport=transport,
            ) as provider:
                result = await provider.build_route_matrix(
                    sources=[source], targets=[target], mode="drive"
                )
                self.assertEqual(result.cells[0][0].duration_seconds, 600)
                metrics_by_call.append(provider.telemetry.snapshot())

        self.assertEqual(len(calls), 3)
        self.assertEqual(metrics_by_call[1]["provider_requests"], {})
        self.assertEqual(metrics_by_call[1]["cache_hits"], {"matrix": 1})
        self.assertEqual(metrics_by_call[1]["matrix_cells"], 1)
        self.assertEqual(metrics_by_call[3]["provider_requests"], {"matrix": 1})
        self.assertEqual(metrics_by_call[3]["cache_hits"], {})

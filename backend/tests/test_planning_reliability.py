"""Planning failures and route-estimate reconciliation without a database."""

import unittest
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.core.config import Settings
from app.modules.planning import service
from app.modules.planning.errors import PlanningError
from app.modules.planning.policy import execution_policy
from app.modules.planning.schemas import PreviewRequest
from app.modules.routing.schemas import RouteMatrixCell, RouteMatrixResult, RouteResult
from tests.planning_fakes import FeasiblePlanner


def planning_settings():
    return Settings(
        database_url="postgresql://unused/isolated_test",
        jwt_secret_key="isolated-ci-only-key-at-least-thirty-two-characters",
        planning_enabled=True,
        planning_provider_concurrency=1,
    )


def prepared_case(settings):
    epoch = datetime(2030, 1, 15, 9, tzinfo=UTC)
    return {
        "epoch": epoch,
        "horizon": 120,
        "policy": execution_policy(settings),
        "open_end": False,
        "route_end": "return_to_start",
        "workers": [
            {
                "user_id": 10,
                "worker_id": 10,
                "location_id": 1,
                "profile": "drive",
                "transport_type": "car",
                "window": [0, 120],
            }
        ],
        "tickets": [
            {
                "id": 100,
                "location_id": 2,
                "window": [0, 110],
                "duration": 10,
                "duration_source": "ticket_estimate",
                "allowed": [0],
                "category": "repair",
                "priority": 3,
                "received_at": epoch,
                "sla_deadline_at": None,
                "deadline_at": None,
                "rejected": [],
                "allocations": [],
            }
        ],
        "locations": {
            1: {"longitude": 37.0, "latitude": 55.0},
            2: {"longitude": 38.0, "latitude": 55.0},
        },
        "unassigned": [],
        "excluded_workers": [],
    }


class RouteFixtureProvider:
    def __init__(self, outbound_seconds=(600,), *, geometry_mode="correct"):
        self.outbound_seconds = list(outbound_seconds)
        self.geometry_mode = geometry_mode
        self.outbound_calls = 0
        self.telemetry = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def build_route_matrix(self, *, sources, targets, mode):
        if self.telemetry is not None:
            self.telemetry.record_operation(
                "matrix", mode, cells=len(sources) * len(targets), source="geoapify_matrix"
            )
        return RouteMatrixResult(
            cells=[
                [
                    RouteMatrixCell(
                        distance_meters=0 if source == target else 1_000,
                        duration_seconds=0 if source == target else 60,
                    )
                    for target in targets
                ]
                for source in sources
            ]
        )

    async def build_route(self, *, origin, destination, mode):
        if self.telemetry is not None:
            self.telemetry.record_operation("route", mode, cells=0, source="geoapify_route")
        outbound = origin == (37.0, 55.0)
        if outbound:
            index = min(self.outbound_calls, len(self.outbound_seconds) - 1)
            seconds = self.outbound_seconds[index]
            self.outbound_calls += 1
        else:
            seconds = 60

        if self.geometry_mode == "swapped" and outbound:
            coordinates = [[[55.0, 37.0], [55.0, 38.0]]]
        elif self.geometry_mode == "gap" and outbound:
            coordinates = [
                [[37.0, 55.0], [37.1, 55.0]],
                [[37.9, 55.0], [38.0, 55.0]],
            ]
        else:
            coordinates = [[list(origin), list(destination)]]

        return RouteResult(
            distance_meters=1_000 if outbound else 1_000,
            duration_seconds=seconds,
            geometry={"type": "MultiLineString", "coordinates": coordinates},
        )


class CountingPlanner:
    def __init__(self):
        self.problems = []

    async def solve(self, problem):
        self.problems.append(problem.model_copy(deep=True))
        return await FeasiblePlanner().solve(problem)


class NullTransitionPlanner:
    async def solve(self, problem):
        solution = await FeasiblePlanner().solve(problem)
        first = solution.routes[0].steps[0].node
        second = solution.routes[0].steps[1].node
        problem.matrices["drive"].time_minutes[first][second] = None
        return solution


class SlowPlanner:
    async def solve(self, problem):
        import asyncio

        await asyncio.sleep(0.05)
        return await FeasiblePlanner().solve(problem)


class FakeSession:
    def __init__(self, saved):
        self.saved = saved

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def begin(self):
        return nullcontext()

    def add(self, value):
        self.saved.append(value)


class PlanningRouteReconciliationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = planning_settings()
        self.prepared = prepared_case(self.settings)
        self.snapshot = {
            "planning_policy": self.prepared["policy"].model_dump(mode="json"),
            "current_day_revision": None,
        }
        self.request = PreviewRequest(
            route_date=self.prepared["epoch"].date(), ticket_ids=[100], worker_ids=[10]
        )
        self.saved = []

    async def preview(self, provider, planner):
        with (
            patch.object(service, "read_snapshot", return_value=self.snapshot),
            patch.object(service, "prepare", return_value=self.prepared),
            patch.object(service, "visit_factors"),
            patch.object(service, "Session", side_effect=lambda _engine: FakeSession(self.saved)),
        ):
            return await service.preview(
                engine=object(),
                request=self.request,
                actor=1,
                settings=self.settings,
                provider_factory=lambda: provider,
                planner=planner,
                clock=lambda: self.prepared["epoch"],
            )

    async def test_matrix_discrepancy_updates_schedule_after_one_solver_rerun(self):
        provider, planner = RouteFixtureProvider(), CountingPlanner()

        plan = await self.preview(provider, planner)

        self.assertEqual(len(planner.problems), 2)
        self.assertEqual(planner.problems[0].matrices["drive"].time_minutes[0][1], 1)
        self.assertEqual(planner.problems[1].matrices["drive"].time_minutes[0][1], 10)
        arrival = datetime.fromisoformat(plan["routes"][0]["stops"][0]["arrival_at"])
        self.assertEqual(arrival, self.prepared["epoch"] + timedelta(minutes=10))
        self.assertEqual(plan["routes"][0]["travel_minutes"], 11)
        self.assertEqual(plan["metrics"]["routing"]["stages"]["solver"]["calls"], 2)
        self.assertEqual(plan["metrics"]["routing"]["profiles"]["drive"], 5)
        self.assertGreater(plan["metrics"]["routing"]["matrix_cells"], 0)
        self.assertEqual(len(self.saved), 1)

    async def test_second_matrix_discrepancy_rejects_before_plan_persistence(self):
        provider = RouteFixtureProvider(outbound_seconds=(600, 1_200))
        planner = CountingPlanner()

        with self.assertRaises(PlanningError) as caught:
            await self.preview(provider, planner)

        self.assertEqual(caught.exception.code, "routing_estimate_changed")
        self.assertEqual(len(planner.problems), 2)
        self.assertEqual(self.saved, [])

    def test_approximated_transit_metadata_keeps_approximation_marker(self):
        from app.modules.routing.schemas import GeoapifyPathProperties

        props = GeoapifyPathProperties(
            mode="approximated_transit",
            approximate=True,
            legs=[
                {
                    "from_sequence": 1,
                    "to_sequence": 2,
                    "distance_meters": 1,
                    "duration_seconds": 1,
                    "geometry_start": 0,
                    "geometry_end": 1,
                }
            ],
        )

        self.assertTrue(props.approximate)

    async def test_excessive_route_duration_rejects_before_plan_persistence(self):
        provider = RouteFixtureProvider(outbound_seconds=(10_000_000,))
        planner = CountingPlanner()

        with self.assertRaises(PlanningError) as caught:
            await self.preview(provider, planner)

        self.assertEqual(caught.exception.code, "routing_estimate_changed")
        self.assertEqual(len(planner.problems), 1)
        self.assertEqual(self.saved, [])

    async def test_common_timeout_rejects_without_persisting_a_plan(self):
        self.settings.planning_total_timeout_seconds = 0.01

        with self.assertRaises(PlanningError) as caught:
            await self.preview(RouteFixtureProvider(), SlowPlanner())

        self.assertEqual(caught.exception.code, "planning_timeout")
        self.assertEqual(self.saved, [])

    async def test_null_selected_transition_rejects_before_plan_persistence(self):
        with self.assertRaises(PlanningError) as caught:
            await self.preview(RouteFixtureProvider(), NullTransitionPlanner())

        self.assertEqual(caught.exception.code, "planner_invalid_response")
        self.assertEqual(self.saved, [])

    async def test_swapped_coordinates_reject_before_plan_persistence(self):
        provider = RouteFixtureProvider(outbound_seconds=(60,), geometry_mode="swapped")

        with self.assertRaises(PlanningError) as caught:
            await self.preview(provider, CountingPlanner())

        self.assertEqual(caught.exception.code, "routing_invalid_geometry")
        self.assertEqual(self.saved, [])

    async def test_gap_inside_provider_leg_rejects_without_connector_geometry(self):
        provider = RouteFixtureProvider(outbound_seconds=(60,), geometry_mode="gap")

        with self.assertRaises(PlanningError) as caught:
            await self.preview(provider, CountingPlanner())

        self.assertEqual(caught.exception.code, "routing_invalid_geometry")
        self.assertEqual(self.saved, [])

    async def test_approximated_transit_marker_is_saved_with_the_route(self):
        self.prepared["workers"][0]["profile"] = "approximated_transit"
        self.prepared["workers"][0]["transport_type"] = "public_transport"

        plan = await self.preview(RouteFixtureProvider(), CountingPlanner())

        route_create = self.saved[0].result_snapshot["route_creates"][0]
        self.assertEqual(route_create["path_properties"]["mode"], "approximated_transit")
        self.assertTrue(route_create["path_properties"]["approximate"])
        self.assertIn("estimated_transit", plan["warnings"])

"""Explicit deterministic boundaries for backend-only tests; E2E uses real OR-Tools."""

import httpx

from app.modules.planning.solver_contract import SolveResponse
from app.modules.routing.client import AsyncGeoapifyRoutingClient


def geoapify_response(request):
    import json

    if request.url.path.endswith("routematrix"):
        payload = json.loads(request.content)
        rows = []
        for i, source in enumerate(payload["sources"]):
            row = []
            for j, target in enumerate(payload["targets"]):
                same = source["location"] == target["location"]
                row.append(
                    {
                        "source_index": i,
                        "target_index": j,
                        "time": 0 if same else 60,
                        "distance": 0 if same else 100,
                    }
                )
            rows.append(row)
        return httpx.Response(200, json={"sources_to_targets": rows})
    positions = [
        list(reversed([float(x) for x in p.split(",")]))
        for p in request.url.params["waypoints"].split("|")
    ]
    return httpx.Response(
        200,
        json={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "MultiLineString", "coordinates": [positions]},
                    "properties": {"distance": 100, "time": 60},
                }
            ],
        },
    )


def provider_factory():
    return AsyncGeoapifyRoutingClient(
        "fixture-key", transport=httpx.MockTransport(geoapify_response)
    )


class FeasiblePlanner:
    """Simple fixture assignment, never presented as an optimizing implementation."""

    async def solve(self, problem):
        remaining = set(map(int, problem.allowed_vehicles))
        routes = []
        for vehicle, depot in enumerate(problem.starts):
            matrix = problem.matrices[problem.vehicle_profiles[vehicle]]
            arrival = problem.vehicle_time_windows[vehicle][0]
            steps = [{"node": depot, "arrival_time": arrival}]
            travel = distance = service = waiting = 0
            previous = depot
            for node in sorted(remaining):
                if vehicle not in problem.allowed_vehicles[str(node)]:
                    continue
                duration = matrix.time_minutes[previous][node]
                back = matrix.time_minutes[node][depot]
                if duration is None or back is None:
                    continue
                earliest = arrival + problem.service_times[previous] + duration
                next_time = max(earliest, problem.time_windows[node][0])
                if (
                    next_time > problem.time_windows[node][1]
                    or next_time + problem.service_times[node] + back
                    > problem.vehicle_time_windows[vehicle][1]
                ):
                    continue
                waiting += next_time - earliest
                service += problem.service_times[previous]
                travel += duration
                distance += matrix.distance_meters[previous][node]
                arrival, previous = next_time, node
                steps.append({"node": node, "arrival_time": arrival})
                remaining.remove(node)
            duration = matrix.time_minutes[previous][depot]
            arrival += problem.service_times[previous] + duration
            service += problem.service_times[previous]
            travel += duration
            distance += matrix.distance_meters[previous][depot]
            steps.append({"node": depot, "arrival_time": arrival})
            routes.append(
                {
                    "vehicle_id": vehicle,
                    "steps": steps,
                    "distance": distance,
                    "travel_minutes": travel,
                    "service_minutes": service,
                    "waiting_minutes": waiting,
                }
            )
        return SolveResponse(
            status="FEASIBLE",
            solver_status_code=1,
            routes=routes,
            dropped_nodes=sorted(remaining),
            total_distance=sum(r["distance"] for r in routes),
            total_cost=sum(r["travel_minutes"] for r in routes)
            + sum(problem.penalties[n] for n in remaining),
        )

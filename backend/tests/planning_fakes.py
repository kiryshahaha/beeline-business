"""Explicit deterministic boundaries for backend-only tests; E2E uses real OR-Tools."""

import httpx

from app.modules.planning.solver_contract import ObjectiveComponents, SolveResponse
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
    """Simple fixture assignment, never presented as an optimizing implementation.

    A greedy pass takes visits in window order; then every visit left over is tried in
    the waiting gaps of the routes, so a fixed visit keeps its time and a short request
    can still use the time before it, as a real solver would.
    """

    async def solve(self, problem):
        remaining = set(map(int, problem.allowed_vehicles))
        task_nodes = sorted(
            set(range(len(problem.time_windows))) - set(problem.starts) - set(problem.ends)
        )
        policy_by_node = dict(zip(task_nodes, problem.ticket_policies, strict=True))

        def schedule(vehicle, order):
            """Arrival times and totals of a route, or None when it breaks a window."""
            depot, finish = problem.starts[vehicle], problem.ends[vehicle]
            matrix = problem.matrices[problem.vehicle_profiles[vehicle]]
            arrival = problem.vehicle_time_windows[vehicle][0]
            steps = [{"node": depot, "arrival_time": arrival}]
            totals = {"travel": 0, "distance": 0, "service": 0, "waiting": 0}
            response = reassigned = 0
            previous = depot
            for node in order:
                policy = policy_by_node[node]
                duration = matrix.time_minutes[previous][node]
                back = matrix.time_minutes[node][finish]
                if duration is None or back is None:
                    return None
                earliest = arrival + problem.service_times[previous] + duration
                next_time = max(earliest, problem.time_windows[node][0])
                if (
                    next_time > problem.time_windows[node][1]
                    or next_time < policy.received_at
                    or (
                        policy.sla_deadline_at is not None
                        and next_time + problem.service_times[node] > policy.sla_deadline_at
                    )
                    or next_time + problem.service_times[node] + back
                    > problem.vehicle_time_windows[vehicle][1]
                ):
                    return None
                totals["waiting"] += next_time - earliest
                totals["service"] += problem.service_times[previous]
                totals["travel"] += duration
                totals["distance"] += matrix.distance_meters[previous][node]
                arrival, previous = next_time, node
                steps.append({"node": node, "arrival_time": arrival})
                if policy.category == "emergency":
                    response += arrival - policy.received_at
                reassigned += policy.previous_vehicle_id not in (None, vehicle)
            duration = matrix.time_minutes[previous][finish]
            arrival += problem.service_times[previous] + duration
            totals["service"] += problem.service_times[previous]
            totals["travel"] += duration
            totals["distance"] += matrix.distance_meters[previous][finish]
            steps.append({"node": finish, "arrival_time": arrival})
            return steps, totals, response, reassigned

        orders = []
        for vehicle in range(len(problem.starts)):
            order = []
            for node in sorted(
                remaining,
                key=lambda item: (
                    problem.time_windows[item][0] != problem.time_windows[item][1],
                    problem.time_windows[item][0],
                    item,
                ),
            ):
                if vehicle in problem.allowed_vehicles[str(node)] and schedule(
                    vehicle, [*order, node]
                ):
                    order.append(node)
                    remaining.remove(node)
            orders.append(order)
        for node in sorted(remaining, key=lambda item: (problem.time_windows[item][0], item)):
            for vehicle in problem.allowed_vehicles[str(node)]:
                order = orders[vehicle]
                position = next(
                    (
                        index
                        for index in range(len(order) + 1)
                        if schedule(vehicle, [*order[:index], node, *order[index:]])
                    ),
                    None,
                )
                if position is not None:
                    order.insert(position, node)
                    remaining.remove(node)
                    break
        routes = []
        response = reassigned = 0
        for vehicle, order in enumerate(orders):
            steps, totals, route_response, route_reassigned = schedule(vehicle, order)
            response += route_response
            reassigned += route_reassigned
            routes.append(
                {
                    "vehicle_id": vehicle,
                    "steps": steps,
                    "distance": totals["distance"],
                    "travel_minutes": totals["travel"],
                    "service_minutes": totals["service"],
                    "waiting_minutes": totals["waiting"],
                }
            )
        dropped = [policy_by_node[node].category for node in remaining]
        components = ObjectiveComponents(
            unassigned_emergencies=dropped.count("emergency"),
            emergency_response_minutes=response,
            unassigned_connections=dropped.count("connection"),
            unassigned_total=len(dropped),
            active_workers=sum(len(r["steps"]) > 2 for r in routes),
            travel_minutes=sum(r["travel_minutes"] for r in routes),
            reassigned_visits=reassigned,
        )
        weights = problem.objective_weights()
        return SolveResponse(
            status="FEASIBLE",
            solver_status_code=1,
            routes=routes,
            dropped_nodes=sorted(remaining),
            total_distance=sum(r["distance"] for r in routes),
            total_cost=weights.cost(components),
            objective_components=components,
            objective_weights=weights,
        )

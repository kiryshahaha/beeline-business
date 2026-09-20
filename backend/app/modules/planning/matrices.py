"""Separate logical visits from unique coordinates and query all directed matrix blocks."""

import math

from app.modules.planning.async_utils import bounded_map
from app.modules.planning.errors import PlanningError
from app.modules.planning.solver_contract import SolveRequest


async def build_problem(prepared: dict, provider, settings) -> tuple[SolveRequest, list[dict]]:
    workers, tickets = prepared["workers"], prepared["tickets"]
    nodes = [{"kind": "depot", "location_id": w["location_id"]} for w in workers] + [
        {"kind": "ticket", "location_id": t["location_id"], "ticket": t} for t in tickets
    ]
    coordinates, coordinate_index, node_coordinates = [], {}, []
    for node in nodes:
        location = prepared["locations"][node["location_id"]]
        position = (float(location["longitude"]), float(location["latitude"]))
        if position not in coordinate_index:
            coordinate_index[position] = len(coordinates)
            coordinates.append(position)
        node_coordinates.append(coordinate_index[position])
    profiles = sorted({w["profile"] for w in workers})
    u = len(coordinates)
    if len(profiles) * u * u > settings.planning_max_matrix_cells_total:
        raise PlanningError("planning_limit_exceeded")
    matrices = {
        p: {
            "time_minutes": [[None] * u for _ in range(u)],
            "distance_meters": [[None] * u for _ in range(u)],
        }
        for p in profiles
    }
    blocks = [(p, a, b) for p in profiles for a in range(0, u, 25) for b in range(0, u, 25)]

    async def fetch(block):
        profile, a, b = block
        result = await provider.build_route_matrix(
            sources=coordinates[a : a + 25], targets=coordinates[b : b + 25], mode=profile
        )
        matrix = matrices[profile]
        for i, row in enumerate(result.cells):
            for j, cell in enumerate(row):
                duration, distance = cell.duration_seconds, cell.distance_meters
                if i + a == j + b:
                    duration = distance = 0
                if duration is None or distance is None:
                    continue
                if not all(
                    math.isfinite(x) and 0 <= x <= 1_000_000_000 for x in (duration, distance)
                ):
                    raise PlanningError("routing_invalid_response", 502)
                matrix["time_minutes"][a + i][b + j] = math.ceil(duration / 60)
                matrix["distance_meters"][a + i][b + j] = math.ceil(distance)

    await bounded_map(fetch, blocks, settings.planning_provider_concurrency)
    expanded = {
        p: {
            key: [[values[i][j] for j in node_coordinates] for i in node_coordinates]
            for key, values in matrix.items()
        }
        for p, matrix in matrices.items()
    }
    v, horizon = len(workers), prepared["horizon"]
    request = SolveRequest(
        num_vehicles=v,
        starts=list(range(v)),
        ends=list(range(v)),
        vehicle_profiles=[w["profile"] for w in workers],
        vehicle_time_windows=[w["window"] for w in workers],
        matrices=expanded,
        time_windows=[[0, horizon] for _ in workers] + [t["window"] for t in tickets],
        service_times=[0] * v + [t["duration"] for t in tickets],
        allowed_vehicles={str(v + i): t["allowed"] for i, t in enumerate(tickets)},
        penalties=[0] * v + [v * horizon + 1] * len(tickets),
        time_capacity=horizon,
        slack_max=horizon,
        search_time_limit_s=settings.planning_solve_time_limit_seconds,
    )
    return request, nodes

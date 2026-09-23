"""Separate logical visits from unique coordinates and query all directed matrix blocks."""

import math

from app.modules.planning.async_utils import bounded_map
from app.modules.planning.errors import PlanningError
from app.modules.planning.policy import execution_policy
from app.modules.planning.solver_contract import SolveRequest


async def build_problem(prepared: dict, provider, settings) -> tuple[SolveRequest, list[dict]]:
    policy = prepared.get("policy") or execution_policy(settings)
    open_end: bool = prepared.get("open_end", False)
    workers, tickets = prepared["workers"], prepared["tickets"]
    # Depot (start) nodes — one per worker.
    depot_nodes = [{"kind": "depot", "location_id": w["location_id"]} for w in workers]
    # Finish nodes — separate when open_end, same index as depot otherwise.
    if open_end:
        finish_nodes = [{"kind": "finish", "location_id": w["location_id"]} for w in workers]
    else:
        finish_nodes = depot_nodes  # same objects; starts == ends
    task_nodes = [
        {"kind": "ticket", "location_id": t["location_id"], "ticket": t} for t in tickets
    ]
    # Node ordering: depots | (finishes if open_end) | tasks
    if open_end:
        nodes = depot_nodes + finish_nodes + task_nodes
        v = len(workers)
        starts = list(range(v))
        ends = list(range(v, 2 * v))
        task_offset = 2 * v
    else:
        nodes = depot_nodes + task_nodes
        v = len(workers)
        starts = list(range(v))
        ends = list(range(v))
        task_offset = v
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
    n = len(nodes)
    horizon = prepared["horizon"]
    # Time windows for depot and (when open_end) finish nodes are the vehicle window.
    # Finish nodes in open_end have the full vehicle time window (any moment in shift is fine).
    depot_windows = [w["window"] for w in workers]
    finish_windows = [w["window"] for w in workers] if open_end else []
    task_windows = [t["window"] for t in tickets]
    depot_service = [0] * v
    finish_service = [0] * v if open_end else []
    task_service = [t["duration"] for t in tickets]
    depot_penalties = [0] * v
    finish_penalties = [0] * v if open_end else []
    task_penalties = [policy.penalty(v, horizon)] * len(tickets)
    # allowed_vehicles keys are task node indices (strings).
    allowed = {
        str(task_offset + i): t["allowed"] for i, t in enumerate(tickets)
    }
    request = SolveRequest(
        policy_version=policy.policy_version,
        num_vehicles=v,
        starts=starts,
        ends=ends,
        open_end=open_end,
        vehicle_profiles=[w["profile"] for w in workers],
        vehicle_time_windows=depot_windows,
        matrices=expanded,
        time_windows=depot_windows + finish_windows + task_windows,
        service_times=depot_service + finish_service + task_service,
        allowed_vehicles=allowed,
        penalties=depot_penalties + finish_penalties + task_penalties,
        time_capacity=horizon,
        slack_max=horizon,
        search_time_limit_s=policy.search_time_limit_seconds,
    )
    return request, nodes

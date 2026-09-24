"""Retrieve selected roads only; never turn provider gaps into invented road segments."""

import math
from datetime import timedelta

from pydantic import ValidationError

from app.modules.planning.async_utils import bounded_map
from app.modules.planning.errors import PlanningError
from app.modules.routing.schemas import (
    GeoapifyPathProperties,
    MultiLineString,
    RouteCreate,
    RouteGeoJSON,
    RouteLeg,
    RouteStop,
)


async def build_routes(prepared, problem, nodes, solution, provider, settings):
    locations = prepared["locations"]
    open_end: bool = problem.open_end

    def position(node):
        loc = locations[nodes[node]["location_id"]]
        return (float(loc["longitude"]), float(loc["latitude"]))

    routes = [r for r in solution.routes if len(r.steps) > 2]
    requests = sorted(
        {
            (problem.vehicle_profiles[r.vehicle_id], position(a.node), position(b.node))
            for r in routes
            for a, b in zip(r.steps, r.steps[1:])
            if position(a.node) != position(b.node)
        }
    )

    async def fetch(key):
        mode, start, end = key
        result = await provider.build_route(origin=start, destination=end, mode=mode)
        if not all(
            math.isfinite(x) and x >= 0 for x in (result.distance_meters, result.duration_seconds)
        ):
            raise PlanningError("routing_invalid_response", 502)
        try:
            MultiLineString.model_validate(result.geometry)
        except ValidationError as error:
            raise PlanningError("routing_invalid_response", 502) from error
        return key, result

    roads = dict(await bounded_map(fetch, requests, settings.planning_provider_concurrency))
    output, snapshots = [], []
    epoch = prepared["epoch"]
    finish_nodes = set(problem.ends) if open_end else set()

    for route in routes:
        vehicle = route.vehicle_id
        worker = prepared["workers"][vehicle]
        lines, legs, public_steps, stops, visits = [], [], [], [], []
        travel = distance = waiting_total = 0
        matrix = problem.matrices[worker["profile"]]

        for index, step in enumerate(route.steps):
            node_index = step.node
            # open_end: skip the virtual finish node from public stops/legs
            if open_end and node_index in finish_nodes and index == len(route.steps) - 1:
                # Still account for travel to finish in metrics
                if index > 0:
                    previous_step = route.steps[index - 1]
                    travel_to_finish = matrix.time_minutes[previous_step.node][node_index]
                    if travel_to_finish is None:
                        raise PlanningError("routing_estimate_changed", 502)
                    travel += travel_to_finish
                break

            node = nodes[node_index]

            # Physical arrival = epoch + step.arrival_time (the solver's cumul value).
            # For depots (index==0) there is no waiting: service_start == arrival_at.
            # For task nodes the solver already accounts for waiting: arrival_time
            # is the service_start (earliest the window allows), NOT the physical
            # road arrival.  We reconstruct the physical arrival from the previous
            # step's service_end + travel to separate the two timestamps (F10).
            if index == 0:
                physical_arrival = epoch + timedelta(minutes=step.arrival_time)
                service_start = physical_arrival
                wait_minutes = 0
            else:
                previous_step = route.steps[index - 1]
                prev_service_end_min = (
                    previous_step.arrival_time + problem.service_times[previous_step.node]
                )
                start_pos = position(previous_step.node)
                end_pos = position(node_index)
                road = (
                    roads.get((worker["profile"], start_pos, end_pos))
                    if start_pos != end_pos
                    else None
                )
                seconds, meters_leg = (
                    (road.duration_seconds, road.distance_meters) if road else (0, 0)
                )
                conservative_travel = max(
                    matrix.time_minutes[previous_step.node][node_index],
                    math.ceil(seconds / 60),
                )
                if conservative_travel < 0:
                    raise PlanningError("routing_estimate_changed", 502)
                physical_arrival_min = prev_service_end_min + conservative_travel
                # service_start = max(physical_arrival, window_lower)
                # The solver stores the service-start in arrival_time.
                service_start_min = step.arrival_time
                wait_minutes = service_start_min - physical_arrival_min
                if wait_minutes < 0:
                    raise PlanningError("routing_estimate_changed", 502)
                physical_arrival = epoch + timedelta(minutes=physical_arrival_min)
                service_start = epoch + timedelta(minutes=service_start_min)
                distance += meters_leg
                travel += conservative_travel
                waiting_total += wait_minutes
                # Build leg (index > 0)
                begin = len(lines)
                if road:
                    lines.extend(road.geometry["coordinates"])
                legs.append(
                    RouteLeg(
                        from_sequence=index,
                        to_sequence=index + 1,
                        distance_meters=meters_leg,
                        duration_seconds=seconds,
                        geometry_start=begin,
                        geometry_end=len(lines),
                    )
                )

            stop = {
                "location_id": node["location_id"],
                "arrival_at": physical_arrival.isoformat(),
                "service_start_at": service_start.isoformat(),
            }
            if node["kind"] == "ticket":
                ticket = node["ticket"]
                stop["ticket_id"] = ticket["id"]
                service_end = service_start + timedelta(minutes=ticket["duration"])
                visits.append(
                    {
                        **stop,
                        "sequence": len(visits) + 1,
                        "service_end_at": service_end.isoformat(),
                        "waiting_minutes": wait_minutes,
                        "effective_service_minutes": ticket["duration"],
                        "duration_source": ticket["duration_source"],
                    }
                )
            public_steps.append(step)
            stops.append(stop)

        properties = GeoapifyPathProperties(
            mode=worker["profile"], legs=legs, snap_limit_meters=settings.planning_max_snap_meters
        )
        # RouteCreate uses arrival_at for ordering; use service_start_at as the persisted stop time
        # (clients see service_start_at via the public PlannedVisit, not RouteStop.arrival_at).
        route_stops = [
            RouteStop(
                location_id=s["location_id"],
                ticket_id=s.get("ticket_id"),
                arrival_at=s["service_start_at"],  # persisted as service_start for DB/schedule
            )
            for s in stops
        ]
        try:
            data = RouteCreate(
                worker_id=worker["user_id"],
                route_date=epoch.date(),
                stops=route_stops,
                geometry=MultiLineString(coordinates=lines) if lines else None,
                path_properties=properties if lines else None,
            )
            # Validate snapped endpoints and leg indexing before a proposal can be applied.
            features = [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": position(step.node)},
                    "properties": {**stop, "sequence": i + 1},
                }
                for i, (step, stop) in enumerate(zip(public_steps, stops, strict=True))
            ]
            if lines:
                features.append(
                    {
                        "type": "Feature",
                        "geometry": data.geometry.model_dump(),
                        "properties": properties.model_dump(),
                    }
                )
            RouteGeoJSON.model_validate(
                {
                    "type": "FeatureCollection",
                    "properties": {
                        "worker_id": worker["user_id"],
                        "route_date": epoch.date(),
                        "route_number": 1,
                    },
                    "features": features,
                }
            )
        except ValidationError as error:
            raise PlanningError("routing_invalid_geometry", 502) from error
        snapshots.append(data.model_dump(mode="json"))
        departure_at = stops[0]["service_start_at"]
        return_at = stops[-1]["service_start_at"]
        output.append(
            {
                "worker_id": worker["user_id"],
                "transport_type": worker["transport_type"],
                "routing_mode": worker["profile"],
                "start_location_id": worker.get("start_location_id", worker["location_id"]),
                "end_location_id": worker.get("end_location_id", worker["location_id"]),
                "departure_at": departure_at,
                "return_at": return_at,
                "distance_meters": distance,
                "travel_minutes": travel,
                "service_minutes": route.service_minutes,
                "waiting_minutes": waiting_total,
                "stops": visits,
                "geometry": data.geometry.model_dump(mode="json") if data.geometry else None,
                "legs": [leg.model_dump() for leg in legs],
            }
        )
    return output, snapshots

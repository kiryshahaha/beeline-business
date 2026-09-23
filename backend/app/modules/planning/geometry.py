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
)


async def build_routes(prepared, problem, nodes, solution, provider, settings):
    locations = prepared["locations"]

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
    for route in routes:
        vehicle = route.vehicle_id
        worker = prepared["workers"][vehicle]
        lines, legs, stops, visits = [], [], [], []
        travel = distance = waiting = 0
        matrix = problem.matrices[worker["profile"]]
        for index, step in enumerate(route.steps):
            node = nodes[step.node]
            arrival = epoch + timedelta(minutes=step.arrival_time)
            stop = {"location_id": node["location_id"], "arrival_at": arrival.isoformat()}
            if node["kind"] == "ticket":
                ticket = node["ticket"]
                stop["ticket_id"] = ticket["id"]
                visits.append(
                    {
                        **stop,
                        "sequence": len(visits) + 1,
                        "service_end_at": (
                            arrival + timedelta(minutes=ticket["duration"])
                        ).isoformat(),
                        "effective_service_minutes": ticket["duration"],
                        "duration_source": ticket["duration_source"],
                    }
                )
            stops.append(stop)
            if index == 0:
                continue
            previous = route.steps[index - 1]
            start, end = position(previous.node), position(step.node)
            road = roads.get((worker["profile"], start, end)) if start != end else None
            seconds, meters = (road.duration_seconds, road.distance_meters) if road else (0, 0)
            conservative = max(
                matrix.time_minutes[previous.node][step.node], math.ceil(seconds / 60)
            )
            gap = (
                step.arrival_time
                - previous.arrival_time
                - problem.service_times[previous.node]
                - conservative
            )
            if gap < 0:
                raise PlanningError("routing_estimate_changed", 502)
            begin = len(lines)
            if road:
                lines.extend(road.geometry["coordinates"])
            legs.append(
                RouteLeg(
                    from_sequence=index,
                    to_sequence=index + 1,
                    distance_meters=meters,
                    duration_seconds=seconds,
                    geometry_start=begin,
                    geometry_end=len(lines),
                )
            )
            distance += meters
            travel += conservative
            waiting += gap
        properties = GeoapifyPathProperties(
            mode=worker["profile"], legs=legs, snap_limit_meters=settings.planning_max_snap_meters
        )
        try:
            data = RouteCreate(
                worker_id=worker["user_id"],
                route_date=epoch.date(),
                stops=stops,
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
                for i, (step, stop) in enumerate(zip(route.steps, stops, strict=True))
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
        output.append(
            {
                "worker_id": worker["user_id"],
                "transport_type": worker["transport_type"],
                "routing_mode": worker["profile"],
                "start_location_id": worker.get("start_location_id", worker["location_id"]),
                "end_location_id": worker.get("end_location_id", worker["location_id"]),
                "departure_at": stops[0]["arrival_at"],
                "return_at": stops[-1]["arrival_at"],
                "distance_meters": distance,
                "travel_minutes": travel,
                "service_minutes": route.service_minutes,
                "waiting_minutes": waiting,
                "stops": visits,
                "geometry": data.geometry.model_dump(mode="json") if data.geometry else None,
                "legs": [leg.model_dump() for leg in legs],
            }
        )
    return output, snapshots

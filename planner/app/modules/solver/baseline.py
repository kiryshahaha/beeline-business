from app.modules.solver.schemas import (
    ObjectiveComponents,
    Route,
    SolveRequest,
    SolveResponse,
    Step,
)


def solve_baseline(data: SolveRequest) -> SolveResponse:
    n = len(data.time_windows)
    depots = set(data.starts) | set(data.ends)
    tasks = sorted(set(range(n)) - depots)

    # Map node to its task_index in the ticket_policies array
    task_index_to_position = {node: i for i, node in enumerate(tasks)}

    # Sort tasks: (received_at, stable key: ticket_id)
    sorted_tasks = sorted(
        tasks,
        key=lambda node: (
            data.ticket_policies[task_index_to_position[node]].received_at,
            data.ticket_policies[task_index_to_position[node]].ticket_id,
        ),
    )

    # Initialize vehicles
    vehicle_states = []
    for v in range(data.num_vehicles):
        vehicle_states.append(
            {
                "current_node": data.starts[v],
                "current_time": data.vehicle_time_windows[v][0],
                "steps": [Step(node=data.starts[v], arrival_time=data.vehicle_time_windows[v][0])],
                "distance": 0,
                "travel_minutes": 0,
                "service_minutes": 0,
                "waiting_minutes": 0,
            }
        )

    dropped = []

    for node in sorted_tasks:
        policy = data.ticket_policies[task_index_to_position[node]]
        assigned = False

        # Try to assign to the first eligible vehicle
        for v in range(data.num_vehicles):
            if v not in data.allowed_vehicles[str(node)]:
                continue

            state = vehicle_states[v]
            profile = data.vehicle_profiles[v]
            matrix = data.matrices[profile]

            travel = matrix.time_minutes[state["current_node"]][node]
            if travel is None:
                continue

            arrival_time = (
                state["current_time"] + data.service_times[state["current_node"]] + travel
            )

            window_start, window_end = data.time_windows[node]
            window_start = max(window_start, policy.received_at)
            if policy.sla_deadline_at is not None:
                window_end = min(window_end, policy.sla_deadline_at - data.service_times[node])

            if arrival_time > window_end:
                continue

            wait_time = max(0, window_start - arrival_time)
            if wait_time > data.slack_max:
                continue

            service_start = arrival_time + wait_time
            if service_start > window_end:
                continue

            # Check return to depot
            return_node = data.ends[v]
            return_travel = matrix.time_minutes[node][return_node]
            if return_travel is None:
                continue

            return_arrival = service_start + data.service_times[node] + return_travel
            depot_end = data.vehicle_time_windows[v][1]
            if return_arrival > depot_end:
                continue

            # Valid assignment, apply it
            meters = matrix.distance_meters[state["current_node"]][node]

            # Like the solver, a step records the service start after waiting.
            state["steps"].append(Step(node=node, arrival_time=service_start))
            state["distance"] += meters
            state["travel_minutes"] += travel
            state["waiting_minutes"] += wait_time
            state["service_minutes"] += data.service_times[state["current_node"]]

            state["current_node"] = node
            state["current_time"] = service_start
            assigned = True
            break

        if not assigned:
            dropped.append(node)

    # Close routes
    routes = []
    response_minutes = active_workers = reassigned = 0

    for v in range(data.num_vehicles):
        state = vehicle_states[v]
        profile = data.vehicle_profiles[v]
        matrix = data.matrices[profile]

        return_node = data.ends[v]
        travel = matrix.time_minutes[state["current_node"]][return_node]
        meters = matrix.distance_meters[state["current_node"]][return_node]

        arrival_time = state["current_time"] + data.service_times[state["current_node"]] + travel

        state["steps"].append(Step(node=return_node, arrival_time=arrival_time))
        state["distance"] += meters
        state["travel_minutes"] += travel
        state["service_minutes"] += data.service_times[state["current_node"]]

        if len(state["steps"]) > 2:
            active_workers += 1

        routes.append(
            Route(
                vehicle_id=v,
                steps=state["steps"],
                distance=state["distance"],
                travel_minutes=state["travel_minutes"],
                service_minutes=state["service_minutes"],
                waiting_minutes=state["waiting_minutes"],
            )
        )

        for step in state["steps"][1:-1]:
            policy = data.ticket_policies[task_index_to_position[step.node]]
            if policy.previous_vehicle_id not in (None, v):
                reassigned += 1
            if policy.category == "emergency":
                response_minutes += step.arrival_time - policy.received_at

    dropped_categories = [data.ticket_policies[task_index_to_position[n]].category for n in dropped]
    components = ObjectiveComponents(
        unassigned_emergencies=dropped_categories.count("emergency"),
        emergency_response_minutes=response_minutes,
        unassigned_connections=dropped_categories.count("connection"),
        unassigned_total=len(dropped),
        active_workers=active_workers,
        travel_minutes=sum(r.travel_minutes for r in routes),
        reassigned_visits=reassigned,
    )
    weights = data.objective_weights()

    return SolveResponse(
        contract_version=2,
        status="FEASIBLE",
        solver_status_code=1,  # Equivalent to ROUTING_SUCCESS
        routes=routes,
        dropped_nodes=sorted(dropped),
        total_cost=weights.cost(components),
        total_distance=sum(r.distance for r in routes),
        objective_components=components,
        objective_weights=weights,
    )

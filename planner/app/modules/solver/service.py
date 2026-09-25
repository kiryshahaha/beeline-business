"""Mixed-profile VRPTW with explicit eligibility and conservative time arithmetic."""

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.modules.solver.schemas import (
    ObjectiveComponents,
    Route,
    SolveRequest,
    SolveResponse,
    Step,
)

W_CHANGE = 1
W_TRAVEL = 1
W_VEHICLE = 100_000
W_DROP_TOTAL = 10_000_000
W_DROP_CONN = 1_000_000_000
W_DELAY_EMERG = 100_000_000_000
W_DROP_EMERG = 30_000_000_000_000_000


def solve(data: SolveRequest) -> SolveResponse:
    n = len(data.time_windows)
    manager = pywrapcp.RoutingIndexManager(n, data.num_vehicles, data.starts, data.ends)
    routing = pywrapcp.RoutingModel(manager)
    time_callbacks = {}

    tasks = sorted(set(range(n)) - (set(data.starts) | set(data.ends)))
    task_index_to_position = {node: i for i, node in enumerate(tasks)}

    def make_time_callback(profile: str):
        matrix = data.matrices[profile].time_minutes

        def callback(source: int, target: int) -> int:
            a, b = manager.IndexToNode(source), manager.IndexToNode(target)
            travel = matrix[a][b]
            if travel is None:
                return data.time_capacity + 1
            return travel + data.service_times[a]

        return callback

    def make_cost_callback(profile: str, vehicle_id: int):
        matrix = data.matrices[profile].time_minutes

        def callback(source: int, target: int) -> int:
            a, b = manager.IndexToNode(source), manager.IndexToNode(target)
            travel = matrix[a][b]
            if travel is None:
                return data.time_capacity + 1
            cost = travel * W_TRAVEL
            if b in task_index_to_position:
                policy = data.ticket_policies[task_index_to_position[b]]
                if (
                    policy.previous_vehicle_id is not None
                    and policy.previous_vehicle_id != vehicle_id
                ):
                    cost += W_CHANGE
            return cost

        return callback

    for profile in data.matrices:
        time_callbacks[profile] = routing.RegisterTransitCallback(make_time_callback(profile))

    routing.AddDimensionWithVehicleTransits(
        [time_callbacks[p] for p in data.vehicle_profiles],
        data.slack_max,
        data.time_capacity,
        False,
        "Time",
    )
    dimension = routing.GetDimensionOrDie("Time")

    cost_callbacks = []
    for v, profile in enumerate(data.vehicle_profiles):
        cb = routing.RegisterTransitCallback(make_cost_callback(profile, v))
        cost_callbacks.append(cb)
        routing.SetArcCostEvaluatorOfVehicle(cb, v)
        routing.SetFixedCostOfVehicle(W_VEHICLE, v)
        a, b = data.vehicle_time_windows[v]
        dimension.CumulVar(routing.Start(v)).SetRange(a, b)
        dimension.CumulVar(routing.End(v)).SetRange(a, b)

    for task_position, node in enumerate(tasks):
        index = manager.NodeToIndex(node)
        lower, upper = data.time_windows[node]
        ticket_policy = data.ticket_policies[task_position]
        lower = max(lower, ticket_policy.received_at)
        if ticket_policy.sla_deadline_at is not None:
            upper = min(upper, ticket_policy.sla_deadline_at - data.service_times[node])

        penalty = W_DROP_TOTAL
        if ticket_policy.category == "emergency":
            penalty += W_DROP_EMERG
        elif ticket_policy.category == "connection":
            penalty += W_DROP_CONN

        routing.AddDisjunction([index], penalty)
        if lower > upper:
            routing.ActiveVar(index).SetValue(0)
        else:
            dimension.CumulVar(index).SetRange(lower, upper)

        if ticket_policy.category == "emergency":
            dimension.SetCumulVarSoftUpperBound(index, ticket_policy.received_at, W_DELAY_EMERG)

        allowed = data.allowed_vehicles[str(node)]
        if not allowed:
            routing.ActiveVar(index).SetValue(0)
        else:
            # Keep -1 (inactive) in the domain so dropping remains possible.
            for vehicle in range(data.num_vehicles):
                if vehicle not in allowed:
                    routing.VehicleVar(index).RemoveValue(vehicle)

    parameters = pywrapcp.DefaultRoutingSearchParameters()
    parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    )
    parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    parameters.time_limit.seconds = data.search_time_limit_s
    assignment = routing.SolveWithParameters(parameters)
    status = routing.status()
    if assignment is None:
        return SolveResponse(
            contract_version=2,
            status="INFEASIBLE" if status == 6 else "NOT_SOLVED",
            solver_status_code=status,
        )

    routes = []
    dropped_emergencies = 0
    emergency_delays = 0
    dropped_connections = 0
    active_vehicles = 0
    changed_assignments = 0

    for vehicle in range(data.num_vehicles):
        matrix = data.matrices[data.vehicle_profiles[vehicle]]
        index = routing.Start(vehicle)
        previous = manager.IndexToNode(index)
        arrival = assignment.Min(dimension.CumulVar(index))
        steps = [Step(node=previous, arrival_time=arrival)]
        distance = travel_total = service_total = waiting = 0
        while not routing.IsEnd(index):
            index = assignment.Value(routing.NextVar(index))
            node = manager.IndexToNode(index)
            travel = matrix.time_minutes[previous][node]
            meters = matrix.distance_meters[previous][node]
            if travel is None or meters is None:
                raise RuntimeError("Solver selected an unreachable arc")
            arrival += data.service_times[previous] + travel
            wait = assignment.Min(dimension.CumulVar(index)) - arrival
            if wait < 0 or wait > data.slack_max:
                raise RuntimeError("Solver route has invalid waiting")
            arrival += wait
            upper = (
                data.vehicle_time_windows[vehicle][1]
                if routing.IsEnd(index)
                else data.time_windows[node][1]
            )
            if arrival > upper:
                raise RuntimeError("Solver route has no valid concrete schedule")
            distance += meters
            travel_total += travel
            service_total += data.service_times[previous]
            waiting += wait
            steps.append(Step(node=node, arrival_time=arrival))

            if node in task_index_to_position:
                policy = data.ticket_policies[task_index_to_position[node]]
                if policy.previous_vehicle_id is not None and policy.previous_vehicle_id != vehicle:
                    changed_assignments += 1
                if policy.category == "emergency":
                    delay = max(0, arrival - policy.received_at)
                    emergency_delays += delay

            previous = node

        if len(steps) > 2:
            active_vehicles += 1

        routes.append(
            Route(
                vehicle_id=vehicle,
                steps=steps,
                distance=distance,
                travel_minutes=travel_total,
                service_minutes=service_total,
                waiting_minutes=waiting,
            )
        )

    dropped = [
        node
        for node in tasks
        if assignment.Value(routing.NextVar(manager.NodeToIndex(node))) == manager.NodeToIndex(node)
    ]

    for node in dropped:
        policy = data.ticket_policies[task_index_to_position[node]]
        if policy.category == "emergency":
            dropped_emergencies += 1
        elif policy.category == "connection":
            dropped_connections += 1

    components = ObjectiveComponents(
        dropped_emergencies=dropped_emergencies,
        emergency_delays=emergency_delays,
        dropped_connections=dropped_connections,
        dropped_total=len(dropped),
        active_vehicles=active_vehicles,
        travel_time=sum(route.travel_minutes for route in routes),
        changed_assignments=changed_assignments,
    )

    return SolveResponse(
        contract_version=2,
        status="OPTIMAL" if status == 7 else "FEASIBLE",
        solver_status_code=status,
        routes=routes,
        dropped_nodes=dropped,
        total_cost=assignment.ObjectiveValue(),
        total_distance=sum(route.distance for route in routes),
        objective_components=components,
    )

"""Mixed-profile VRPTW with explicit eligibility and conservative time arithmetic."""

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.modules.solver.schemas import Route, SolveRequest, SolveResponse, Step


def solve(data: SolveRequest) -> SolveResponse:
    n = len(data.time_windows)
    manager = pywrapcp.RoutingIndexManager(n, data.num_vehicles, data.starts, data.ends)
    routing = pywrapcp.RoutingModel(manager)
    time_callbacks, cost_callbacks = {}, {}

    def make_callback(profile: str, include_service: bool):
        matrix = data.matrices[profile].time_minutes

        def callback(source: int, target: int) -> int:
            a, b = manager.IndexToNode(source), manager.IndexToNode(target)
            travel = matrix[a][b]
            if travel is None:
                return data.time_capacity + 1
            return travel + (data.service_times[a] if include_service else 0)

        return callback

    for profile in data.matrices:
        time_callbacks[profile] = routing.RegisterTransitCallback(make_callback(profile, True))
        cost_callbacks[profile] = routing.RegisterTransitCallback(make_callback(profile, False))
    routing.AddDimensionWithVehicleTransits(
        [time_callbacks[p] for p in data.vehicle_profiles],
        data.slack_max,
        data.time_capacity,
        False,
        "Time",
    )
    dimension = routing.GetDimensionOrDie("Time")
    for v, profile in enumerate(data.vehicle_profiles):
        routing.SetArcCostEvaluatorOfVehicle(cost_callbacks[profile], v)
        a, b = data.vehicle_time_windows[v]
        dimension.CumulVar(routing.Start(v)).SetRange(a, b)
        dimension.CumulVar(routing.End(v)).SetRange(a, b)

    tasks = sorted(set(range(n)) - set(data.starts))
    for node in tasks:
        index = manager.NodeToIndex(node)
        dimension.CumulVar(index).SetRange(*data.time_windows[node])
        routing.AddDisjunction([index], data.penalties[node])
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
            status="INFEASIBLE" if status == 6 else "NOT_SOLVED",
            solver_status_code=status,
        )

    routes = []
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
            previous = node
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
    return SolveResponse(
        status="OPTIMAL" if status == 7 else "FEASIBLE",
        solver_status_code=status,
        routes=routes,
        dropped_nodes=dropped,
        total_cost=assignment.ObjectiveValue(),
        total_distance=sum(route.distance for route in routes),
    )

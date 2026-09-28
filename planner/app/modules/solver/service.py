"""Mixed-profile VRPTW with explicit eligibility and conservative time arithmetic.

The objective is the lexicographic policy of SolveRequest.objective_weights: every
weight exceeds the largest possible sum of all lower components, so the weighted
sum ranks schedules in policy order. The search is heuristic and time limited; a
FEASIBLE answer is the best schedule found, not a proven optimum.
"""

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.modules.solver.schemas import (
    ObjectiveComponents,
    Route,
    SolveRequest,
    SolveResponse,
    Step,
)


def solve(data: SolveRequest) -> SolveResponse:
    n = len(data.time_windows)
    manager = pywrapcp.RoutingIndexManager(n, data.num_vehicles, data.starts, data.ends)
    routing = pywrapcp.RoutingModel(manager)
    weights = data.objective_weights()
    time_callbacks = {}

    tasks = data.task_nodes()
    policies = dict(zip(tasks, data.ticket_policies, strict=True))

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
            cost = travel * weights.travel_minutes
            policy = policies.get(b)
            if (
                policy is not None
                and policy.previous_vehicle_id is not None
                and policy.previous_vehicle_id != vehicle_id
            ):
                cost += weights.reassigned_visits
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

    for v, profile in enumerate(data.vehicle_profiles):
        routing.SetArcCostEvaluatorOfVehicle(
            routing.RegisterTransitCallback(make_cost_callback(profile, v)), v
        )
        # Charged only when the route serves at least one visit.
        routing.SetFixedCostOfVehicle(weights.active_workers, v)
        a, b = data.vehicle_time_windows[v]
        dimension.CumulVar(routing.Start(v)).SetRange(a, b)
        dimension.CumulVar(routing.End(v)).SetRange(a, b)

    for node in tasks:
        index = manager.NodeToIndex(node)
        policy = policies[node]
        lower, upper = data.time_windows[node]
        lower = max(lower, policy.received_at)
        if policy.sla_deadline_at is not None:
            upper = min(upper, policy.sla_deadline_at - data.service_times[node])

        penalty = weights.unassigned_total
        if policy.category == "emergency":
            penalty += weights.unassigned_emergencies
        elif policy.category == "connection":
            penalty += weights.unassigned_connections

        routing.AddDisjunction([index], penalty)
        if lower > upper:
            routing.ActiveVar(index).SetValue(0)
        else:
            dimension.CumulVar(index).SetRange(lower, upper)

        if policy.category == "emergency":
            # Every minute between receipt and service start is response delay.
            dimension.SetCumulVarSoftUpperBound(
                index, policy.received_at, weights.emergency_response_minutes
            )

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
    response_minutes = active_workers = reassigned = 0

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

            policy = policies.get(node)
            if policy is not None:
                if policy.previous_vehicle_id not in (None, vehicle):
                    reassigned += 1
                if policy.category == "emergency":
                    response_minutes += arrival - policy.received_at

            previous = node

        if len(steps) > 2:
            active_workers += 1

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
    dropped_categories = [policies[node].category for node in dropped]
    components = ObjectiveComponents(
        unassigned_emergencies=dropped_categories.count("emergency"),
        emergency_response_minutes=response_minutes,
        unassigned_connections=dropped_categories.count("connection"),
        unassigned_total=len(dropped),
        active_workers=active_workers,
        travel_minutes=sum(route.travel_minutes for route in routes),
        reassigned_visits=reassigned,
    )
    if assignment.ObjectiveValue() != weights.cost(components):
        raise RuntimeError("Solver objective does not match its components")

    return SolveResponse(
        contract_version=2,
        status="OPTIMAL" if status == 7 else "FEASIBLE",
        solver_status_code=status,
        routes=routes,
        dropped_nodes=dropped,
        total_cost=assignment.ObjectiveValue(),
        total_distance=sum(route.distance for route in routes),
        objective_components=components,
        objective_weights=weights,
    )

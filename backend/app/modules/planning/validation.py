"""Independently validate every solver-selected transition before publishing a plan.

The objective breakdown is measured again from the checked routes; the solver's
components, weights and total cost must match it exactly.
"""

from app.modules.planning.errors import PlanningError
from app.modules.planning.solver_contract import ObjectiveComponents, SolveRequest, SolveResponse


def validate_solution(problem: SolveRequest, solution: SolveResponse) -> None:
    if solution.status not in ("FEASIBLE", "OPTIMAL"):
        raise PlanningError("planner_not_solved", 503, retryable=True)
    seen, vehicles = set(), set()
    # open_end: depots = starts ∪ ends; round-trip: starts == ends so union = starts
    depots = set(problem.starts) | set(problem.ends)
    tasks = set(range(len(problem.time_windows))) - depots
    ticket_policy_by_node = dict(zip(sorted(tasks), problem.ticket_policies, strict=True))
    response_minutes = active_workers = reassigned = 0
    try:
        for route in solution.routes:
            v = route.vehicle_id
            if v >= problem.num_vehicles or v in vehicles:
                raise ValueError
            vehicles.add(v)
            steps = route.steps
            if steps[0].node != problem.starts[v] or steps[-1].node != problem.ends[v]:
                raise ValueError
            if not (
                problem.vehicle_time_windows[v][0]
                <= steps[0].arrival_time
                <= steps[-1].arrival_time
                <= problem.vehicle_time_windows[v][1]
            ):
                raise ValueError
            matrix = problem.matrices[problem.vehicle_profiles[v]]
            distance = travel = service = waiting = 0
            for i, (a, b) in enumerate(zip(steps, steps[1:])):
                if a.node >= len(problem.time_windows) or b.node >= len(problem.time_windows):
                    raise ValueError
                minutes = matrix.time_minutes[a.node][b.node]
                meters = matrix.distance_meters[a.node][b.node]
                if minutes is None or meters is None:
                    raise ValueError
                gap = b.arrival_time - a.arrival_time - problem.service_times[a.node] - minutes
                if gap < 0 or gap > problem.slack_max:
                    raise ValueError
                travel += minutes
                service += problem.service_times[a.node]
                distance += meters
                waiting += gap
                if i < len(steps) - 2:
                    if b.node not in tasks or b.node in seen:
                        raise ValueError
                    seen.add(b.node)
                    start, end = problem.time_windows[b.node]
                    if (
                        not start <= b.arrival_time <= end
                        or v not in problem.allowed_vehicles[str(b.node)]
                    ):
                        raise ValueError
                    ticket_policy = ticket_policy_by_node[b.node]
                    if b.arrival_time < ticket_policy.received_at:
                        raise ValueError
                    if (
                        ticket_policy.sla_deadline_at is not None
                        and b.arrival_time + problem.service_times[b.node]
                        > ticket_policy.sla_deadline_at
                    ):
                        raise ValueError
                    if ticket_policy.category == "emergency":
                        response_minutes += b.arrival_time - ticket_policy.received_at
                    if ticket_policy.previous_vehicle_id not in (None, v):
                        reassigned += 1
            if (distance, travel, service, waiting) != (
                route.distance,
                route.travel_minutes,
                route.service_minutes,
                route.waiting_minutes,
            ):
                raise ValueError
            active_workers += len(steps) > 2
        dropped = set(solution.dropped_nodes)
        if len(dropped) != len(solution.dropped_nodes) or seen & dropped or seen | dropped != tasks:
            raise ValueError
        if solution.total_distance != sum(r.distance for r in solution.routes):
            raise ValueError
        categories = [ticket_policy_by_node[node].category for node in dropped]
        measured = ObjectiveComponents(
            unassigned_emergencies=categories.count("emergency"),
            emergency_response_minutes=response_minutes,
            unassigned_connections=categories.count("connection"),
            unassigned_total=len(dropped),
            active_workers=active_workers,
            travel_minutes=sum(r.travel_minutes for r in solution.routes),
            reassigned_visits=reassigned,
        )
        weights = problem.objective_weights()
        if (
            solution.objective_components != measured
            or solution.objective_weights != weights
            or solution.total_cost != weights.cost(measured)
        ):
            raise ValueError
    except (ValueError, IndexError, KeyError) as error:
        raise PlanningError("planner_invalid_response", 502) from error

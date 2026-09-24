"""Bounded checks in the solver's own time model; they explain a plan and never change it.

A visit that fails even as the only stop of an engineer cannot fit that engineer at all.
A missing insertion into the computed routes only means that no place was found there:
other permutations of the day are not searched, so it is reported as such.
"""

from datetime import datetime, timedelta

from app.modules.planning import reasons

ESTIMATE_CHECK_BUDGET = 50_000


def simulate(problem, vehicle, tasks):
    """Earliest schedule of tasks in this order; waiting is allowed exactly as in the solver."""
    matrix = problem.matrices[problem.vehicle_profiles[vehicle]].time_minutes
    moment, shift_end = problem.vehicle_time_windows[vehicle]
    previous, end, travel = problem.starts[vehicle], problem.ends[vehicle], 0
    for node in (*tasks, end):
        minutes = matrix[previous][node]
        if minutes is None:
            return {"kind": "unreachable", "source": previous, "target": node}
        moment += problem.service_times[previous] + minutes
        travel += minutes
        if node == end and moment > shift_end:
            return {"kind": "shift_end", "time": moment}
        if node != end:
            lower, upper = problem.time_windows[node]
            if moment > upper:
                return {"kind": "late", "time": moment}
            moment = max(moment, lower)
        previous = node
    return {"kind": "ok", "travel": travel}


def cheapest_insertion(problem, vehicle, tasks, node, budget=None):
    best = None
    for position in range(len(tasks) + 1):
        if budget is not None:
            if budget[0] <= 0:
                break
            budget[0] -= 1
        result = simulate(problem, vehicle, [*tasks[:position], node, *tasks[position:]])
        if result["kind"] == "ok" and (best is None or result["travel"] < best[1]):
            best = (position, result["travel"])
    return best


def single_visit_reason(problem, vehicle, node, failure, ticket, epoch):
    day = epoch.date()
    if failure["kind"] == "unreachable":
        profile = problem.vehicle_profiles[vehicle]
        source, target = failure["source"], failure["target"]
        reachable = sorted(
            p
            for p, matrix in problem.matrices.items()
            if p != profile and matrix.time_minutes[source][target] is not None
        )
        return reasons.unreachable(profile, reachable, ticket["location_id"])
    if failure["kind"] == "late":
        return reasons.arrival_after_window(
            epoch + timedelta(minutes=failure["time"]),
            datetime.fromisoformat(ticket["visit_window_end"]),
            day,
        )
    return reasons.return_after_shift(
        epoch + timedelta(minutes=failure["time"]),
        epoch + timedelta(minutes=problem.vehicle_time_windows[vehicle][1]),
        day,
    )


def planned_tasks(solution):
    return {
        route.vehicle_id: [step.node for step in route.steps[1:-1]] for route in solution.routes
    }


def diagnose_dropped(prepared, problem, nodes, solution):
    """Structured rejection of every dropped visit, with a reason for each engineer."""
    routes = planned_tasks(solution)
    workers, epoch = prepared["workers"], prepared["epoch"]
    limit = prepared["policy"].search_time_limit_seconds
    result = []
    for node in solution.dropped_nodes:
        ticket = nodes[node]["ticket"]
        candidates, slots, fitting = list(ticket["rejected"]), [], []
        for vehicle in problem.allowed_vehicles[str(node)]:
            worker_id = workers[vehicle]["user_id"]
            tasks = routes.get(vehicle, [])
            alone = simulate(problem, vehicle, [node])
            if alone["kind"] != "ok":
                reason = single_visit_reason(problem, vehicle, node, alone, ticket, epoch)
            else:
                fitting.append(worker_id)
                found = cheapest_insertion(problem, vehicle, tasks, node)
                if found is None:
                    reason = reasons.route_full(len(tasks))
                else:
                    slots.append(worker_id)
                    after = nodes[tasks[found[0] - 1]]["ticket"]["id"] if found[0] else None
                    reason = reasons.slot_available(found[0], after)
            candidates.append({"worker_id": worker_id, "reason": reason})
        candidates.sort(key=lambda c: c["worker_id"])
        if slots:
            primary = reasons.feasible_slot_missed(slots, limit)
        elif fitting:
            primary = reasons.no_slot_in_plan(fitting)
        else:
            primary = reasons.no_eligible_worker(candidates)
        result.append({"ticket_id": ticket["id"], "reason": primary, "candidates": candidates})
    return result


def fill_copy(problem, vehicle, pool, budget):
    """Greedy cheapest insertion of pool visits into an empty route of a copied engineer."""
    tasks, travel = [], 0
    while budget[0] > 0:
        choice = None
        for node in sorted(pool - set(tasks)):
            if vehicle not in problem.allowed_vehicles[str(node)]:
                continue
            found = cheapest_insertion(problem, vehicle, tasks, node, budget)
            if found and (choice is None or found[1] < choice[0]):
                choice = (found[1], node, found[0])
        if choice is None:
            break
        travel, node, position = choice
        tasks.insert(position, node)
    return tasks, travel


def estimate_resources(prepared, problem, nodes, dropped):
    """What-if with copies of real engineers: same skills, office, shift and transport."""
    ids = {r["ticket_id"] for r in dropped if r["reason"]["code"] == "no_slot_in_computed_plan"}
    pending = {n for n, node in enumerate(nodes) if node.get("ticket", {}).get("id") in ids}
    if not pending:
        return None
    workers = prepared["workers"]
    templates = {}
    usable = {v for n in pending for v in problem.allowed_vehicles[str(n)]}
    for vehicle in sorted(usable, key=lambda v: workers[v]["user_id"]):
        # Engineers equal in every planning attribute produce identical copies.
        w = workers[vehicle]
        key = (
            w["profile"],
            w["office_id"],
            w["location_id"],
            tuple(w["window"]),
            frozenset(w["skill_ids"]),
        )
        templates.setdefault(key, vehicle)
    budget, remaining, added = [ESTIMATE_CHECK_BUDGET], set(pending), []
    while remaining and budget[0] > 0:
        best = None
        for vehicle in templates.values():
            tasks, travel = fill_copy(problem, vehicle, remaining, budget)
            if tasks and (best is None or (-len(tasks), travel) < (-len(best[1]), best[2])):
                best = (vehicle, tasks, travel)
        if best is None:
            break
        added.append(best)
        remaining -= set(best[1])
    complete = budget[0] > 0 or not remaining

    def ticket_ids(values):
        return sorted(nodes[n]["ticket"]["id"] for n in values)

    covered = ticket_ids(pending - remaining)
    extra = [
        {
            "like_worker_id": workers[vehicle]["user_id"],
            "ticket_ids": ticket_ids(tasks),
            "travel_minutes": travel,
        }
        for vehicle, tasks, travel in added
    ]
    return {
        "is_estimate": True,
        "method": "greedy_insertion_with_worker_copies",
        "complete": complete,
        "message": reasons.resource_message(extra, len(covered), len(pending), complete),
        "additional_workers": len(extra),
        "considered_ticket_ids": ticket_ids(pending),
        "covered_ticket_ids": covered,
        "uncovered_ticket_ids": ticket_ids(remaining),
        "workers": extra,
    }


def visit_factors(prepared, routes):
    """Attach the checked facts to each planned visit, without claiming a unique best engineer."""
    tickets = {t["id"]: t for t in prepared["tickets"]}
    policy, day = prepared["policy"], prepared["epoch"].date()
    for route in routes:
        previous_end = datetime.fromisoformat(route["departure_at"])
        for index, visit in enumerate(route["stops"]):
            ticket = tickets[visit["ticket_id"]]
            arrival = datetime.fromisoformat(visit["arrival_at"])
            start = datetime.fromisoformat(visit["service_start_at"])
            visit["factors"] = [
                reasons.skills_factor(ticket["required_skill_ids"]),
                reasons.transport_factor(
                    route["transport_type"],
                    route["routing_mode"],
                    round((arrival - previous_end).total_seconds() / 60),
                    index == 0,
                ),
                reasons.window_factor(
                    start,
                    datetime.fromisoformat(ticket["visit_window_start"]),
                    datetime.fromisoformat(ticket["visit_window_end"]),
                    visit["waiting_minutes"],
                    day,
                ),
                reasons.equipment_factor(ticket["allocations"], prepared["appliance_names"]),
                reasons.priority_factor(policy.priority),
                reasons.selection_factor(len(ticket["allowed"]), policy.objective_order),
            ]
            previous_end = datetime.fromisoformat(visit["service_end_at"])


def plan_metrics(request, prepared, routes, unassigned):
    by_category = {}
    for item in unassigned:
        category = item["reason"]["category"]
        by_category[category] = by_category.get(category, 0) + 1
    return {
        "requested_tickets": len(request.ticket_ids),
        "eligible_tickets": len(prepared["tickets"]),
        "assigned_tickets": sum(len(r["stops"]) for r in routes),
        "unassigned_tickets": len(unassigned),
        "requested_workers": len(request.worker_ids),
        "available_workers": len(prepared["workers"]),
        "used_workers": len(routes),
        "distance_meters": sum(r["distance_meters"] for r in routes),
        "travel_minutes": sum(r["travel_minutes"] for r in routes),
        "service_minutes": sum(r["service_minutes"] for r in routes),
        "waiting_minutes": sum(r["waiting_minutes"] for r in routes),
        "unassigned_by_category": dict(sorted(by_category.items())),
    }


def outcome(routes, unassigned):
    if not routes:
        return "empty"
    return "partial" if unassigned else "complete"

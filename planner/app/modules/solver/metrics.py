from collections import defaultdict
from typing import Any

from app.modules.solver.schemas import SolveRequest, SolveResponse

def calculate_metrics(request: SolveRequest, response: SolveResponse) -> dict[str, Any]:
    tasks = sorted(set(range(len(request.time_windows))) - (set(request.starts) | set(request.ends)))
    
    # Input tasks by category
    input_by_category = defaultdict(int)
    eligible_by_category = defaultdict(int)
    
    for i, node in enumerate(tasks):
        cat = request.ticket_policies[i].category
        input_by_category[cat] += 1
        if request.allowed_vehicles.get(str(node)):
            eligible_by_category[cat] += 1
            
    # Assigned and unassigned
    assigned_nodes = set()
    for route in response.routes:
        for step in route.steps[1:-1]:
            assigned_nodes.add(step.node)
            
    assigned_by_category = defaultdict(int)
    unassigned_by_category = defaultdict(int)
    
    for i, node in enumerate(tasks):
        cat = request.ticket_policies[i].category
        if node in assigned_nodes:
            assigned_by_category[cat] += 1
        else:
            unassigned_by_category[cat] += 1
            
    distances = [route.distance for route in response.routes]
    
    travel_time = sum(r.travel_minutes for r in response.routes)
    service_time = sum(r.service_minutes for r in response.routes)
    waiting_time = sum(r.waiting_minutes for r in response.routes)
    
    # Delays and SLA
    emergency_delays = 0
    sla_violations = 0
    
    for route in response.routes:
        for step in route.steps[1:-1]:
            node = step.node
            policy = request.ticket_policies[tasks.index(node)]
            if policy.category == "emergency":
                delay = max(0, step.arrival_time - policy.received_at)
                emergency_delays += delay
            
            if policy.sla_deadline_at is not None:
                completion_time = step.arrival_time + request.service_times[node]
                if completion_time > policy.sla_deadline_at:
                    sla_violations += 1
                    
    return {
        "input_tasks": dict(input_by_category),
        "eligible_tasks": dict(eligible_by_category),
        "assigned_tasks": dict(assigned_by_category),
        "unassigned_tasks": dict(unassigned_by_category),
        "active_vehicles": len([r for r in response.routes if len(r.steps) > 2]),
        "distances": distances,
        "total_distance": sum(distances),
        "travel_minutes": travel_time,
        "service_minutes": service_time,
        "waiting_minutes": waiting_time,
        "emergency_delays": emergency_delays,
        "sla_violations": sla_violations,
    }

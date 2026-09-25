"""Small deterministic problems, independent of database IDs."""


def problem(n=4, vehicles=1, horizon=100):
    matrix = [[0 if i == j else 5 for j in range(n)] for i in range(n)]
    return {
        "contract_version": 2,
        "num_vehicles": vehicles,
        "starts": list(range(vehicles)),
        "ends": list(range(vehicles)),
        "vehicle_profiles": ["drive"] * vehicles,
        "vehicle_time_windows": [[0, horizon]] * vehicles,
        "matrices": {
            "drive": {
                "time_minutes": matrix,
                "distance_meters": [[v * 100 for v in row] for row in matrix],
            }
        },
        "time_windows": [[0, horizon]] * n,
        "service_times": [0] * vehicles + [10] * (n - vehicles),
        "allowed_vehicles": {str(i): list(range(vehicles)) for i in range(vehicles, n)},
        "penalties": [0] * vehicles + [vehicles * horizon + 1] * (n - vehicles),
        "ticket_policies": [
            {
                "ticket_id": 100 + node,
                "category": "emergency" if node == vehicles else "repair",
                "priority": 1 if node == vehicles else 3,
                "received_at": 0,
                "sla_deadline_at": None,
            }
            for node in range(vehicles, n)
        ],
        "time_capacity": horizon,
        "slack_max": horizon,
        "vehicle_fixed_cost": 0,
        "search_time_limit_s": 1,
    }

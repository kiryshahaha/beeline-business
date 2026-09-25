"""Deterministic domain fixtures shared by database tests, Bruno and file generation."""

from datetime import UTC, date, datetime, time, timedelta

from generate_synthetic import TZ, generate_dataset

ROUTE_DATE = date(2030, 1, 15)
NOW = datetime(2030, 1, 14, tzinfo=UTC)
SCENARIOS = ("mixed", "duplicate_coordinates", "night", "rejections", "overload", "volume")


def generate_planning_dataset(scenario="mixed", *, seed=1900):
    if scenario not in SCENARIOS:
        raise ValueError("Unknown planning scenario")
    count = 50 if scenario in ("overload", "volume") else 24
    workers = 20 if scenario == "volume" else 4
    data = generate_dataset(
        seed=seed, start_date=ROUTE_DATE, tickets=count, workers=workers, days=1
    )
    # A day plan belongs to one district. Keep the fixture geographically rich
    # while placing every location and office in district 1.
    for building in data["buildings"]:
        building.update(city_id=1, district_id=1, street_id=1)
    for brigade in data["brigades"]:
        brigade["division_id"] = 1
    for skill in data["worker_skills"]:
        skill["skill"] += f" [planning {seed}]"
    for name in (
        "ticket_comments",
        "notification_events",
        "routes",
        # Equipment on hand and source provenance belong to the generic package only.
        "office_kit_reserves",
        "worker_appliances",
        "appliance_movements",
        "ticket_appliance_states",
        "appliance_operations",
        "source_records",
        "source_addresses",
        "source_imports",
    ):
        data[name] = []
    night = scenario == "night"
    for worker in data["workers"]:
        worker["workshift_start"] = time(22 if night else 8)
        worker["workshift_end"] = time(6 if night else 18)
        worker["service_area_id"] = 1
    for location in data["locations"]:
        index = 0 if scenario == "duplicate_coordinates" else location["id"]
        location.update(
            latitude=round(55.75 + index * 0.0001, 6), longitude=round(37.61 + index * 0.0001, 6)
        )
    data["worker_skill_assignments"] = [
        {"worker_id": w["user_id"], "skill_id": s["id"]}
        for w in data["workers"]
        for s in data["worker_skills"]
    ]
    types = data["work_types"]
    members = {m["worker_id"]: m["brigade_id"] for m in data["brigade_members"]}
    data["ticket_appliances"] = []
    start = datetime.combine(ROUTE_DATE, time(22 if night else 8), TZ)
    end = start + timedelta(hours=8 if night else 10)
    for i, ticket in enumerate(data["tickets"]):
        work_type = types[i % len(types)]
        worker = data["workers"][i % workers]
        ticket.update(
            service_area_id=1,
            status="planned",
            lifecycle_state="waiting_assignment",
            revision=1,
            execution_cycle=1,
            actual_started_at=None,
            actual_completed_at=None,
            cancel_reason=None,
            last_event_id=None,
            assigned_worker_id=None,
            work_type=work_type["name"],
            work_type_id=work_type["id"],
            category=work_type.get("category", "repair"),
            priority=work_type.get("default_priority", 3),
            received_at=start - timedelta(hours=1),
            sla_deadline_at=None,
            required_transport_type=None,
            title=f"[planning:{scenario}] {i + 1}",
            visit_window_start=start,
            visit_window_end=end,
            estimated_duration_minutes=90 if scenario == "overload" else 20,
            actual_duration_minutes=None,
            planned_start_at=None,
            planned_end_at=None,
        )
        data["ticket_appliances"].append(
            {
                "ticket_id": ticket["id"],
                "appliance_id": work_type["id"],
                "office_id": members[worker["user_id"]],
                "quantity": 1,
                "created_at": NOW,
            }
        )
    if scenario == "rejections":
        data["tickets"][0]["status"] = "completed"
        data["tickets"][1]["work_type_id"] = None
        data["tickets"][1]["work_type"] = "Unconfigured fictional work"
        data["ticket_appliances"] = [a for a in data["ticket_appliances"] if a["ticket_id"] != 3]
        data["tickets"][3]["visit_window_start"] = start + timedelta(hours=20)
        data["tickets"][3]["visit_window_end"] = start + timedelta(hours=22)
    return data


def preview_request(receipt, data):
    ids = receipt["id_map"]
    return {
        "route_date": ROUTE_DATE.isoformat(),
        "allow_partial": True,
        "ticket_ids": [ids["tickets"][str(t["id"])] for t in data["tickets"]],
        "worker_ids": [ids["workers"][str(w["user_id"])] for w in data["workers"]],
    }

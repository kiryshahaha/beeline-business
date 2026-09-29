"""Deterministic domain fixtures shared by database tests, Bruno and file generation.

Each scenario is one day of the «Восток» area on real Moscow addresses (see
generate_synthetic.py): six brigades, each serving its own districts, and engineers who
can do every work type of the case, so only the scenario itself limits the plan.
"""

from datetime import UTC, date, datetime, time, timedelta

from generate_synthetic import DAY_12, Layout, Shift, generate_package

ROUTE_DATE = date(2030, 1, 15)
NOW = datetime(2030, 1, 14, tzinfo=UTC)
SCENARIOS = ("mixed", "duplicate_coordinates", "night", "rejections", "overload", "volume")
AREA = ("vostok",)
NIGHT_8 = Shift(time(22), time(6), "2/2", night=True)
DAY_8 = Shift(time(10), time(18), "5/2")
LAYOUTS = {
    # Two-hour windows in turn: every engineer can serve all of his visits.
    "mixed": Layout(by_worker=True, slots=True, shift=DAY_12, scenarios=False),
    # Neighbours of one entrance after a building-wide outage: identical coordinates,
    # every client at home for the whole day.
    "duplicate_coordinates": Layout(
        by_worker=True,
        categories=("repair", "connection", "additional", "repair"),
        window=(time(10), time(22)),
        shift=DAY_12,
        one_entrance=True,
        scenarios=False,
    ),
    # A night duty 22:00-06:00 answering outages reported during the night.
    "night": Layout(
        by_worker=True,
        categories=("emergency",),
        window=(time(22), time(6)),
        shift=NIGHT_8,
        scenarios=False,
    ),
    "rejections": Layout(by_worker=True, slots=True, shift=DAY_12, scenarios=False),
    # Fifty connections for four engineers: the day cannot hold them all.
    "overload": Layout(
        by_worker=True,
        categories=("connection",),
        window=(time(10), time(18)),
        shift=DAY_8,
        scenarios=False,
    ),
    "volume": Layout(by_worker=True, slots=True, shift=DAY_12, scenarios=False),
}
UNCONFIGURED_WORK = "Монтаж видеодомофона"


def generate_planning_dataset(scenario="mixed", *, seed=1900):
    if scenario not in SCENARIOS:
        raise ValueError("Unknown planning scenario")
    count = 50 if scenario in ("overload", "volume") else 24
    workers = 20 if scenario == "volume" else 4
    data = generate_package(
        seed=seed,
        start_date=ROUTE_DATE,
        tickets=count,
        workers=workers,
        days=1,
        area_codes=AREA,
        layout=LAYOUTS[scenario],
    ).tables
    # The kit of a fixture engineer is exactly his requests: no spare-consumables norm.
    data["office_kit_reserves"] = []
    # A fixture engineer may take any visit of his brigade: skills never limit the plan.
    skill_ids = {row["skill"]: row["id"] for row in data["worker_skills"]}
    case_skills = {
        skill_ids[name]
        for name in ("Локальные работы", "Работы на подключение и дозаказы", "Аварийные работы")
    }
    have = {(row["worker_id"], row["skill_id"]) for row in data["worker_skill_assignments"]}
    for worker in data["workers"]:
        for skill_id in sorted(case_skills):
            if (worker["user_id"], skill_id) not in have:
                data["worker_skill_assignments"].append(
                    {"worker_id": worker["user_id"], "skill_id": skill_id}
                )
    data["worker_skill_assignments"].sort(key=lambda row: (row["worker_id"], row["skill_id"]))
    if scenario == "night":
        for ticket in data["tickets"]:
            ticket["received_at"] = ticket["visit_window_start"]
            ticket["sla_deadline_at"] = ticket["received_at"] + timedelta(hours=24)
            ticket["response_deadline_at"] = ticket["received_at"] + timedelta(hours=2)
    if scenario == "rejections":
        tickets = data["tickets"]
        tickets[0].update(
            status="completed",
            lifecycle_state="completed",
            assigned_worker_id=None,
        )
        tickets[1].update(
            work_type_id=None,
            work_type=UNCONFIGURED_WORK,
            title="Установка видеодомофона в квартире",
            description="Клиент просит установить видеодомофон и провести кабель от двери.",
            request_type_hd="Работа с кабелем",
        )
        # The first connection of the day has no router reserved for it.
        connection = next(t for t in tickets[2:] if t["category"] == "connection")
        required = {row["appliance_id"] for row in data["work_type_required_appliances"]}
        data["ticket_appliances"] = [
            row
            for row in data["ticket_appliances"]
            if not (row["ticket_id"] == connection["id"] and row["appliance_id"] in required)
        ]
        late = next(
            t for t in tickets[2:] if t["id"] != connection["id"] and t["category"] != "emergency"
        )
        late["visit_window_start"] += timedelta(hours=20)
        late["visit_window_end"] += timedelta(hours=20)
    return data


def preview_request(receipt, data):
    ids = receipt["id_map"]
    return {
        "route_date": ROUTE_DATE.isoformat(),
        "allow_partial": True,
        "ticket_ids": [ids["tickets"][str(t["id"])] for t in data["tickets"]],
        "worker_ids": [ids["workers"][str(w["user_id"])] for w in data["workers"]],
    }

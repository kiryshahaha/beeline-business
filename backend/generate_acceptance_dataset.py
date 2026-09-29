"""Generate the fixed, fictional Plan 5 acceptance input package."""

import argparse
import copy
import csv
import hashlib
import io
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

from app.modules.data_exchange.formats import json_default, parse_file, serialize
from app.modules.data_exchange.registry import FORMAT_VERSION
from app.modules.routing.schemas import RouteGeoJSON
from generate_synthetic import TZ, generate_dataset

SEED = 5025
DATE = date(2030, 1, 15)
TIMEZONE = "Europe/Moscow"
CITIES = ("Москва", "Домодедово", "Кашира", "Подольск")
ZONE_NAMES = ("moscow_a", "remote_a", "moscow_b", "remote_b", "moscow_c", "remote_c")
CITY_POINTS = {
    1: (55.7500, 37.6100),
    2: (55.4400, 37.7700),
    3: (54.8400, 38.1500),
    4: (55.4300, 37.5500),
}


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime.combine(DATE, time(hour, minute), TZ)


def _area(index: int) -> int:
    return 101 + index // 4


def _geojson(worker_id: int, tickets: list[dict], locations: dict[int, dict]) -> dict:
    features = []
    points = []
    for sequence, ticket in enumerate(tickets, 1):
        location = locations[ticket["location_id"]]
        point = [location["longitude"], location["latitude"]]
        points.append(point)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": point},
                "properties": {
                    "location_id": ticket["location_id"],
                    "ticket_id": ticket["id"],
                    "sequence": sequence,
                    "arrival_at": ticket["planned_start_at"].isoformat(),
                    "service_start_at": ticket["planned_start_at"].isoformat(),
                    "service_end_at": ticket["planned_end_at"].isoformat(),
                    "waiting_minutes": 0,
                    "effective_service_minutes": 30,
                    "duration_source": "ticket_estimate",
                },
            }
        )
    features.append(
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": points},
            "properties": {"kind": "path", "source": "straight_lines"},
        }
    )
    return RouteGeoJSON.model_validate(
        {
            "type": "FeatureCollection",
            "properties": {
                "worker_id": worker_id,
                "route_date": DATE.isoformat(),
                "route_number": 1,
            },
            "features": features,
        }
    ).model_dump(mode="json")


def build_dataset() -> tuple[dict, dict]:
    """Return importable rows and the separate event/roster scenario contract."""
    tables = generate_dataset(seed=SEED, start_date=DATE, tickets=48, workers=13, days=1)
    tables["cities"] = tables["cities"][:1] + [
        {"id": index, "name": name} for index, name in enumerate(CITIES[1:], 2)
    ]
    tables["cities"][0]["name"] = CITIES[0]
    tables["service_areas"] = tables["service_areas"][:3]
    for index, area in enumerate(tables["service_areas"]):
        area.update(code=f"acceptance_{index + 1}", name=f"Тестовый участок {index + 1}")
    for district in tables["districts"]:
        local = (district["id"] - 1) % 4
        region = (district["id"] - 1) // 4
        district["city_id"] = 1 if local < 2 else region + 2
        district["name"] = f"Участок {region + 1}, зона {local + 1}"
    for street in tables["streets"]:
        district = tables["districts"][street["id"] - 1]
        street["city_id"] = district["city_id"]
    for division in tables["divisions"]:
        division["service_area_id"] = _area(division["id"] - 1)
    for building in tables["buildings"]:
        district = tables["districts"][building["street_id"] - 1]
        building["city_id"] = district["city_id"]
        building["service_area_id"] = _area(district["id"] - 1)
    for location in tables["locations"]:
        building = tables["buildings"][location["building_id"] - 1]
        latitude, longitude = CITY_POINTS[building["city_id"]]
        offset = (location["id"] % 7) * 0.0001
        location.update(
            latitude=round(latitude + offset, 6), longitude=round(longitude + offset, 6)
        )
    tables["offices"] = tables["offices"][:3]
    tables["appliance_stocks"] = [
        row for row in tables["appliance_stocks"] if row["office_id"] <= 3
    ]
    for index, office in enumerate(tables["offices"]):
        office["location_id"] = index * 4 + 1
        office["service_area_id"] = 101 + index
    for index, brigade in enumerate(tables["brigades"]):
        brigade["division_id"] = (index // 2) * 4 + (1 if index % 2 == 0 else 3)
        brigade["office_id"] = index // 2 + 1
    for index, worker in enumerate(tables["workers"]):
        region = min(index // 4, 2)
        worker.update(
            service_area_id=101 + region,
            workshift_start=time(8),
            workshift_end=time(16 if index % 2 else 20),
        )
    for index, member in enumerate(tables["brigade_members"]):
        region = min(index // 4, 2)
        member["brigade_id"] = region * 2 + index % 2 + 1
    member_brigade = {row["worker_id"]: row["brigade_id"] for row in tables["brigade_members"]}
    tables["work_types"][2]["category"] = "emergency"
    locations = {row["id"]: row for row in tables["locations"]}
    area_locations = defaultdict(list)
    for location in tables["locations"]:
        building = tables["buildings"][location["building_id"] - 1]
        area_locations[building["service_area_id"]].append(location["id"])
    assigned = defaultdict(list)
    ticket_cases = []
    for index, ticket in enumerate(tables["tickets"]):
        region = index % 3
        phase = "planned" if index < 36 else "new"
        category = "emergency" if phase == "new" and (index - 36) // 3 >= 2 else "repair"
        # New events 37-42 are ordinary, 43-48 are emergencies.
        worker_id = 9 + region * 4 + (index // 3) % 4 if phase == "planned" else None
        location_id = area_locations[101 + region][(index // 3) % 8]
        if ticket["id"] == 37:
            # Put the new ticket on a Moscow address near the neighboring area's route.
            location_id = area_locations[101][1]
        elif ticket["id"] == 38:
            # This ticket exercises a remote city that still belongs to area 102.
            location_id = next(
                location_id
                for location_id in area_locations[102]
                if tables["buildings"][locations[location_id]["building_id"] - 1]["city_id"] != 1
            )
        hour = (9, 11, 14)[(index // 12) % 3] if phase == "planned" else 10 + (index - 36) // 3
        start = _at(hour)
        received = _at(8) if phase == "planned" else start - timedelta(minutes=20)
        if index == 36:
            received = _at(8, 10)
        if index == 41:
            received = _at(8, 12)
        work_type_id = 3 if category == "emergency" else 1
        ticket.update(
            location_id=location_id,
            service_area_id=101 + region,
            brigade_id=member_brigade[worker_id] if worker_id else region * 2 + 1,
            title=f"[Приёмка {phase}] Заявка {index + 1}",
            work_type_id=work_type_id,
            work_type=tables["work_types"][work_type_id - 1]["name"],
            category=category,
            priority=1 if category == "emergency" else 3,
            request_type_hd="Авария" if category == "emergency" else "Ремонт",
            received_at=received,
            response_deadline_at=(received + timedelta(minutes=60 if index % 2 else 120))
            if category == "emergency"
            else None,
            status="planned",
            lifecycle_state="assigned" if phase == "planned" else "waiting_assignment",
            assigned_worker_id=worker_id,
            visit_window_start=start,
            visit_window_end=start
            + timedelta(minutes=15 if index == 41 else 90 if category == "emergency" else 180),
            estimated_duration_minutes=30,
            actual_duration_minutes=None,
            actual_started_at=None,
            actual_completed_at=None,
            planned_start_at=start if phase == "planned" else None,
            planned_end_at=start + timedelta(minutes=30) if phase == "planned" else None,
            cancel_reason=None,
        )
        if ticket["id"] == 43:
            ticket["visit_window_start"] = _at(10)
            ticket["visit_window_end"] = _at(12)
        elif ticket["id"] == 45:
            ticket["visit_window_start"] = _at(12)
            ticket["visit_window_end"] = _at(14)
        if worker_id:
            assigned[worker_id].append(ticket)
        ticket_cases.append(
            {
                "ticket_id": ticket["id"],
                "phase": phase,
                "category": category,
                "service_area_id": ticket["service_area_id"],
                "received_at": received.isoformat(),
                "visit_window_start": ticket["visit_window_start"].isoformat(),
                "visit_window_end": ticket["visit_window_end"].isoformat(),
                "expected_worker_id": worker_id,
            }
        )
    allocation_template = tables["ticket_appliances"][0]
    tables["ticket_appliances"] = []
    for ticket in tables["tickets"]:
        allocation = copy.copy(allocation_template)
        allocation.update(
            ticket_id=ticket["id"],
            appliance_id=ticket["work_type_id"],
            office_id=ticket["service_area_id"] - 100,
            quantity=1,
        )
        tables["ticket_appliances"].append(allocation)
    # The generic package has a test issue of appliance 2 to ticket 1.
    for table_name in ("worker_appliances", "appliance_movements", "ticket_appliance_states"):
        for row in tables[table_name]:
            row["appliance_id"] = 1
            if "quantity" in row:
                row["quantity"] = 1
    route_template = copy.copy(tables["routes"][0])
    tables["routes"] = []
    for worker_id in range(9, 21):
        tickets = sorted(assigned[worker_id], key=lambda ticket: ticket["planned_start_at"])
        tables["routes"].append(
            {
                **route_template,
                "id": worker_id - 8,
                "worker_id": worker_id,
                "route_date": DATE,
                "route_number": 1,
                "geojson": _geojson(worker_id, tickets, locations),
            }
        )
    revision_template = copy.copy(tables["day_plan_revisions"][0])
    tables["day_plan_revisions"] = []
    for region in range(3):
        area_id = 101 + region
        workers = tables["workers"][region * 4 : region * 4 + 4]
        roster = [
            {
                "worker_id": worker["user_id"],
                "service_area_id": area_id,
                "workshift_start": worker["workshift_start"].isoformat(),
                "workshift_end": worker["workshift_end"].isoformat(),
                "source": "published",
            }
            for worker in workers
        ]
        visits = []
        for worker in workers:
            for sequence, ticket in enumerate(
                sorted(assigned[worker["user_id"]], key=lambda t: t["planned_start_at"]), 1
            ):
                visits.append(
                    {
                        "ticket_id": ticket["id"],
                        "worker_id": worker["user_id"],
                        "route_id": worker["user_id"] - 8,
                        "sequence": sequence,
                        "arrival_at": ticket["planned_start_at"].isoformat(),
                        "service_start_at": ticket["planned_start_at"].isoformat(),
                        "service_end_at": ticket["planned_end_at"].isoformat(),
                    }
                )
        tables["day_plan_revisions"].append(
            {
                **revision_template,
                "id": region + 1,
                "service_area_id": area_id,
                "route_date": DATE,
                "event_id": None,
                "roster": roster,
                "fingerprint": hashlib.sha256(f"acceptance-{SEED}-{area_id}".encode()).hexdigest(),
                "plan_state": {
                    "route_date": DATE.isoformat(),
                    "plan_id": None,
                    "outcome": "complete",
                    "visits": sorted(visits, key=lambda v: v["ticket_id"]),
                    "unassigned_ticket_ids": [],
                    "metrics": {
                        "assigned_tickets": len(visits),
                        "unassigned_tickets": 0,
                        "used_workers": len(workers),
                    },
                },
            }
        )
    event_template = copy.copy(tables["work_events"][0])
    tables["work_events"] = []
    for event_index, ticket in enumerate(tables["tickets"][36:], 1):
        tables["work_events"].append(
            {
                **event_template,
                "id": event_index,
                "ticket_id": ticket["id"],
                "worker_id": None,
                "service_area_id": ticket["service_area_id"],
                "route_date": DATE,
                "occurred_at": ticket["received_at"],
                "recorded_at": ticket["received_at"],
                "before_revision": None,
                "after_revision": 1,
                "idempotency_key": f"acceptance-{SEED}-{event_index}",
                "payload": {"ticket_id": ticket["id"], "source": "synthetic_acceptance"},
            }
        )
    # The generic consumption example referenced the original first event.
    tables["equipment_movements"] = []
    scenarios = {
        "schema_version": 1,
        "seed": SEED,
        "timezone": TIMEZONE,
        "route_date": DATE.isoformat(),
        "roster_worker_ids": list(range(9, 21)),
        "outside_roster_worker_id": 21,
        "territory_cases": {
            "nearby_cross_area_ticket_id": 37,
            "nearby_reference_ticket_id": 2,
            "nearby_worker_id": 13,
            "same_area_remote_ticket_id": 38,
        },
        "window_cases": {"no_slot_ticket_id": 43, "later_window_ticket_id": 45},
        "tickets": ticket_cases,
        "events": [
            {
                "event_id": row["id"],
                "ticket_id": row["ticket_id"],
                "received_at": row["occurred_at"].isoformat(),
                "category": tables["tickets"][row["ticket_id"] - 1]["category"],
            }
            for row in tables["work_events"]
        ],
        "notes": "Маршруты — синтетические снимки; результаты событий требуют прогона.",
    }
    return tables, scenarios


def road_matrix() -> dict:
    travel = {}
    distance = {}
    for source_index, source in enumerate(ZONE_NAMES):
        travel[source] = {}
        distance[source] = {}
        for target_index, target in enumerate(ZONE_NAMES):
            minutes = (
                0
                if source_index == target_index
                else 8
                + abs(source_index - target_index) * 11
                + (source_index * 3 + target_index) % 7
            )
            travel[source][target] = minutes
            distance[source][target] = minutes * 480
    return {
        "schema_version": 1,
        "source": "deterministic_stub",
        "seed": SEED,
        "timezone": TIMEZONE,
        "route_date": DATE.isoformat(),
        "zones": list(ZONE_NAMES),
        "travel_minutes": travel,
        "distance_meters": distance,
        "peak_profile": {
            "09:00-11:00": {"duration_multiplier": 1.3},
            "16:00-19:00": {"duration_multiplier": 1.5},
        },
        "note": "This directed synthetic matrix is not Geoapify output or a native planner result.",
    }


def write_package(output: Path) -> dict:
    tables, scenarios = build_dataset()
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    canonical = None
    for format_name, extension in (("csv", "zip"), ("xlsx", "xlsx")):
        name = f"dataset.{extension}"
        content = serialize(tables, format_name)
        parsed = parse_file(content, name)
        if canonical is not None and parsed != canonical:
            raise AssertionError("Acceptance CSV/XLSX data differ")
        canonical = parsed
        (output / name).write_bytes(content)
        files[name] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            "rows": {table: len(rows) for table, rows in parsed.items()},
        }
    auxiliaries = {
        "scenarios.json": json.dumps(scenarios, ensure_ascii=False, indent=2) + "\n",
        "road_matrix.json": json.dumps(road_matrix(), ensure_ascii=False, indent=2) + "\n",
    }
    negative = io.StringIO()
    writer = csv.writer(negative, lineterminator="\n")
    writer.writerow(("case_id", "request_type_hd", "category", "strict", "expected"))
    writer.writerows(
        (
            ("empty_hd", "", "repair", "false", "repair"),
            ("unknown_default", "Неизвестный тип", "repair", "false", "repair"),
            ("unknown_strict", "Неизвестный тип", "repair", "true", "unknown_hd_type"),
            ("conflicting_hd", "Авария", "repair", "false", "category_classification_conflict"),
            (
                "unknown_emergency",
                "Неизвестный тип",
                "emergency",
                "false",
                "category_classification_conflict",
            ),
        )
    )
    auxiliaries["negative_tickets.csv"] = negative.getvalue()
    auxiliary_files = {}
    for name, content in auxiliaries.items():
        encoded = content.encode("utf-8")
        (output / name).write_bytes(encoded)
        auxiliary_files[name] = {
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "bytes": len(encoded),
        }
    manifest = {
        "schema_version": FORMAT_VERSION,
        "generator": "backend/generate_acceptance_dataset.py",
        "generator_version": 1,
        "seed": SEED,
        "timezone": TIMEZONE,
        "route_date": DATE.isoformat(),
        "counts": {name: len(rows) for name, rows in tables.items()},
        "expected_initial_assignments": {
            str(ticket["id"]): ticket["assigned_worker_id"]
            for ticket in tables["tickets"]
            if ticket["assigned_worker_id"] is not None
        },
        "road_matrix_source": "deterministic_stub",
        "files": files,
        "auxiliary_files": auxiliary_files,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=json_default) + "\n",
        encoding="utf-8",
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("../data/synthetic/acceptance"))
    args = parser.parse_args()
    result = write_package(args.output)
    print(json.dumps({"seed": result["seed"], "counts": result["counts"]}, ensure_ascii=False))

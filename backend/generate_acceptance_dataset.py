"""Generate the fixed Plan 5 acceptance package on real Moscow and Moscow-region addresses.

Three areas of the case with two brigades each, twelve engineers of the day roster and one
engineer outside it, 36 requests known in the morning and 12 arriving during the day
(six outages at house nodes and six ordinary requests). As in the organizer's files, the
«Юго-восток» area also serves Домодедово, Ступино and Кашира; the other two areas are
Moscow only. The package has no routes and no published day plan: the acceptance run
builds the first plan with the native planner.
"""

import argparse
import csv
import hashlib
import io
import json
import math
from datetime import date, datetime, time, timedelta
from pathlib import Path

from app.modules.data_exchange.formats import json_default, parse_file, serialize
from app.modules.data_exchange.registry import FORMAT_VERSION
from generate_synthetic import (
    DAY_12,
    FOREMEN,
    OBSERVERS,
    TZ,
    Generator,
    Shift,
)
from synthetic_moscow.catalog import REQUEST_KINDS, WORK_TYPE_BY_CODE
from synthetic_moscow.geography import AREAS, REMOTE_TOWNS, district_buildings

SEED = 5025
DATE = date(2030, 1, 15)
TIMEZONE = "Europe/Moscow"
# The acceptance clock is 08:20 and a first plan covers shifts that have not begun yet.
EARLY_8 = Shift(time(9), time(17), "5/2")
LATE_8 = Shift(time(12), time(20), "5/2")
FULL_12 = Shift(time(9), time(21), "2/2")
# Brigade -> districts next to the borders of the areas, so neighbouring addresses of
# different areas meet and distance never hides the area rule.
BORDER_DISTRICTS = {
    1: ("Южнопортовый",),
    2: ("Текстильщики",),
    3: ("Москворечье-Сабурово", "Царицыно"),
    4: ("Орехово-Борисово Северное",),
    5: ("Нагатинский Затон", "Нагатино-Садовники"),
    6: ("Нагорный",),
}
# Engineer id -> (brigade, profile, shift, transport). Ids 9-20 form the day roster.
ENGINEERS = {
    9: (1, "universal", FULL_12, "car"),
    10: (2, "universal", FULL_12, "car"),
    11: (1, "installer", EARLY_8, "public_transport"),
    12: (2, "technician", LATE_8, "walking"),
    13: (3, "universal", FULL_12, "car"),
    14: (4, "universal", FULL_12, "car"),
    15: (3, "installer", EARLY_8, "public_transport"),
    # Lives in Кашира and starts the day from home, as the experts describe.
    16: (4, "universal", FULL_12, "car"),
    17: (5, "universal", FULL_12, "car"),
    18: (6, "universal", FULL_12, "car"),
    19: (5, "technician", Shift(time(10), time(18), "5/2"), "bicycle"),
    20: (6, "installer", EARLY_8, "public_transport"),
    # Outside the published roster of the day.
    21: (5, "universal", DAY_12, "car"),
}
ROSTER = tuple(range(9, 21))
OUTSIDE_ROSTER = 21
REMOTE_HOME_WORKER = 16
# Six morning requests per brigade: (work type, window start). A senior engineer and a
# junior one can serve them without the junior needing a skill he lacks.
MORNING_WITH_INSTALLER = (
    ("connection", 10),
    ("repair", 10),
    ("connection", 12),
    ("additional", 14),
    ("repair", 14),
    ("connection", 16),
)
MORNING_WITH_TECHNICIAN = (
    ("repair", 10),
    ("connection", 10),
    ("repair", 12),
    ("repair", 14),
    ("connection", 14),
    ("additional", 16),
)
# The remote towns get the connections of brigade 4.
REMOTE_ORDINALS = {0: "Домодедово", 2: "Ступино", 5: "Кашира"}
NEW_ORDINARY_KINDS = ("Нет линка", "Работа с кабелем")
ZONES = ("vostok", "yugo_vostok", "yugotsentr", "domodedovo", "stupino", "kashira")


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime.combine(DATE, time(hour, minute), TZ)


class AcceptanceGenerator(Generator):
    def __init__(self):
        super().__init__(seed=SEED, start_date=DATE, tickets=48, workers=0, days=1)
        # Everybody of the package works on the acceptance day; the roster decides who plans.
        self.all_on_duty = True
        self.cases = []

    def reference(self):
        super().reference()
        self.city_ids = {"Москва": 1}
        for index, town in enumerate(REMOTE_TOWNS, 2):
            self.add("cities", id=index, name=town.name)
            self.city_ids[town.name] = index

    def staff(self):
        self.worker_count = 0
        super().staff()
        for user_id, (brigade, role, shift, transport) in ENGINEERS.items():
            home = None
            target = self.brigades[brigade - 1]
            if user_id == REMOTE_HOME_WORKER:
                town = district_buildings("Кашира")
                building = town[len(town) // 2]
                entrance, apartment, floor = building.apartment(user_id * 7)
                home = self.place(
                    building,
                    target["area"]["id"],
                    entrance,
                    apartment,
                    floor,
                    self.city_ids["Кашира"],
                )
            created = self.add_worker(target, role, shift, transport, start_location_id=home)
            assert created == user_id, "acceptance engineer ids are part of the contract"
        self.cover_transports()

    def building(self, brigade: int, ordinal: int, town: str | None = None):
        if town:
            pool = district_buildings(town)
        else:
            pool = [b for name in BORDER_DISTRICTS[brigade] for b in district_buildings(name)]
        # A stable spread over the districts' real houses.
        return pool[(ordinal * 37 + brigade * 11) % len(pool)]

    def demand(self):
        for index in range(48):
            area_index = index % 3
            if index < 36:
                self.morning(index, area_index)
            else:
                self.arrival(index, area_index)
        self.shortage_office = None

    def morning(self, index: int, area_index: int):
        brigade_number = area_index * 2 + (index // 3) % 2 + 1
        brigade = self.brigades[brigade_number - 1]
        ordinal = index // 6
        juniors = {self.workers[w]["role"] for w in brigade["members"] if w in ROSTER and w != 16}
        plan = MORNING_WITH_TECHNICIAN if "technician" in juniors else MORNING_WITH_INSTALLER
        code, hour = plan[ordinal]
        spec = WORK_TYPE_BY_CODE[code]
        town = REMOTE_ORDINALS.get(ordinal) if brigade_number == 4 else None
        building = self.building(brigade_number, ordinal, town)
        entrance, apartment, floor = building.apartment(index * 13 + 5)
        received = datetime.combine(DATE - timedelta(days=1), time(9 + index % 12), TZ)
        ticket = self.create_ticket(
            spec,
            brigade,
            building,
            entrance,
            apartment,
            floor,
            _at(hour),
            _at(hour + 2),
            received,
            city_id=self.city_ids.get(town, 1),
        )
        self.finish(ticket, spec, brigade, "planned", town or "Москва")

    def arrival(self, index: int, area_index: int):
        brigade_number = area_index * 2 + 1
        brigade = self.brigades[brigade_number - 1]
        emergency = (index - 36) // 3 >= 2
        spec = WORK_TYPE_BY_CODE["emergency" if emergency else "repair"]
        start = _at(10 + (index - 36) // 3)
        received = start - timedelta(minutes=20)
        if index == 36:
            received = _at(8, 10)
        if index == 41:
            received = _at(8, 12)
        end = start + timedelta(minutes=15 if index == 41 else 180)
        if index == 42:
            start, end = _at(10), _at(12)
        elif index == 44:
            start, end = _at(12), _at(14)
        # The remote arrival remains inside area 102 and uses a real regional address.
        town = "Домодедово" if index == 37 else None
        building = self.building(brigade_number, index, town)
        entrance, apartment, floor = building.apartment(index * 17 + 3)
        kind = None
        if not emergency:
            kind = next(
                k
                for k in REQUEST_KINDS["repair"]
                if k.hd_type == NEW_ORDINARY_KINDS[index % len(NEW_ORDINARY_KINDS)]
            )
        ticket = self.create_ticket(
            spec,
            brigade,
            building,
            entrance,
            apartment,
            floor,
            start,
            end,
            received,
            city_id=self.city_ids.get(town, 1),
            kind=kind,
        )
        if emergency:
            # Both reaction norms of the case: one and two hours.
            ticket["response_deadline_at"] = received + timedelta(minutes=60 if index % 2 else 120)
        # The arrival itself is the event of the day that the planner reacts to.
        self.add(
            "work_events",
            event_type="new_ticket",
            ticket_id=ticket["id"],
            worker_id=None,
            service_area_id=ticket["service_area_id"],
            route_date=DATE,
            occurred_at=ticket["received_at"],
            recorded_at=ticket["received_at"],
            actor_id=1,
            reason=None,
            previous_state=None,
            new_state="waiting_assignment",
            before_revision=None,
            after_revision=1,
            idempotency_key=f"acceptance-{SEED}-{ticket['id']}",
            payload={"ticket_id": ticket["id"], "source": "helpdesk"},
        )
        self.finish(ticket, spec, brigade, "new", town or "Москва")

    def finish(self, ticket: dict, spec, brigade, phase: str, city: str):
        self.allocate(ticket, spec, brigade, ticket.pop("_appliances"))
        locations = {row["id"]: row for row in self.tables["locations"]}
        location = locations[ticket["location_id"]]
        building = next(
            row for row in self.tables["buildings"] if row["id"] == location["building_id"]
        )
        street = next(
            row["name"] for row in self.tables["streets"] if row["id"] == building["street_id"]
        )
        house = building["number"] + (f", {building['block']}" if building["block"] else "")
        self.cases.append(
            {
                "ticket_id": ticket["id"],
                "phase": phase,
                "category": spec.category,
                "service_area_id": ticket["service_area_id"],
                "brigade_id": ticket["brigade_id"],
                "received_at": ticket["received_at"].isoformat(),
                "visit_window_start": ticket["visit_window_start"].isoformat(),
                "visit_window_end": ticket["visit_window_end"].isoformat(),
                "window": [
                    ticket["visit_window_start"].isoformat(),
                    ticket["visit_window_end"].isoformat(),
                ],
                "request_type_hd": ticket["request_type_hd"],
                "title": ticket["title"],
                "address": f"{city}, {street}, д. {house}"
                + (f", кв. {location['apartment']}" if location["apartment"] else ""),
            }
        )


def build_dataset() -> tuple[dict, dict]:
    """Return importable rows and the separate event/roster scenario contract."""
    generator = AcceptanceGenerator()
    tables = generator.run().tables
    assert len(tables["users"]) == OBSERVERS + FOREMEN + len(ENGINEERS)
    scenarios = {
        "schema_version": 2,
        "seed": SEED,
        "timezone": TIMEZONE,
        "route_date": DATE.isoformat(),
        "roster_worker_ids": list(ROSTER),
        "outside_roster_worker_id": OUTSIDE_ROSTER,
        "remote_home_worker_id": REMOTE_HOME_WORKER,
        "territory_cases": {
            "nearby_cross_area_ticket_id": 37,
            "nearby_reference_ticket_id": 2,
            "nearby_worker_id": 13,
            "same_area_remote_ticket_id": 38,
        },
        "window_cases": {"no_slot_ticket_id": 43, "later_window_ticket_id": 45},
        "initial_plan": (
            "В пакете нет маршрутов и ревизий дня: первый план каждого участка строит "
            "планировщик по заявкам фазы planned и дневному составу (POST "
            "/api/v1/planning/preview с service_area_id, затем apply)."
        ),
        "tickets": generator.cases,
        "events": [
            {
                "ticket_id": case["ticket_id"],
                "received_at": case["received_at"],
                "category": case["category"],
                "request_type_hd": case["request_type_hd"],
                "title": case["title"],
                "address": case["address"],
            }
            for case in generator.cases
            if case["phase"] == "new"
        ],
    }
    return tables, scenarios


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(h))


def zone_points() -> dict[str, tuple[float, float]]:
    points = {area.code: (area.office.latitude, area.office.longitude) for area in AREAS}
    for town, code in zip(REMOTE_TOWNS, ZONES[3:], strict=True):
        south, west, north, east = town.bbox
        points[code] = ((south + north) / 2, (west + east) / 2)
    return points


def road_matrix() -> dict:
    """Directed stub: road length from real distances, slower towards the city centre."""
    points = zone_points()
    travel, distance = {}, {}
    for source in ZONES:
        travel[source], distance[source] = {}, {}
        for target in ZONES:
            if source == target:
                travel[source][target] = distance[source][target] = 0
                continue
            road_km = _haversine_km(points[source], points[target]) * 1.35
            remote = source in ZONES[3:] or target in ZONES[3:]
            speed = 55 if remote else 24
            # Morning traffic runs into Moscow: trips towards Moscow zones take longer.
            inbound = 1.18 if target in ZONES[:3] and source in ZONES[3:] else 1.0
            travel[source][target] = round(road_km / speed * 60 * inbound) + 8
            distance[source][target] = round(road_km * 1000)
    return {
        "schema_version": 2,
        "source": "deterministic_stub",
        "seed": SEED,
        "timezone": TIMEZONE,
        "route_date": DATE.isoformat(),
        "zones": list(ZONES),
        "zone_points": {k: list(v) for k, v in points.items()},
        "travel_minutes": travel,
        "distance_meters": distance,
        "peak_profile": {
            "09:00-11:00": {"duration_multiplier": 1.3},
            "16:00-19:00": {"duration_multiplier": 1.5},
        },
        "note": (
            "Directed synthetic matrix: straight-line distances between real points times "
            "1.35, average speeds and a morning inbound delay. It is not Geoapify output "
            "or a native planner result."
        ),
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
        "generator_version": 2,
        "seed": SEED,
        "timezone": TIMEZONE,
        "route_date": DATE.isoformat(),
        "counts": {name: len(rows) for name, rows in tables.items()},
        "roster_worker_ids": list(ROSTER),
        "initial_plan": "native_planner",
        "road_matrix_source": "deterministic_stub",
        "addresses": (
            "Реальные дома Москвы, Домодедово, Ступино и Каширы из OpenStreetMap "
            "(© участники OpenStreetMap, ODbL 1.0); заявки, люди и квартиры вымышлены."
        ),
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

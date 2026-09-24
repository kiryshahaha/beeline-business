"""Generate deterministic, entirely fictional exchange packages without touching a DB."""

import argparse
import hashlib
import json
import random
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from app.modules.data_exchange.formats import json_default, parse_file, serialize
from app.modules.data_exchange.registry import TABLES
from app.modules.routing.schemas import RouteGeoJSON

SCENARIOS = (
    "balanced",
    "overlapping_windows",
    "missing_skill",
    "unassigned",
    "missing_coordinates",
    "equipment_shortage",
    "urgent_example",
    "night_shift",
)
SKILLS = ("Локальные работы", "Работы на подключение и дозаказы", "Аварийные работы")
TRANSPORT = ("car", "walking", "bicycle", "public_transport")
APPLIANCE_TYPES = (
    "CLIENT_ROUTER",
    "RACK_ROUTER",
    "CABLE",
    "FIBER",
    "TOOL",
    "TV_BOX",
    "SPEAKER",
    "IP_CAMERA",
    "OTHER",
)
TZ = timezone(timedelta(hours=3))


def generate_dataset(*, seed=42, start_date=date(2026, 9, 21), tickets=1500, workers=120, days=7):
    if tickets < 8 or workers < 4 or days < 1:
        raise ValueError("Нужно не менее 8 заявок, 4 исполнителей и 1 дня")
    rng = random.Random(seed)
    tables = {name: [] for name in TABLES}
    stamp = datetime.combine(start_date, time(8), TZ)

    def add(entity, **values):
        for column in TABLES[entity].columns:
            key = column.name
            if key in values or key == "password_hash":
                continue
            if key == "id":
                values[key] = len(tables[entity]) + 1
            elif key in ("created_at", "updated_at", "assigned_at", "next_attempt_at"):
                values[key] = stamp
            elif column.nullable:
                values[key] = None
        tables[entity].append(values)
        return values

    for i in range(1, 4):
        add("cities", id=i, name=f"Синтетический город {seed}-{i}")
    for i in range(1, 13):
        add("districts", id=i, city_id=(i - 1) // 4 + 1, name=f"Тестовый район {i}")
        add("streets", id=i, city_id=(i - 1) // 4 + 1, name=f"Вымышленная улица {i}")
    location_count = max(24, (tickets + 2) // 3)
    for i in range(1, location_count + 1):
        district = (i - 1) % 12 + 1
        add(
            "buildings",
            id=i,
            city_id=(district - 1) // 4 + 1,
            district_id=district,
            street_id=district,
            number=str(i),
        )
        add("entrances", id=i, building_id=i, number=str(i % 3 + 1))
        missing = i > 6 and i % 17 == 0
        add(
            "locations",
            id=i,
            building_id=i,
            entrance_id=i,
            floor=i % 20,
            apartment=str(i % 90 + 1),
            latitude=None if missing else round(55.65 + rng.random() * 0.2, 6),
            longitude=None if missing else round(37.45 + rng.random() * 0.3, 6),
        )
    for i in range(1, 7):
        add("offices", id=i, location_id=i, name=f"Синтетический офис {seed}-{i}")
    for i, skill in enumerate(SKILLS, 1):
        add("worker_skills", id=i, skill=skill)
    for i in range(1, 9 + workers):
        role = "observer" if i <= 2 else "foreman" if i <= 8 else "worker"
        add(
            "users",
            id=i,
            name=f"Тестовый{role}{i}",
            surname=f"Синтетический{seed}",
            username=f"synthetic_{seed}_{role}_{i}",
            role=role,
        )
        if role != "worker":
            continue
        w = i - 9
        night = w % 10 == 0
        add(
            "workers",
            user_id=i,
            workshift_start=time(22 if night else 8),
            workshift_end=time(6 if night else 18),
            transport_type=TRANSPORT[w % 4],
            is_on_line=True,
        )
        for skill in range(1, w % 3 + 2):
            add("worker_skill_assignments", worker_id=i, skill_id=skill)
        add("brigade_members", brigade_id=w % 6 + 1, worker_id=i)
    for i in range(1, 7):
        add(
            "brigades",
            id=i,
            name=f"Синтетическая бригада {seed}-{i}",
            foreman_id=i + 2,
            office_id=i,
        )
    for i in range(1, 28):
        add(
            "appliances",
            id=i,
            name=f"Тестовое оборудование {seed}-{i}",
            type=APPLIANCE_TYPES[(i - 1) % 9],
            description="Полностью вымышленная номенклатура",
            unit="м" if i % 9 in (3, 4) else "шт",
            is_active=i != 27,
        )
        for office in range(1, 7):
            add(
                "appliance_stocks",
                office_id=office,
                appliance_id=i,
                stock=0 if i == 26 else tickets * 3,
            )
    # Explicit fictional requirements, scoped by seed to keep packages independent.
    for i, skill in enumerate(SKILLS, 1):
        add(
            "work_types",
            id=i,
            name=f"{skill} [synthetic {seed}]",
            travel_minutes=15,
            work_minutes=30,
            documents_minutes=10,
            norm_minutes=55,
        )
        add(
            "work_type_planning_rules",
            work_type_id=i,
            service_duration_source="ticket_estimate",
            configured_by=1,
        )
        add("work_type_required_skills", work_type_id=i, skill_id=i)
        add("work_type_required_appliances", work_type_id=i, appliance_id=i, quantity=1)
    for i in range(1, tickets + 1):
        scenario = SCENARIOS[(i - 1) % len(SCENARIOS)]
        day = start_date + timedelta(days=(i - 1) % days)
        start = datetime.combine(day, time(22 if scenario == "night_shift" else (8 + i % 8)), TZ)
        duration = (30, 45, 60, 90)[i % 4]
        location = (i - 1) % location_count + 1
        if scenario == "missing_coordinates":
            # Every labelled case really references an ungeocoded location, including
            # the small fixture; other scenarios retain the full address distribution.
            location = 17 * ((i // 8) % (location_count // 17) + 1)
        status = ("planned", "in_progress", "completed", "wont_fix")[(i // 8) % 4]
        add(
            "tickets",
            id=i,
            location_id=location,
            title=f"[Синтетика:{scenario}] Заявка {i}",
            description=(
                f"Сценарий {scenario}; seed={seed}. Вымышленные данные.\n"
                "Строка с запятой, точкой; и «кавычками»."
                + (
                    " Требуется позиция оборудования 26 с нулевым остатком."
                    if scenario == "equipment_shortage"
                    else ""
                )
            ),
            work_type="Редкий отсутствующий навык"
            if scenario == "missing_skill"
            else f"{SKILLS[i % 3]} [synthetic {seed}]",
            status=status,
            visit_window_start=start,
            visit_window_end=start
            + timedelta(minutes=30 if scenario == "overlapping_windows" else 240),
            estimated_duration_minutes=duration,
            actual_duration_minutes=duration + i % 20 if status == "completed" else None,
            planned_start_at=start + timedelta(minutes=10)
            if status in ("in_progress", "completed")
            else None,
            planned_end_at=start + timedelta(minutes=duration + 10)
            if status in ("in_progress", "completed")
            else None,
        )
        worker = (i - 1) % workers + 9
        if scenario not in ("unassigned", "missing_skill"):
            add("ticket_assignments", ticket_id=i, worker_id=worker)
        if i % 3 == 0:
            add(
                "ticket_comments",
                ticket_id=i,
                author_id=1,
                text=f"Синтетический комментарий {i}, проверка UTF-8 и переноса\nвторой строки",
            )
        if scenario != "equipment_shortage":
            add(
                "ticket_appliances",
                ticket_id=i,
                appliance_id=i % 24 + 1,
                office_id=(worker - 9) % 6 + 1,
                quantity=i % 3 + 1,
            )
        if i % 5 == 0:
            add(
                "notification_events",
                recipient_id=worker,
                ticket_id=i,
                kind="ticket_assigned",
                data={"ticket_id": i, "worker_id": worker},
                attempt_count=0,
                websocket_delivered_at=stamp,
                push_delivered_at=stamp,
            )
    # Saved routes are fixture snapshots, not an assertion that the optimizer found these plans.
    for w in range(workers):
        for day_index in range(days):
            day = start_date + timedelta(days=day_index)
            worker = w + 9
            location_ids = [w % 6 + 1, (w + 1) % 6 + 1]
            start = datetime.combine(day, time(22 if w % 10 == 0 else 9), TZ)
            for number in range(1, 3 if w < 8 else 2):
                features = []
                points = []
                for sequence, location_id in enumerate(location_ids, 1):
                    loc = tables["locations"][location_id - 1]
                    position = [loc["longitude"], loc["latitude"]]
                    points.append(position)
                    features.append(
                        {
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": position},
                            "properties": {
                                "location_id": location_id,
                                "ticket_id": None,
                                "sequence": sequence,
                                "arrival_at": (
                                    start + timedelta(minutes=sequence * 40 + number)
                                ).isoformat(),
                                "service_start_at": (
                                    start + timedelta(minutes=sequence * 40 + number)
                                ).isoformat(),
                                "service_end_at": (
                                    start + timedelta(minutes=sequence * 40 + number + 30)
                                ).isoformat(),
                                "waiting_minutes": 0,
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
                geojson = RouteGeoJSON.model_validate(
                    {
                        "type": "FeatureCollection",
                        "properties": {
                            "worker_id": worker,
                            "route_date": day,
                            "route_number": number,
                        },
                        "features": features,
                    }
                ).model_dump(mode="json")
                add(
                    "routes", worker_id=worker, route_date=day, route_number=number, geojson=geojson
                )
    return tables


def write_dataset(output: Path, **options) -> dict:
    tables = generate_dataset(**options)
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    for format, extension in (("csv", "zip"), ("xlsx", "xlsx")):
        content = serialize(tables, format)
        # Check every generated row with the same parser used by the upload API.
        parsed = parse_file(content, f"dataset.{extension}")
        assert {k: len(v) for k, v in parsed.items()} == {k: len(v) for k, v in tables.items()}
        path = output / f"dataset.{extension}"
        path.write_bytes(content)
        files[path.name] = {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    manifest = {
        "generator": "generate_synthetic.py",
        "parameters": options,
        "counts": {name: len(rows) for name, rows in tables.items()},
        "scenarios": SCENARIOS,
        "files": files,
        "notes": [
            "Все имена, адреса, заявки и комментарии вымышлены. "
            "Координаты служат тестовыми точками.",
            "urgent_example отмечен в названии: поле приоритета пока отсутствует в модели заявок.",
            "equipment_shortage: нулевой остаток позиции 26; "
            "невозможные резервы вынесены в отрицательные тесты.",
            "Маршруты — сохранённые примеры, "
            "а не результат оптимизации или доказательство выполнимости.",
            "Импортированные учётные записи не имеют известного пароля; пароль задаётся отдельно.",
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=json_default) + "\n",
        encoding="utf-8",
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("../data/synthetic/standard"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--date", type=date.fromisoformat, default=date(2026, 9, 21))
    parser.add_argument("--tickets", type=int, default=1500)
    parser.add_argument("--workers", type=int, default=120)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    result = write_dataset(
        args.output,
        seed=args.seed,
        start_date=args.date,
        tickets=args.tickets,
        workers=args.workers,
        days=args.days,
    )
    print(json.dumps(result["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

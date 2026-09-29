"""Download real residential buildings of the case areas from OpenStreetMap.

Run from backend/: ``python -m synthetic_moscow.fetch_osm``. The result replaces
``synthetic_moscow/buildings.json``; raw Overpass answers are cached in
``.local/osm-cache`` so a repeated run is offline and byte-for-byte reproducible.

Data © OpenStreetMap contributors, available under the Open Database License 1.0.
"""

import argparse
import hashlib
import json
import math
import re
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from synthetic_moscow.geography import AREAS, BUILDINGS_FILE, MOSCOW, REMOTE_TOWNS

ENDPOINTS = (
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
USER_AGENT = "beeline-business-synthetic-data/1.0 (hackathon; OSM extract)"
RESIDENTIAL = "^(apartments|residential)$"
# Typical Moscow sections have four apartments per floor.
APARTMENTS_PER_FLOOR = 4
HOUSE = re.compile(
    r"^(?P<number>\d{1,4}(?:[А-ЯЁа-яё](?![А-ЯЁа-яё]))?(?:/\d{1,3}[А-ЯЁа-яё]?)?)"
    r"(?:\s*к\s*(?P<korpus>\d{1,3}[А-ЯЁа-яё]?))?"
    r"(?:\s*с\s*(?P<stroenie>\d{1,3}[А-ЯЁа-яё]?))?$"
)
FLATS_RANGE = re.compile(r"^\s*(\d{1,4})\s*[-–]\s*(\d{1,4})\s*$")


def overpass(query: str, cache_dir: Path) -> dict:
    key = hashlib.sha256(query.encode()).hexdigest()[:24]
    cached = cache_dir / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    body = urllib.parse.urlencode({"data": query}).encode()
    last_error = None
    for attempt in range(6):
        endpoint = ENDPOINTS[attempt % len(ENDPOINTS)]
        request = urllib.request.Request(
            endpoint, data=body, headers={"User-Agent": USER_AGENT}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError) as error:
            last_error = error
            time.sleep(5 * (attempt + 1))
            continue
        if "remark" in payload and not payload.get("elements"):
            last_error = RuntimeError(payload["remark"])
            time.sleep(5 * (attempt + 1))
            continue
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload
    raise RuntimeError(f"Overpass недоступен: {last_error}")


def district_query(relation: int) -> str:
    return f"""[out:json][timeout:280];
area(id:{3600000000 + relation})->.d;
way(area.d)["building"~"{RESIDENTIAL}"]["addr:street"]["addr:housenumber"]->.b;
.b out center;
node(w.b)["entrance"];
out;"""


def town_query(town) -> str:
    south, west, north, east = town.bbox
    return f"""[out:json][timeout:280];
way({south},{west},{north},{east})["building"~"{RESIDENTIAL}"]["addr:street"]
  ["addr:housenumber"]["building:levels"]->.b;
.b out center;
node(w.b)["entrance"];
out;"""


def parse_house(value: str) -> tuple[str, str | None] | None:
    match = HOUSE.match(value.strip().replace("  ", " "))
    if not match:
        return None
    parts = []
    if match["korpus"]:
        parts.append(f"корпус {match['korpus']}")
    if match["stroenie"]:
        parts.append(f"строение {match['stroenie']}")
    return match["number"].upper(), ", ".join(parts) or None


def positive_int(value, low: int, high: int) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def natural_key(value: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", value))


def mapped_entrances(way: dict, nodes: dict) -> list[dict]:
    result = []
    for node_id in way.get("nodes", []):
        node = nodes.get(node_id)
        if node is None:
            continue
        ref = positive_int(node["tags"].get("ref"), 1, 40)
        if ref is None:
            continue
        flats = FLATS_RANGE.match(node["tags"].get("addr:flats", ""))
        result.append(
            {
                "ref": str(ref),
                "lat": round(node["lat"], 6),
                "lon": round(node["lon"], 6),
                "flats": [int(flats[1]), int(flats[2])] if flats else None,
            }
        )
    unique = {entrance["ref"]: entrance for entrance in result}
    return [unique[ref] for ref in sorted(unique, key=int)]


def valid_ranges(entrances: list[dict]) -> bool:
    if not entrances or any(e["flats"] is None for e in entrances):
        return False
    previous = 0
    for entrance in entrances:
        first, last = entrance["flats"]
        if not previous < first <= last or last - first > 400:
            return False
        previous = last
    return True


def building_record(
    way: dict, nodes: dict, city: str, district: str, *, estimate_flats: bool = False
) -> dict | None:
    tags = way["tags"]
    house = parse_house(tags["addr:housenumber"])
    levels = positive_int(tags.get("building:levels"), 2, 60)
    if house is None or levels is None or "center" not in way:
        return None
    entrances = mapped_entrances(way, nodes)
    flats = positive_int(tags.get("building:flats"), 2, 3000)
    if valid_ranges(entrances):
        source = "osm"
        flats = entrances[-1]["flats"][1] - entrances[0]["flats"][0] + 1
    else:
        if flats is None and estimate_flats and levels >= 3:
            # Town houses rarely carry the number of apartments in OSM: typical sections.
            flats = (len(entrances) or 2) * levels * APARTMENTS_PER_FLOOR
        if flats is None:
            return None
        source = "estimated"
        count = len(entrances) or max(1, round(flats / (levels * APARTMENTS_PER_FLOOR)))
        per_entrance = math.ceil(flats / count)
        if per_entrance < levels:
            count = max(1, flats // levels)
            per_entrance = math.ceil(flats / count)
            entrances = []
        positions = entrances or [{"ref": str(i + 1)} for i in range(count)]
        entrances = []
        for index, entrance in enumerate(positions[:count]):
            first = index * per_entrance + 1
            last = min(flats, first + per_entrance - 1)
            if first > last:
                break
            entrances.append({**entrance, "flats": [first, last]})
    center = way["center"]
    number, block = house
    record = {
        "osm": f"way/{way['id']}",
        "city": city,
        "district": district,
        "street": tags["addr:street"].strip(),
        "number": number,
        "lat": round(center["lat"], 6),
        "lon": round(center["lon"], 6),
        "levels": levels,
        "flats": flats,
        "entrance_source": source,
        "entrances": [
            {key: value for key, value in e.items() if value is not None} for e in entrances
        ],
    }
    if block:
        record["block"] = block
    return record


def collect(payload: dict, city: str, district: str, *, estimate_flats=False) -> list[dict]:
    nodes = {e["id"]: e for e in payload["elements"] if e["type"] == "node"}
    records = {}
    for way in payload["elements"]:
        if way["type"] != "way":
            continue
        record = building_record(way, nodes, city, district, estimate_flats=estimate_flats)
        if record is None:
            continue
        key = (record["street"].lower(), record["number"], record.get("block"))
        # Several OSM ways can carry one address; the larger building represents it.
        if key not in records or record["flats"] > records[key]["flats"]:
            records[key] = record
    return sorted(
        records.values(),
        key=lambda r: (r["street"], natural_key(r["number"]), r.get("block") or ""),
    )


STREET_WORDS = {
    "улица",
    "ул",
    "проспект",
    "пр-кт",
    "бульвар",
    "б-р",
    "переулок",
    "пер",
    "проезд",
    "шоссе",
    "ш",
    "набережная",
    "наб",
    "площадь",
    "пл",
    "тупик",
    "туп",
}


def address_key(city: str, street: str, number: str, block: str | None) -> tuple:
    words = frozenset(
        word
        for word in re.split(r"[\s.,]+", street.lower().replace("ё", "е"))
        if word and word not in STREET_WORDS
    )
    parts = re.findall(r"(корпус|корп|к|строение|стр|с)\.?\s*([0-9a-zа-я]+)", (block or "").lower())
    return (
        city.lower().replace("ё", "е"),
        words,
        number.lower(),
        "".join(kind[0] + value for kind, value in parts),
    )


def source_address_keys(directory: Path) -> set[tuple]:
    """Addresses of the organizer's day files, used only to leave those houses out.

    The files are not part of the repository and their addresses are never written
    anywhere: a synthetic request must not land on a house of the real control day.
    """
    import csv
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "source_addresses",
        Path(__file__).resolve().parents[1] / "app/modules/source_import/addresses.py",
    )
    addresses = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(addresses)
    keys = set()
    for path in sorted(directory.glob("*.csv")):
        text = path.read_bytes().decode("cp1251", errors="replace")
        for row in csv.reader(text.splitlines(), delimiter=";"):
            for cell in row:
                parsed = addresses.parse_address(cell) if "д" in cell else None
                if parsed is not None:
                    keys.add(
                        address_key(
                            parsed.city, parsed.street, parsed.building_number, parsed.block
                        )
                    )
    return keys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path(".local/osm-cache"))
    parser.add_argument("--output", type=Path, default=BUILDINGS_FILE)
    parser.add_argument(
        "--exclude-source-dir",
        type=Path,
        help="Папка с исходными файлами организатора: их дома не попадут в выгрузку",
    )
    args = parser.parse_args()
    excluded = source_address_keys(args.exclude_source_dir) if args.exclude_source_dir else set()
    buildings = []
    districts = {}
    for area in AREAS:
        for district in area.districts:
            payload = overpass(district_query(district.osm_relation), args.cache)
            rows = [
                row
                for row in collect(payload, MOSCOW, district.name)
                if address_key(MOSCOW, row["street"], row["number"], row.get("block"))
                not in excluded
            ]
            districts[district.name] = {
                "area": area.code,
                "city": MOSCOW,
                "osm_relation": district.osm_relation,
                "buildings": len(rows),
                "osm_timestamp": payload["osm3s"]["timestamp_osm_base"],
            }
            buildings.extend(rows)
            print(f"{area.name} / {district.name}: {len(rows)}")
    for town in REMOTE_TOWNS:
        payload = overpass(town_query(town), args.cache)
        rows = [
            row
            for row in collect(payload, town.name, town.name, estimate_flats=True)
            if address_key(town.name, row["street"], row["number"], row.get("block"))
            not in excluded
        ]
        districts[town.name] = {
            "area": town.area_code,
            "city": town.name,
            "bbox": list(town.bbox),
            "buildings": len(rows),
            "osm_timestamp": payload["osm3s"]["timestamp_osm_base"],
        }
        buildings.extend(rows)
        print(f"{town.name}: {len(rows)}")
    document = {
        "source": "OpenStreetMap, Overpass API",
        "license": "Open Database License (ODbL) 1.0",
        "attribution": "© участники OpenStreetMap, openstreetmap.org/copyright",
        "extracted_on": date.today().isoformat(),
        "selection": (
            "Жилые дома (building=apartments|residential) с улицей, номером дома, "
            "этажностью и числом квартир или подъездами с диапазонами квартир"
        ),
        "districts": districts,
        "excluded": (
            "Дома из дневных файлов организатора исключены из выборки"
            if excluded
            else "Исключения не применялись"
        ),
        "buildings": buildings,
    }
    # One building per line keeps a regenerated file reviewable as a diff.
    head = {key: value for key, value in document.items() if key != "buildings"}
    lines = [json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in buildings]
    text = json.dumps(head, ensure_ascii=False, indent=1)[:-2]
    text += ',\n "buildings": [\n' + ",\n".join(lines) + "\n ]\n}\n"
    args.output.write_text(text, encoding="utf-8")
    print(f"Всего домов: {len(buildings)} -> {args.output}")


if __name__ == "__main__":
    main()

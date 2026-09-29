"""Service areas of the case, their real Moscow districts and real addresses of buildings.

The three areas, their districts and office addresses follow the organizer's day files
(«Восток», «Юго-восток», «Югоцентр»). Buildings come from OpenStreetMap
(`buildings.json`, see README.md): the street, house number, block, coordinates, number of
floors and apartments are real; apartments, floors and entrances of a request are picked
inside those real limits.
"""

import json
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path

BUILDINGS_FILE = Path(__file__).with_name("buildings.json")
MOSCOW = "Москва"


@dataclass(frozen=True, kw_only=True)
class Office:
    name: str
    city: str
    street: str
    number: str
    block: str | None
    latitude: float
    longitude: float
    # How the organizer writes the office row under the day table.
    source_text: str


@dataclass(frozen=True, kw_only=True)
class District:
    name: str
    osm_relation: int
    # Spelling of the «Район» column in the organizer's files.
    source_name: str


@dataclass(frozen=True, kw_only=True)
class Area:
    code: str
    name: str
    office: Office
    # Each brigade of an area serves its own group of neighbouring districts.
    zones: tuple[tuple[District, ...], ...]

    @property
    def districts(self) -> tuple[District, ...]:
        return tuple(district for zone in self.zones for district in zone)


@dataclass(frozen=True, kw_only=True)
class RemoteTown:
    """A Moscow-region town that the organizer includes into the «Юго-восток» area."""

    name: str
    area_code: str
    # South, west, north, east of the town's built-up area.
    bbox: tuple[float, float, float, float]


def _d(name: str, relation: int, source_name: str | None = None) -> District:
    return District(name=name, osm_relation=relation, source_name=source_name or name)


AREAS = (
    Area(
        code="vostok",
        name="Восток",
        office=Office(
            name="Офис «Восток»",
            city=MOSCOW,
            street="улица Юных Ленинцев",
            number="83",
            block="строение 4",
            latitude=55.702267,
            longitude=37.773852,
            source_text="г. Москва, ул Юных Ленинцев, д 83с 4",
        ),
        zones=(
            (
                _d("Таганский", 1275608),
                _d("Басманный", 2162195),
                _d("Лефортово", 1278064),
                _d("Нижегородский", 1278046),
                _d("Южнопортовый", 1278096),
            ),
            (
                _d("Текстильщики", 455184),
                _d("Кузьминки", 444812),
                _d("Рязанский", 1255563),
                _d("Выхино-Жулебино", 548619, "Выхино"),
            ),
        ),
    ),
    Area(
        code="yugo_vostok",
        name="Юго-восток",
        office=Office(
            name="Офис «Юго-восток»",
            city=MOSCOW,
            street="Бирюлёвская улица",
            number="1",
            block="строение 1",
            latitude=55.601956,
            longitude=37.664752,
            source_text="г. Москва, ул Бирюлёвская, д 1с1",
        ),
        zones=(
            (
                _d("Царицыно", 950641),
                _d("Москворечье-Сабурово", 455528, "Москворечье - Сабурово"),
                _d("Бирюлёво Восточное", 950639, "Бирюлево Восточное"),
                _d("Бирюлёво Западное", 950658, "Бирюлево Западное"),
            ),
            (
                _d("Орехово-Борисово Северное", 455539, "Орехово Борисово Северное"),
                _d("Орехово-Борисово Южное", 456807, "Орехово Борисово Южное"),
                _d("Зябликово", 531264),
                _d("Братеево", 531287),
            ),
        ),
    ),
    Area(
        code="yugotsentr",
        name="Югоцентр",
        office=Office(
            name="Офис «Югоцентр»",
            city=MOSCOW,
            street="Симферопольский проезд",
            number="7",
            block=None,
            latitude=55.665025,
            longitude=37.615596,
            source_text="г.Москва проезд Симферопольский, д.7",
        ),
        zones=(
            (
                _d("Хамовники", 1255987),
                _d("Замоскворечье", 1255942),
                _d("Даниловский", 1281209),
                _d("Донской", 444908),
                _d("Нагатино-Садовники", 535655, "Нагатино - Садовники"),
                _d("Нагатинский Затон", 455460),
            ),
            (
                _d("Нагорный", 535662),
                _d("Котловка", 1292211),
                _d("Зюзино", 1292286),
                _d("Академический", 1281220),
                _d("Гагаринский", 1281648),
            ),
        ),
    ),
)

# Only the Plan 5 acceptance package uses them, as in the organizer's «Юго-восток» file.
REMOTE_TOWNS = (
    RemoteTown(name="Домодедово", area_code="yugo_vostok", bbox=(55.38, 37.70, 55.48, 37.84)),
    RemoteTown(name="Ступино", area_code="yugo_vostok", bbox=(54.86, 38.02, 54.92, 38.13)),
    RemoteTown(name="Кашира", area_code="yugo_vostok", bbox=(54.80, 38.12, 54.87, 38.29)),
)

AREA_BY_CODE = {area.code: area for area in AREAS}


def split_zones(area: Area, parts: int) -> tuple[tuple[District, ...], ...]:
    """Neighbouring districts of an area for ``parts`` brigades, in the area's order."""
    if parts == len(area.zones):
        return area.zones
    districts = area.districts
    if parts > len(districts):
        return tuple((districts[index % len(districts)],) for index in range(parts))
    bounds = [round(index * len(districts) / parts) for index in range(parts + 1)]
    return tuple(districts[bounds[i] : bounds[i + 1]] for i in range(parts))


@dataclass(frozen=True, kw_only=True)
class Entrance:
    number: str
    first_apartment: int
    last_apartment: int
    latitude: float
    longitude: float


@dataclass(frozen=True, kw_only=True)
class Building:
    osm: str
    city: str
    district: str
    street: str
    number: str
    block: str | None
    latitude: float
    longitude: float
    levels: int
    flats: int
    entrances: tuple[Entrance, ...]
    # "osm": entrances and apartment ranges are mapped in OSM; "estimated": derived from
    # the real number of floors and apartments.
    entrance_source: str

    @property
    def house(self) -> str:
        return self.number if self.block is None else f"{self.number}, {self.block}"

    def apartment(self, index: int) -> tuple[Entrance, int, int]:
        """A real apartment of this building: its entrance, number and floor.

        ``index`` is any non-negative integer; it is folded into the building's apartments.
        """
        apartment_count = sum(e.last_apartment - e.first_apartment + 1 for e in self.entrances)
        offset = index % apartment_count
        for entrance in self.entrances:
            size = entrance.last_apartment - entrance.first_apartment + 1
            if offset < size:
                per_floor = max(1, math.ceil(size / self.levels))
                floor = min(self.levels, offset // per_floor + 1)
                return entrance, entrance.first_apartment + offset, floor
            offset -= size
        raise AssertionError("unreachable")


def _building(row: dict) -> Building:
    return Building(
        osm=row["osm"],
        city=row["city"],
        district=row["district"],
        street=row["street"],
        number=row["number"],
        block=row.get("block"),
        latitude=row["lat"],
        longitude=row["lon"],
        levels=row["levels"],
        flats=row["flats"],
        entrances=tuple(
            Entrance(
                number=e["ref"],
                first_apartment=e["flats"][0],
                last_apartment=e["flats"][1],
                latitude=e.get("lat", row["lat"]),
                longitude=e.get("lon", row["lon"]),
            )
            for e in row["entrances"]
        ),
        entrance_source=row["entrance_source"],
    )


@cache
def reference() -> dict:
    return json.loads(BUILDINGS_FILE.read_text(encoding="utf-8"))


@cache
def buildings_by_district() -> dict[str, tuple[Building, ...]]:
    grouped: dict[str, list[Building]] = {}
    for row in reference()["buildings"]:
        grouped.setdefault(row["district"], []).append(_building(row))
    return {name: tuple(rows) for name, rows in grouped.items()}


def district_buildings(district: str) -> tuple[Building, ...]:
    return buildings_by_district().get(district, ())

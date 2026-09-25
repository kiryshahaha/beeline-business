"""Split the free-text source address into the directory levels city/street/building.

The files write one address in many ways («ул.Учебная», «Учебная ул.», «д. 3/1к2»,
«д 83с 4»). Street types are brought to one spelling so the same street is
not stored twice. The raw text stays in the provenance record; an address that does not
fit these forms is rejected with its row, never guessed.
"""

import re
from dataclasses import dataclass

STREET_TYPES = {
    "ул": "ул.",
    "улица": "ул.",
    "пр-кт": "пр-кт",
    "проспект": "пр-кт",
    "просп": "пр-кт",
    "пр-зд": "проезд",
    "проезд": "проезд",
    "пер": "пер.",
    "переулок": "пер.",
    "наб": "наб.",
    "набережная": "наб.",
    "б-р": "б-р",
    "бульвар": "б-р",
    "ш": "ш.",
    "шоссе": "ш.",
    "пл": "пл.",
    "площадь": "пл.",
    "туп": "туп.",
    "тупик": "туп.",
}
_TYPE = "|".join(sorted((re.escape(t) for t in STREET_TYPES), key=len, reverse=True))
PREFIX_TYPE = re.compile(rf"^(?P<type>{_TYPE})\.?\s*(?P<name>\S.*)$", re.IGNORECASE)
SUFFIX_TYPE = re.compile(rf"^(?P<name>.*\S)\s+(?P<type>{_TYPE})\.?$", re.IGNORECASE)
APARTMENT = re.compile(r",?\s*кв\.?\s*(?P<apartment>[0-9A-Za-zА-Яа-яЁё/\-]+)\s*$", re.IGNORECASE)
HOUSE_MARK = re.compile(r"(?:^|[\s,])д\.?\s*(?=\S)", re.IGNORECASE)
HOUSE = re.compile(
    r"^(?P<number>\d+(?:/\d+)?(?:[А-ЯЁA-Z]|[а-яёa-z](?!\d))?)"
    r"(?:\s*(?P<kind>корп\.?|к|стр\.?|с)\s*(?P<block>[0-9A-Za-zА-Яа-яЁё]+))?$",
    re.IGNORECASE,
)
BLOCK_ONLY = re.compile(r"^(?P<kind>корп\.?|к)\s*(?P<block>[0-9A-Za-zА-Яа-яЁё]+)$", re.IGNORECASE)
QUARTER = re.compile(r"\s+(?P<quarter>квартал\s+\S+)$", re.IGNORECASE)
REGION = re.compile(r"^(?:(?:обл\.?\s*)?московская область|мо)\s*,\s*", re.IGNORECASE)
CITY_PATTERNS = (
    re.compile(r"^г\.?\s*город\s+(?P<city>[А-ЯЁ][а-яё\-]+)[,\s]+", re.IGNORECASE),
    re.compile(r"^город\s+(?P<city>[А-ЯЁ][а-яё\-]+)[,\s]+", re.IGNORECASE),
    re.compile(r"^г\.?\s*(?P<city>[А-ЯЁ][а-яё\-]+)[,\s]+"),
    re.compile(r"^(?P<city>Москва)[,\s]+"),
    re.compile(r"^(?P<city>[А-ЯЁ][а-яё\-]+),\s*"),
)


@dataclass(frozen=True)
class ParsedAddress:
    city: str
    street: str
    building_number: str
    block: str | None
    apartment: str | None


def _street(text: str) -> str:
    parts = [part.strip() for part in text.split(",") if part.strip()]
    result = []
    for part in parts:
        for pattern in (PREFIX_TYPE, SUFFIX_TYPE):
            match = pattern.match(part)
            if match:
                kind = STREET_TYPES[match["type"].lower()]
                name = match["name"].strip(" .")
                part = f"{kind} {name}"
                break
        else:
            part = re.sub(r"^([а-яё\-]+)\.(\S)", r"\1. \2", part)
        result.append(part)
    return ", ".join(result)


def parse_address(text: str) -> ParsedAddress | None:
    value = " ".join(text.replace("\xa0", " ").split())
    apartment = None
    if match := APARTMENT.search(value):
        apartment, value = match["apartment"], value[: match.start()].rstrip(" ,")
    marks = list(HOUSE_MARK.finditer(value))
    if not marks:
        return None
    before, house = value[: marks[-1].start()].rstrip(" ,"), value[marks[-1].end() :].strip()
    number = block = None
    if match := HOUSE.match(house):
        number = match["number"]
        if match["block"]:
            kind = "корп." if match["kind"].lower().startswith("к") else "стр."
            block = f"{kind} {match['block']}"
    elif (match := BLOCK_ONLY.match(house)) and (quarter := QUARTER.search(before)):
        # «б-р.Тестовый Квартал 12а, д. к3»: the quarter is the house, «к3» its block.
        number, block = quarter["quarter"].lower(), f"корп. {match['block']}"
        before = before[: quarter.start()]
    if number is None:
        return None
    before = REGION.sub("", before)
    for pattern in CITY_PATTERNS:
        if match := pattern.match(before):
            city, rest = match["city"].capitalize(), before[match.end() :]
            break
    else:
        return None
    street = _street(rest)
    if not street:
        return None
    return ParsedAddress(city, street, number, block, apartment)

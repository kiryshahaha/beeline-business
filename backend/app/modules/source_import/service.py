"""Organizer file import: parse, geocode outside the transaction, apply in one transaction.

Two kinds of files come per area. «Синтетические данные» (demand) is the day to plan:
every row becomes a ticket, the office below the table becomes the start point.
«Контрольное распределение» (control) is how the organizer's dispatchers really split the
same visits between brigades and what happened to them: it is stored as a baseline and a
replay timeline, never as our assignments, so the planner still gets the whole morning.
"""

import hashlib
import json
import re
import secrets
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any

from sqlalchemy.orm import Session

from app.core.planning_guard import lock_planning_mutation
from app.core.security import hash_password
from app.modules.locations.schemas import LocationCreate
from app.modules.locations.service import resolve_location_id
from app.modules.source_import import classify, repository
from app.modules.source_import.addresses import APARTMENT, ParsedAddress, parse_address
from app.modules.source_import.geocoding import MAX_ADDRESSES, GeocodeResult
from app.modules.source_import.profile import (
    ALIASES,
    MOSCOW,
    SourceFile,
    SourceRow,
    dataset_from_filename,
    normalize,
    parse_moment,
    read_source,
)
from app.modules.tickets.schemas import TicketCreate
from app.modules.tickets.service import create_ticket
from app.modules.users import repository as users_repository
from app.modules.users.enums import TransportType

OFFICE_DISTRICT = "Не указан"
TRANSLIT = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


class SourceImportError(Exception):
    def __init__(self, status: int, code: str, message: str, **details: Any):
        super().__init__(message)
        self.status = status
        self.detail = {"code": code, "message": message, **details}


@dataclass
class ImportOptions:
    actor_id: int
    kind: str | None = None
    dataset: str | None = None
    dry_run: bool = True
    geocode: bool = False
    workshift_start: time = time(9)
    workshift_end: time = time(22)
    transport_type: TransportType = TransportType.CAR


@dataclass
class Prepared:
    row: SourceRow
    external_id: str
    content_sha256: str
    errors: list[dict] = field(default_factory=list)
    start: datetime | None = None
    end: datetime | None = None
    work_type: str | None = None
    status: str | None = None
    address: ParsedAddress | None = None

    def reject(self, code: str, column: str | None, message: str) -> None:
        self.errors.append({"code": code, "column": column, "message": message})

    @property
    def value(self):
        return self.row.values


def area_code(dataset: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", normalize(dataset).translate(TRANSLIT)).strip("-")
    if not slug:
        slug = hashlib.sha256(dataset.encode()).hexdigest()[:12]
    return f"source-{slug}"[:50]


def _content_sha256(row: SourceRow) -> str:
    payload = json.dumps(row.raw, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _prepare(source: SourceFile, kind: str, catalog: dict, warnings: list) -> list[Prepared]:
    prepared, seen = [], {}
    titles = source.columns
    for row in source.rows:
        item = Prepared(row, row.values["external_id"], _content_sha256(row))
        visits = seen.setdefault(item.external_id, [])
        if not item.external_id:
            item.reject("missing_external_id", titles["external_id"], "Нет номера заявки")
        elif any(sha == item.content_sha256 for _, sha in visits):
            first = next(number for number, sha in visits if sha == item.content_sha256)
            item.reject("duplicate_row", titles["external_id"], f"Строка повторяет строку {first}")
        elif visits:
            # One ticket, another visit (e.g. rescheduled): every row is a visit (M21).
            item.external_id = f"{item.external_id}#{len(visits) + 1}"
            warnings.append(
                {
                    "sheet": row.sheet,
                    "row": row.number,
                    "message": f"Номер заявки повторяется со строкой {visits[0][0]}: "
                    f"строка загружена как визит {item.external_id}",
                }
            )
        if item.external_id and not item.errors:
            visits.append((row.number, item.content_sha256))
        for key in ("start", "end"):
            column = f"window_{key}"
            try:
                setattr(item, key, parse_moment(item.value[column]))
            except ValueError as error:
                item.reject("invalid_time", titles[column], str(error))
        if item.start and item.end and item.end <= item.start:
            item.reject("invalid_window", titles["window_end"], "Окончание окна не позже начала")
        code = classify.work_type_code(item.value["bk_type"])
        if code is None:
            item.reject(
                "unknown_source_type",
                titles["bk_type"],
                f"Тип заявки BK «{item.value['bk_type']}» не сопоставлен с видом работ "
                f"(версия соответствий {classify.MAPPING_VERSION})",
            )
        elif code not in catalog:
            item.reject(
                "unknown_work_type", titles["bk_type"], f"В справочнике нет вида работ {code}"
            )
        else:
            item.work_type = code
        if not item.value["district"]:
            item.reject("missing_district", titles["district"], "Не указан район")
        item.address = parse_address(item.value["address"])
        if item.address is None:
            item.reject(
                "address_unparsed",
                titles["address"],
                "Адрес не удалось разобрать на город, улицу и дом",
            )
        if kind == "control":
            item.status = classify.source_status(item.value.get("bk_status", ""))
            if item.status is None:
                item.reject(
                    "unknown_source_status",
                    titles["bk_status"],
                    f"Статус BK «{item.value.get('bk_status', '')}» не сопоставлен",
                )
        prepared.append(item)
    return prepared


def _rejection(item: Prepared, error: dict) -> dict:
    return {
        "sheet": item.row.sheet,
        "row": item.row.number,
        "external_id": item.external_id or None,
        **error,
    }


def _record(item: Prepared, import_id: int, area_id: int, kind: str, outcome: str, **refs) -> dict:
    error = item.errors[0] if item.errors else {}
    return {
        "import_id": import_id,
        "service_area_id": area_id,
        "kind": kind,
        "external_id": item.external_id,
        "sheet": item.row.sheet,
        "row_number": item.row.number,
        "bk_type": item.value.get("bk_type") or None,
        "bk_status": item.value.get("bk_status") or None,
        "hd_type": item.value.get("hd_type") or None,
        "raw": item.row.raw,
        "content_sha256": item.content_sha256,
        "ticket_id": refs.get("ticket_id"),
        "worker_id": refs.get("worker_id"),
        "address_id": refs.get("address_id"),
        "outcome": outcome,
        "reason_code": error.get("code"),
        "reason": error.get("message"),
    }


def _address_status(known, result: GeocodeResult | None) -> dict:
    if result is not None and result.status in ("geocoded", "ambiguous"):
        return {
            "status": result.status,
            "source": "geoapify",
            "confidence": result.confidence,
            "candidate_latitude": result.latitude if result.status == "ambiguous" else None,
            "candidate_longitude": result.longitude if result.status == "ambiguous" else None,
            "latitude": result.latitude if result.status == "geocoded" else None,
            "longitude": result.longitude if result.status == "geocoded" else None,
        }
    if known is not None:
        # A repeated import without geocoding keeps what was found or reviewed before.
        return {
            "status": known["status"],
            "source": known["source"],
            "confidence": known["confidence"],
            "candidate_latitude": known["candidate_latitude"],
            "candidate_longitude": known["candidate_longitude"],
            "latitude": None,
            "longitude": None,
        }
    return {
        "status": "unresolved",
        "source": None,
        "confidence": None,
        "candidate_latitude": None,
        "candidate_longitude": None,
        "latitude": None,
        "longitude": None,
    }


class _Addresses:
    """Resolve each distinct address text once per import and remember its status."""

    def __init__(self, session, area_id, known, geocoded):
        self.session, self.area_id = session, area_id
        self.known, self.geocoded = known, geocoded
        self.cache: dict[str, tuple[int, int, str]] = {}

    def resolve(self, raw: str, parsed: ParsedAddress, district: str) -> tuple[int, int, str]:
        if raw in self.cache:
            return self.cache[raw]
        state = _address_status(self.known.get(raw), self.geocoded.get(raw))
        location_id = resolve_location_id(
            self.session,
            LocationCreate(
                city=parsed.city,
                district=district,
                street=parsed.street,
                building_number=parsed.building_number,
                block=parsed.block,
                apartment=parsed.apartment,
            ),
        )
        if state["latitude"] is not None:
            current = repository.location_coordinates(self.session, location_id)
            # A manual or earlier confident point is never replaced by the geocoder.
            if current["latitude"] is None:
                repository.set_location_coordinates(
                    self.session, location_id, state["latitude"], state["longitude"]
                )
        address_id = repository.upsert_address(
            self.session,
            {
                "service_area_id": self.area_id,
                "raw_address": raw,
                "location_id": location_id,
                **{k: state[k] for k in ("status", "source", "confidence")},
                "candidate_latitude": state["candidate_latitude"],
                "candidate_longitude": state["candidate_longitude"],
            },
        )
        self.cache[raw] = (location_id, address_id, state["status"])
        return self.cache[raw]


def _ticket_values(item: Prepared, work_type, area_id: int, location_id: int) -> dict:
    extra = [f"{title}: {item.row.raw[title]}" for title in item.row.raw if item.row.raw[title]]
    return {
        "location_id": location_id,
        "service_area_id": area_id,
        "title": f"{item.value['bk_type']}: {item.value.get('hd_type') or 'без типа HD'}"[:200],
        "description": "Строка исходной выгрузки. " + "; ".join(extra),
        "work_type_id": work_type["id"],
        "work_type": work_type["name"],
        "category": work_type["category"],
        "priority": work_type["default_priority"],
        # The file has no receipt time: the window start is the earliest known moment.
        "received_at": item.start,
        "visit_window_start": item.start,
        "visit_window_end": item.end,
        "estimated_duration_minutes": work_type["work_minutes"] + work_type["documents_minutes"],
    }


def _apply_demand(session, source, prepared, options, area, context, import_id) -> dict:
    report: dict = {"rejected": [], "warnings": []}
    parsed_office = parse_address(source.office_address)
    if parsed_office is None:
        raise SourceImportError(
            422,
            "office_address_unparsed",
            f"Адрес офиса «{source.office_address}» не удалось разобрать",
            row=source.office_row,
        )
    addresses = _Addresses(session, area["id"], context["known"], context["geocoded"])
    office_location, _, office_status = addresses.resolve(
        source.office_address, parsed_office, OFFICE_DISTRICT
    )
    office_name = f"Офис участка {area['name']}"
    office = repository.find_office(session, office_name)
    if office is None:
        office_id = repository.add_office(session, office_name, office_location)
    else:
        office_id = office["id"]
        if office["location_id"] != office_location:
            report["warnings"].append(
                {"row": source.office_row, "message": "Адрес офиса отличается от сохранённого"}
            )
    catalog = context["catalog"]
    existing = repository.find_records(session, area["id"], "demand")
    counts = Counter()
    categories, coordinates = Counter(), Counter()
    for item in prepared:
        counts["read"] += 1
        record = existing.get(item.external_id)
        if item.errors:
            counts["rejected"] += 1
            report["rejected"] += [_rejection(item, error) for error in item.errors]
            if item.external_id and not any(e["code"] == "duplicate_row" for e in item.errors):
                repository.save_record(
                    session, _record(item, import_id, area["id"], "demand", "rejected")
                )
            continue
        work_type = catalog[item.work_type]
        location_id, address_id, status = addresses.resolve(
            item.value["address"], item.address, item.value["district"]
        )
        coordinates[status] += 1
        values = _ticket_values(item, work_type, area["id"], location_id)
        if record is not None and record["ticket_id"] is not None:
            if record["content_sha256"] == item.content_sha256:
                outcome = "unchanged"
            else:
                state = repository.ticket_state(session, record["ticket_id"])
                if state["lifecycle_state"] != "waiting_assignment" or state["assigned"]:
                    item.reject(
                        "ticket_in_work",
                        None,
                        "Заявка уже в работе: изменения строки не применены",
                    )
                    counts["rejected"] += 1
                    report["rejected"].append(_rejection(item, item.errors[0]))
                    repository.save_record(
                        session,
                        _record(
                            item,
                            import_id,
                            area["id"],
                            "demand",
                            "rejected",
                            ticket_id=record["ticket_id"],
                            address_id=address_id,
                        ),
                    )
                    continue
                repository.update_ticket(session, record["ticket_id"], values)
                outcome = "updated"
            ticket_id = record["ticket_id"]
        else:
            ticket = create_ticket(
                session,
                TicketCreate(**{k: v for k, v in values.items() if k != "work_type"}),
                actor_id=options.actor_id,
                idempotency_key=f"source:{area['id']}:{item.external_id}",
            )
            ticket_id, outcome = ticket.id, "created"
        counts[outcome] += 1
        categories[work_type["category"]] += 1
        repository.save_record(
            session,
            _record(
                item,
                import_id,
                area["id"],
                "demand",
                outcome,
                ticket_id=ticket_id,
                address_id=address_id,
            ),
        )
    used_types = sorted({catalog[i.work_type]["id"] for i in prepared if i.work_type})
    if missing := repository.unconfigured_work_types(session, used_types):
        report["warnings"].append(
            {
                "message": "Для видов работ не настроены требования планирования: заявки "
                "загружены, но в расчёт не попадут до настройки /api/v1/work-types",
                "work_types": missing,
            }
        )
    seen = {item.external_id for item in prepared}
    absent = sorted(external for external in existing if external not in seen)
    if absent:
        report["warnings"].append(
            {
                "message": "Строки прошлой версии файла отсутствуют и не удалены",
                "external_ids": absent,
            }
        )
    report.update(
        counts={k: counts[k] for k in ("read", "created", "updated", "unchanged", "rejected")},
        by_category=dict(sorted(categories.items())),
        coordinates=dict(sorted(coordinates.items())),
        office={
            "office_id": office_id,
            "location_id": office_location,
            "address": source.office_address,
            "row": source.office_row,
            "coordinates": office_status,
        },
    )
    return report


def _key(values: dict) -> tuple:
    return (
        normalize(values.get("bk_type", "")),
        normalize(values.get("hd_type", "")),
        " ".join(values.get("window_start", "").split()),
        " ".join(values.get("window_end", "").split()),
        normalize(values.get("district", "")),
        normalize(APARTMENT.sub("", values.get("address", ""))),
    )


def _fields(raw: dict) -> dict:
    return {
        ALIASES[normalize(title)]: value
        for title, value in raw.items()
        if normalize(title) in ALIASES
    }


def _worker(session, label: str, area, office, options) -> int:
    parts = label.split()
    if len(parts) > 1 and normalize(parts[0]) == "бригада":
        name, surname = parts[0], " ".join(parts[1:])
    else:
        surname, name = parts[0], " ".join(parts[1:]) or "Исполнитель"
    digest = hashlib.sha256(normalize(label).encode()).hexdigest()[:12]
    user_id = users_repository.add_user(
        session,
        {
            "name": name[:100],
            "surname": surname[:100],
            "lastname": None,
            "username": f"src{area['id']}_{digest}",
            # The person signs in only after a dispatcher sets a known password.
            "password_hash": hash_password(secrets.token_urlsafe(48)),
            "role": "worker",
        },
    )
    users_repository.add_worker(
        session,
        {
            "user_id": user_id,
            "workshift_start": options.workshift_start,
            "workshift_end": options.workshift_end,
            "transport_type": options.transport_type.value,
            "service_area_id": area["id"],
            "stock_office_id": office["office_id"],
        },
    )
    return user_id


def _apply_control(session, source, prepared, options, area, context, import_id) -> dict:
    office = repository.latest_demand_import(session, area["id"])
    if office is None:
        raise SourceImportError(
            409,
            "demand_import_required",
            f"Сначала загрузите синтетические данные участка «{area['name']}»: "
            "контрольное распределение сопоставляется с их строками",
        )
    report: dict = {"rejected": [], "warnings": []}
    demand = [
        r
        for r in repository.find_records(session, area["id"], "demand").values()
        if r["ticket_id"] is not None and r["outcome"] != "rejected"
    ]
    by_row = {r["row_number"]: r for r in demand}
    by_key: dict[tuple, list] = {}
    for record in demand:
        by_key.setdefault(_key(_fields(record["raw"])), []).append(record)
    catalog = context["catalog"]
    tickets_category = {
        r["ticket_id"]: catalog[classify.work_type_code(_fields(r["raw"])["bk_type"])]["category"]
        for r in demand
    }
    existing = repository.find_records(session, area["id"], "control")
    brigades = repository.find_records(session, area["id"], "brigade")
    workers: dict[str, int] = {label: r["worker_id"] for label, r in brigades.items()}
    counts, statuses, by_worker, used = Counter(), Counter(), Counter(), set()
    skills: dict[int, set[str]] = {}
    for item in prepared:
        counts["read"] += 1
        match = None
        if not item.errors:
            key = _key(item.value)
            candidate = by_row.get(item.row.number)
            if candidate and candidate["id"] not in used and _key(_fields(candidate["raw"])) == key:
                match = candidate
            else:
                free = [r for r in by_key.get(key, []) if r["id"] not in used]
                match = free[0] if len(free) == 1 else None
            if match is None:
                item.reject(
                    "no_matching_demand_row",
                    None,
                    "В синтетических данных участка нет единственной строки с теми же типами, "
                    "окном, районом и адресом",
                )
        if item.errors:
            counts["rejected"] += 1
            report["rejected"] += [_rejection(item, error) for error in item.errors]
            if item.external_id and not any(e["code"] == "duplicate_row" for e in item.errors):
                repository.save_record(
                    session, _record(item, import_id, area["id"], "control", "rejected")
                )
            continue
        used.add(match["id"])
        label = " ".join(item.value.get("brigade", "").split())
        worker_id = None
        if label:
            worker_id = workers.get(label)
            if worker_id is None:
                worker_id = _worker(session, label, area, office, options)
                workers[label] = worker_id
                counts["workers_created"] += 1
                brigade_row = SourceRow(
                    item.row.sheet, item.row.number, {}, {source.columns["brigade"]: label}
                )
                brigade = Prepared(brigade_row, label, _content_sha256(brigade_row))
                repository.save_record(
                    session,
                    _record(
                        brigade, import_id, area["id"], "brigade", "created", worker_id=worker_id
                    ),
                )
            skills.setdefault(worker_id, set()).add(
                classify.SKILL_BY_CATEGORY[tickets_category[match["ticket_id"]]]
            )
            by_worker[worker_id] += 1
        record = existing.get(item.external_id)
        outcome = (
            "created"
            if record is None
            else "unchanged"
            if record["content_sha256"] == item.content_sha256
            else "updated"
        )
        counts[outcome] += 1
        statuses[item.status] += 1
        repository.save_record(
            session,
            _record(
                item,
                import_id,
                area["id"],
                "control",
                outcome,
                ticket_id=match["ticket_id"],
                worker_id=worker_id,
            ),
        )
    for worker_id, names in skills.items():
        for skill in sorted(names):
            users_repository.assign_worker_skill(
                session, worker_id, users_repository.ensure_skill(session, skill)
            )
    report.update(
        counts={k: counts[k] for k in ("read", "created", "updated", "unchanged", "rejected")},
        baseline={
            "workers": len(by_worker),
            "workers_created": counts["workers_created"],
            "assigned_rows": sum(by_worker.values()),
            "rows_without_brigade": counts["read"] - counts["rejected"] - sum(by_worker.values()),
            "rows_by_worker": {str(k): v for k, v in sorted(by_worker.items())},
            "skills_by_worker": {str(k): sorted(v) for k, v in sorted(skills.items())},
        },
        replay={
            "statuses": dict(sorted(statuses.items())),
            "final": sum(n for s, n in statuses.items() if s in classify.FINAL_STATUSES),
        },
    )
    return report


def import_source(
    session: Session, content: bytes, filename: str, options: ImportOptions, geocoder
) -> dict:
    source = read_source(content, filename)
    kind = options.kind or ("control" if source.is_control else "demand")
    if kind == "control" and not {"brigade", "bk_status"} <= set(source.columns):
        raise SourceImportError(
            422,
            "control_columns_missing",
            "В контрольном распределении нужны столбцы «Статус BK» и «Бригада»",
        )
    if kind == "demand" and source.office_address is None:
        raise SourceImportError(
            422,
            "office_address_missing",
            "Под таблицей нет строки «Адрес офиса»: без неё нет точки старта участка",
        )
    dataset = " ".join((options.dataset or dataset_from_filename(filename)).split())
    if not dataset:
        raise SourceImportError(
            422, "dataset_missing", "Не удалось определить участок по имени файла"
        )
    code = area_code(dataset)
    with session.begin():
        catalog = repository.work_types_by_code(session)
        area = repository.find_service_area(session, code)
        repeated: list[dict] = []
        prepared = _prepare(source, kind, catalog, repeated)
        raws = sorted({i.value["address"] for i in prepared if not i.errors})
        if kind == "demand":
            raws.append(source.office_address)
        known = repository.find_addresses(session, area["id"], raws) if area else {}
    pending = [
        raw
        for raw in dict.fromkeys(raws)
        if raw not in known or known[raw]["status"] == "unresolved"
    ]
    geocoded: dict[str, GeocodeResult] = {}
    if kind == "demand" and options.geocode and not options.dry_run and pending:
        if geocoder is None:
            raise SourceImportError(
                503, "geocoding_not_configured", "Геокодер не настроен (GEOAPIFY_API_KEY)"
            )
        geocoded = geocoder.geocode(pending[:MAX_ADDRESSES])
    moments = [i.start for i in prepared if i.start]
    work_dates = sorted({m.date() for m in moments})
    with session.begin():
        lock_planning_mutation(session)
        savepoint = session.begin_nested()
        try:
            area = repository.find_service_area(session, code)
            area = (
                dict(area) if area else {"id": repository.add_service_area(session, code, dataset)}
            )
            area.setdefault("name", dataset)
            import_id = repository.add_import(
                session,
                {
                    "service_area_id": area["id"],
                    "kind": kind,
                    "filename": filename[:255] or "source",
                    "file_sha256": source.sha256,
                    "mapping_version": classify.MAPPING_VERSION,
                    "work_date": work_dates[0] if work_dates else None,
                    "office_id": None,
                    "created_by": options.actor_id,
                },
            )
            context = {"catalog": catalog, "known": known, "geocoded": geocoded}
            apply = _apply_demand if kind == "demand" else _apply_control
            result = apply(session, source, prepared, options, area, context, import_id)
            report = {
                "import_id": None if options.dry_run else import_id,
                "dry_run": options.dry_run,
                "kind": kind,
                "dataset": dataset,
                "service_area": {"id": area["id"], "code": code},
                "file": {
                    "name": filename,
                    "sha256": source.sha256,
                    "encoding": source.encoding,
                    "delimiter": source.delimiter,
                    "sheets": source.sheets,
                    "columns": source.columns,
                    "unknown_columns": source.unknown_columns,
                },
                "mapping_version": classify.MAPPING_VERSION,
                "work_date": work_dates[0].isoformat() if work_dates else None,
                **result,
            }
            if len(work_dates) > 1:
                report["warnings"].append(
                    {
                        "message": "В файле окна нескольких дат",
                        "dates": [d.isoformat() for d in work_dates],
                    }
                )
            report["warnings"] = source.warnings + repeated + report["warnings"]
            if kind == "demand" and (not options.geocode or options.dry_run):
                report["pending_geocoding"] = len(pending)
            office_id = result.get("office", {}).get("office_id")
            repository.finish_import(session, import_id, report, office_id)
            if options.dry_run:
                savepoint.rollback()
            else:
                savepoint.commit()
        except BaseException:
            if savepoint.is_active:
                savepoint.rollback()
            raise
    return report


def replay(session: Session, area_id: int) -> dict:
    """What the control day did with each visit; the file has no event times, only windows."""
    with session.begin():
        rows = repository.replay_rows(session, area_id)
    events = []
    for row in rows:
        status = classify.source_status(row["bk_status"] or "")
        final = status in classify.FINAL_STATUSES
        events.append(
            {
                "external_id": row["external_id"],
                "row": row["row_number"],
                "ticket_id": row["ticket_id"],
                "worker_id": row["worker_id"],
                "source_status": row["bk_status"],
                "status": status,
                "final": final,
                # Final outcomes happened by the end of the window at the latest; other statuses
                # describe the moment the file was exported, which the file does not state.
                "at": row["visit_window_end"].astimezone(MOSCOW).isoformat() if final else None,
                "time_basis": "visit_window_end" if final else "export_snapshot",
            }
        )
    return {
        "service_area_id": area_id,
        "events": events,
        "statuses": dict(sorted(Counter(e["status"] for e in events).items())),
    }


def review_address(
    session: Session, address_id: int, latitude, longitude, reviewer_id: int
) -> dict:
    with session.begin():
        lock_planning_mutation(session)
        address = repository.lock_address(session, address_id)
        if address is None:
            raise SourceImportError(404, "address_not_found", "Адрес не найден")
        repository.set_location_coordinates(session, address["location_id"], latitude, longitude)
        repository.review_address(session, address_id, reviewer_id)
        [row] = [r for r in repository.list_addresses(session, None, None) if r["id"] == address_id]
        return dict(row)

"""One coherent row of every runtime journal for exchange-format tests.

Synthetic packages hold reference data, people, demand and closed history only: routes,
day plans, execution events, equipment on hand and source-file provenance are written by
the running system. Format tests still need every exchanged table filled, so they add
these samples to a generated package explicitly.
"""

import hashlib
import json
from datetime import datetime, time, timedelta

from app.modules.data_exchange.registry import TABLES
from app.modules.routing.schemas import RouteGeoJSON


def _append(tables: dict, name: str, values: dict) -> None:
    """Fill omitted columns the way the synthetic generator does."""
    for column in TABLES[name].columns:
        if column.name in values:
            continue
        if column.default is not None and getattr(column.default, "arg", None) is not None:
            arg = column.default.arg
            values[column.name] = arg() if callable(arg) else arg
        elif column.nullable:
            values[column.name] = None
    tables[name].append(values)


def add_journal_samples(tables: dict, *, seed: int) -> dict:
    tickets = {row["id"]: row for row in tables["tickets"]}
    locations = {row["id"]: row for row in tables["locations"]}
    ticket = tickets[1]
    day = ticket["visit_window_start"].date()
    stamp = ticket["received_at"]
    area_id = ticket["service_area_id"]
    worker = next(w for w in tables["workers"] if w["service_area_id"] == area_id)
    worker_id = worker["user_id"]
    office_id = next(o["id"] for o in tables["offices"] if o["service_area_id"] == area_id)
    office_location = next(o["location_id"] for o in tables["offices"] if o["id"] == office_id)
    appliance_id = tables["appliances"][0]["id"]
    _append(
        tables,
        "work_events",
        {
            "id": 1,
            "event_type": "new_ticket",
            "ticket_id": ticket["id"],
            "worker_id": worker_id,
            "service_area_id": area_id,
            "route_date": day,
            "occurred_at": stamp,
            "recorded_at": stamp,
            "actor_id": 1,
            "previous_state": None,
            "new_state": "waiting_assignment",
            "before_revision": None,
            "after_revision": 1,
            "idempotency_key": f"sample-{seed}-ticket-1",
            "payload": {"ticket_id": ticket["id"]},
        },
    )
    _append(
        tables,
        "worker_day_states",
        {
            "id": 1,
            "worker_id": worker_id,
            "service_area_id": area_id,
            "route_date": day,
            "revision": 1,
            "available": True,
            "last_location_id": office_location,
            "current_destination_id": None,
            "created_at": stamp,
            "updated_at": stamp,
        },
    )
    _append(
        tables,
        "equipment_movements",
        {
            "id": 1,
            "ticket_id": ticket["id"],
            "execution_cycle": 1,
            "appliance_id": appliance_id,
            "office_id": office_id,
            "event_id": 1,
            "movement": "consume",
            "quantity": 1,
            "created_at": stamp,
        },
    )
    _append(
        tables,
        "day_plan_revisions",
        {
            "id": 1,
            "service_area_id": area_id,
            "route_date": day,
            "revision": 1,
            "previous_revision": None,
            "superseded_at": None,
            "superseded_by_revision": None,
            "plan_id": None,
            "event_id": 1,
            "actor_id": 1,
            "reason": "plan_applied",
            "fingerprint": hashlib.sha256(f"sample-{seed}".encode()).hexdigest(),
            "diff": {},
            "result": {},
            "plan_state": {},
            "roster": [
                {
                    "worker_id": worker_id,
                    "service_area_id": area_id,
                    "workshift_start": worker["workshift_start"].isoformat(),
                    "workshift_end": worker["workshift_end"].isoformat(),
                    "source": "published",
                }
            ],
            "is_current": True,
            "effective_at": stamp,
            "created_at": stamp,
        },
    )
    # Equipment on hand: the first allocation of an assigned visit was issued (T08); a
    # single-day package has nobody assigned yet, so the area's engineer holds it.
    assignees = {t["id"]: t["assigned_worker_id"] for t in tables["tickets"]}
    allocation = next(
        (a for a in tables["ticket_appliances"] if assignees[a["ticket_id"]]),
        next(a for a in tables["ticket_appliances"] if a["office_id"] == office_id),
    )
    holder = assignees[allocation["ticket_id"]] or worker_id
    _append(
        tables,
        "worker_appliances",
        {
            "worker_id": holder,
            "appliance_id": allocation["appliance_id"],
            "quantity": allocation["quantity"],
            "updated_at": stamp,
        },
    )
    _append(
        tables,
        "appliance_operations",
        {
            "id": 1,
            "operation_key": f"sample-{seed}-issue-1",
            "kind": "issue",
            "worker_id": holder,
            "ticket_id": None,
            "actor_id": 1,
            "reason": None,
            "request": {"worker_id": holder, "date": day.isoformat()},
            "recorded_at": stamp,
        },
    )
    _append(
        tables,
        "appliance_movements",
        {
            "id": 1,
            "operation_id": 1,
            "appliance_id": allocation["appliance_id"],
            "quantity": allocation["quantity"],
            "ticket_id": allocation["ticket_id"],
            "from_office_id": allocation["office_id"],
            "from_worker_id": None,
            "to_office_id": None,
            "to_worker_id": holder,
        },
    )
    _append(
        tables,
        "ticket_appliance_states",
        {
            "ticket_id": allocation["ticket_id"],
            "appliance_id": allocation["appliance_id"],
            "holder_worker_id": holder,
            "consumed_operation_id": None,
        },
    )
    # Provenance of one row of an organizer's day file and one brigade (T11).
    location = locations[ticket["location_id"]]
    building = next(b for b in tables["buildings"] if b["id"] == location["building_id"])
    street = next(s["name"] for s in tables["streets"] if s["id"] == building["street_id"])
    raw_address = f"Город Москва, {street}, д. {building['number']}" + (
        f", кв. {location['apartment']}" if location["apartment"] else ""
    )
    raw_row = {"Заявка": f"S{seed}-1", "Тип заявки BK": "Локальная заявка", "Адрес": raw_address}
    _append(
        tables,
        "source_imports",
        {
            "id": 1,
            "service_area_id": area_id,
            "kind": "demand",
            "filename": "Восток Синтетические данные.csv",
            "file_sha256": hashlib.sha256(f"source-{seed}".encode()).hexdigest(),
            "mapping_version": 1,
            "work_date": day,
            "office_id": office_id,
            "report": {"counts": {"read": 1, "created": 1}},
            "created_by": 1,
            "created_at": stamp,
        },
    )
    _append(
        tables,
        "source_addresses",
        {
            "id": 1,
            "service_area_id": area_id,
            "raw_address": raw_address,
            "location_id": ticket["location_id"],
            "status": "manual",
            "source": "manual",
            "reviewed_by": 1,
            "updated_at": stamp,
        },
    )
    for record_id, kind, external_id, ticket_id, record_worker in (
        (1, "demand", f"S{seed}-1", ticket["id"], None),
        (2, "brigade", f"Бригада {seed}", None, holder),
    ):
        _append(
            tables,
            "source_records",
            {
                "id": record_id,
                "import_id": 1,
                "service_area_id": area_id,
                "kind": kind,
                "external_id": external_id,
                "row_number": 2,
                "bk_type": "Локальная заявка" if kind == "demand" else None,
                "hd_type": "Работа с кабелем" if kind == "demand" else None,
                "raw": raw_row,
                "content_sha256": hashlib.sha256(json.dumps(raw_row).encode()).hexdigest(),
                "ticket_id": ticket_id,
                "worker_id": record_worker,
                "address_id": 1 if kind == "demand" else None,
                "outcome": "created",
                "created_at": stamp,
                "updated_at": stamp,
            },
        )
    # A saved route: the first request of the day, then back to the office.
    start = datetime.combine(day, time(9), stamp.tzinfo)
    points, features = [], []
    for sequence, location_id in enumerate((ticket["location_id"], office_location), 1):
        point = locations[location_id]
        position = [point["longitude"], point["latitude"]]
        points.append(position)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": position},
                "properties": {
                    "location_id": location_id,
                    "ticket_id": None,
                    "sequence": sequence,
                    "arrival_at": (start + timedelta(minutes=40 * sequence)).isoformat(),
                    "service_start_at": (start + timedelta(minutes=40 * sequence)).isoformat(),
                    "service_end_at": (start + timedelta(minutes=40 * sequence + 30)).isoformat(),
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
            "properties": {"worker_id": worker_id, "route_date": day, "route_number": 1},
            "features": features,
        }
    ).model_dump(mode="json")
    _append(
        tables,
        "routes",
        {
            "id": 1,
            "worker_id": worker_id,
            "route_date": day,
            "route_number": 1,
            "geojson": geojson,
            "created_at": stamp,
        },
    )
    return tables

"""Convert domain restrictions to eligible vehicles and service-start windows."""

import math
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.modules.planning.errors import PlanningError
from app.modules.planning.policy import snapshot_policy

MOSCOW = ZoneInfo("Europe/Moscow")
PROFILES = {
    "car": "drive",
    "walking": "walk",
    "bicycle": "bicycle",
    "public_transport": "approximated_transit",
}


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def prepare(snapshot: dict, now: datetime) -> dict:
    policy = snapshot_policy(snapshot)
    request = snapshot["request"]
    epoch = datetime.combine(datetime.fromisoformat(request["route_date"]).date(), time(), MOSCOW)
    missing = {
        "ticket_ids": sorted(set(request["ticket_ids"]) - {t["id"] for t in snapshot["tickets"]}),
        "worker_ids": sorted(
            set(request["worker_ids"]) - {w["user_id"] for w in snapshot["workers"]}
        ),
    }
    if any(missing.values()):
        raise PlanningError("unknown_ids", **missing)
    locations = {x["id"]: x for x in snapshot["locations"]}
    offices = {x["id"]: x for x in snapshot["offices"]}
    brigades = {x["id"]: x for x in snapshot["brigades"]}
    members = {x["worker_id"]: x["brigade_id"] for x in snapshot["members"]}
    roles = {x["id"]: x["role"] for x in snapshot["roles"]}
    busy = {x["id"]: x for x in snapshot["busy_tickets"]}
    workers, excluded_workers = [], []
    for worker in snapshot["workers"]:
        worker = dict(worker)
        wid = worker["user_id"]
        start = datetime.combine(
            epoch.date(), time.fromisoformat(worker["workshift_start"]), MOSCOW
        )
        end = datetime.combine(epoch.date(), time.fromisoformat(worker["workshift_end"]), MOSCOW)
        if end <= start:
            end += timedelta(days=1)
        brigade = brigades.get(members.get(wid))
        office = offices.get(brigade["office_id"]) if brigade else None
        location = locations.get(office["location_id"]) if office else None
        reason = None
        if roles.get(wid) != "worker":
            reason = "invalid_worker_role"
        elif not office:
            reason = "missing_office"
        elif not location or location["latitude"] is None or location["longitude"] is None:
            reason = "missing_coordinates"
        elif start <= now:
            reason = "shift_already_started"
        elif worker["transport_type"] not in PROFILES:
            reason = "unsupported_transport_profile"
        else:
            for assignment in snapshot["assignments"]:
                job = busy.get(assignment["ticket_id"])
                if assignment["worker_id"] != wid or job is None:
                    continue
                a = dt(job["planned_start_at"] or job["visit_window_start"])
                b = dt(job["planned_end_at"] or job["visit_window_end"])
                if job["status"] == "in_progress" or (a < end and start < b):
                    reason = "worker_busy"
                    break
        if reason:
            excluded_workers.append({"worker_id": wid, "reason": reason})
            continue
        worker.update(
            {
                "office_id": office["id"],
                "location_id": location["id"],
                "profile": PROFILES[worker["transport_type"]],
                "transport_type": worker["transport_type"],
                "window": [
                    math.ceil((start - epoch).total_seconds() / 60),
                    math.floor((end - epoch).total_seconds() / 60),
                ],
                "skill_ids": {s["skill_id"] for s in snapshot["skills"] if s["worker_id"] == wid},
            }
        )
        workers.append(worker)
    horizon = max((w["window"][1] for w in workers), default=1440)
    types_by_id = {x["id"]: x for x in snapshot["work_types"]}
    types_by_name = {x["name"].strip().lower(): x for x in snapshot["work_types"]}
    rules = {x["work_type_id"]: x for x in snapshot["rules"]}
    stock = {(x["office_id"], x["appliance_id"]): x["stock"] for x in snapshot["stocks"]}
    reserved = {
        (x["office_id"], x["appliance_id"]): x["quantity"] for x in snapshot["reservations"]
    }
    appliances = {x["id"]: x for x in snapshot["appliances"]}
    tickets, unassigned = [], []
    for ticket in snapshot["tickets"]:
        ticket = dict(ticket)
        tid = ticket["id"]
        raw_wt = ticket.get("work_type")
        work_type = types_by_id.get(ticket.get("work_type_id")) or (
            types_by_name.get(raw_wt.strip().lower()) if raw_wt else None
        )
        rule = rules.get(work_type["id"]) if work_type else None
        location = locations.get(ticket["location_id"])
        allocations = [a for a in snapshot["allocations"] if a["ticket_id"] == tid]
        allocated = {a["appliance_id"]: a["quantity"] for a in allocations}
        reason = None
        if ticket["status"] != "planned":
            reason = "ticket_not_planned"
        elif any(a["ticket_id"] == tid for a in snapshot["assignments"]):
            reason = "already_assigned"
        elif not location or location["latitude"] is None or location["longitude"] is None:
            reason = "missing_coordinates"
        elif not work_type:
            reason = "unknown_work_type"
        elif not rule:
            reason = "work_requirements_not_configured"
        if reason is None:
            duration = (
                ticket["estimated_duration_minutes"]
                if rule["service_duration_source"] == "ticket_estimate"
                else work_type["work_minutes"] + work_type["documents_minutes"]
            )
            visit_start = dt(ticket["visit_window_start"])
            if ticket.get("received_at"):
                received = dt(ticket["received_at"])
                if received > visit_start:
                    visit_start = received
            visit_end = dt(ticket["visit_window_end"])
            if ticket.get("sla_deadline_at"):
                sla = dt(ticket["sla_deadline_at"])
                if sla < visit_end:
                    visit_end = sla
            window = policy.start_window(
                visit_start,
                visit_end,
                epoch,
                duration,
                horizon,
            )
            required = [
                a for a in snapshot["required_appliances"] if a["work_type_id"] == work_type["id"]
            ]
            skills = {
                s["skill_id"]
                for s in snapshot["required_skills"]
                if s["work_type_id"] == work_type["id"]
            }
            req_transport = ticket.get("required_transport_type")
            if not 0 < duration <= 2880:
                reason = "invalid_service_duration"
            elif window[0] > window[1]:
                reason = "outside_shift_horizon"
            elif any(allocated.get(a["appliance_id"], 0) < a["quantity"] for a in required):
                reason = "equipment_not_reserved"
            elif any(
                not appliances.get(a["appliance_id"], {}).get("is_active", False)
                or reserved.get((a["office_id"], a["appliance_id"]), 0)
                > stock.get((a["office_id"], a["appliance_id"]), 0)
                for a in allocations
            ):
                reason = "stock_inconsistent"
            else:
                allowed = [
                    v
                    for v, w in enumerate(workers)
                    if skills <= w["skill_ids"]
                    and (req_transport is None or w["transport_type"] == req_transport)
                    and all(a["office_id"] == w["office_id"] for a in allocations)
                    and max(window[0], w["window"][0]) <= min(window[1], w["window"][1] - duration)
                ]
                if not allowed:
                    reason = "no_eligible_worker"
                else:
                    ticket.update(
                        window=window,
                        duration=duration,
                        allowed=allowed,
                        duration_source=rule["service_duration_source"],
                        category=ticket.get("category") or work_type.get("category") or "repair",
                        priority=ticket.get("priority") or work_type.get("default_priority") or 3,
                        work_type_id=work_type["id"],
                    )
        if reason:
            unassigned.append({"ticket_id": tid, "reason": reason})
        else:
            tickets.append(ticket)

    return {
        "policy": policy,
        "epoch": epoch,
        "horizon": horizon,
        "workers": workers,
        "tickets": tickets,
        "locations": locations,
        "unassigned": unassigned,
        "excluded_workers": excluded_workers,
    }


def check_eligibility(snapshot: dict, now: datetime | None = None) -> dict:
    """Convenience helper to evaluate candidate eligibility and exclusions."""
    if now is None:
        now = datetime.min.replace(tzinfo=MOSCOW)
    return prepare(snapshot, now)


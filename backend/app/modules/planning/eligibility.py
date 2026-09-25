"""Convert domain restrictions to eligible vehicles and service-start windows."""

import math
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.modules.planning import reasons
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


def at(epoch: datetime, minutes: int) -> datetime:
    return epoch + timedelta(minutes=minutes)


def candidate_reason(
    ticket, window, duration, skills, allocations, worker, epoch, required_transport_type=None
):
    """First failed hard rule for one engineer; the order goes from qualification to time."""
    day = epoch.date()
    missing = sorted(skills - worker["skill_ids"])
    if missing:
        return reasons.missing_skill(missing, skills)
    worker_area = worker.get("service_area_id")
    ticket_area = ticket.get("service_area_id")
    if worker_area is not None and ticket_area is not None and worker_area != ticket_area:
        return reasons.service_area_mismatch(worker_area, ticket_area)
    offices = sorted({a["office_id"] for a in allocations})
    if any(office != worker["office_id"] for office in offices):
        return reasons.office_mismatch(worker["office_id"], offices)
    if required_transport_type and worker["transport_type"] != required_transport_type:
        return reasons.explain(
            "required_transport_mismatch",
            "transport",
            "Транспорт инженера не совпадает с обязательным транспортом заявки",
            constraint="required_transport_type",
            observed={"transport_type": worker["transport_type"]},
            required={"transport_type": required_transport_type},
        )
    # service_start must be in [window[0], window[1]] AND in shift;
    # service_end (start + duration) must fit within shift_end.
    lower = max(window[0], worker["window"][0])
    if lower > min(window[1], worker["window"][1]):
        return reasons.window_outside_shift(
            dt(ticket["visit_window_start"]),
            dt(ticket["visit_window_end"]),
            at(epoch, worker["window"][0]),
            at(epoch, worker["window"][1]),
            day,
        )
    if lower + duration > worker["window"][1]:
        return reasons.service_after_shift(
            at(epoch, lower), duration, at(epoch, worker["window"][1]), day
        )
    return None


def prepare(snapshot: dict, now: datetime) -> dict:
    policy = snapshot_policy(snapshot)
    request = snapshot["request"]
    epoch = datetime.combine(datetime.fromisoformat(request["route_date"]).date(), time(), MOSCOW)
    day = epoch.date()
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
    day_states = {x["worker_id"]: x for x in snapshot.get("worker_day_states", [])}
    busy = {x["id"]: x for x in snapshot["busy_tickets"]}
    workers, excluded_workers = [], []
    for worker in snapshot["workers"]:
        worker = dict(worker)
        wid = worker["user_id"]
        day_state = day_states.get(wid)
        start = datetime.combine(
            epoch.date(), time.fromisoformat(worker["workshift_start"]), MOSCOW
        )
        end = datetime.combine(epoch.date(), time.fromisoformat(worker["workshift_end"]), MOSCOW)
        if end <= start:
            end += timedelta(days=1)
        brigade = brigades.get(members.get(wid))
        office_id = worker.get("stock_office_id") or (brigade["office_id"] if brigade else None)
        office = offices.get(office_id) if office_id else None

        if day_state and day_state.get("last_location_id"):
            start_location_id = day_state["last_location_id"]
        elif worker.get("start_location_id"):
            start_location_id = worker["start_location_id"]
        elif office:
            start_location_id = office["location_id"]
        else:
            start_location_id = None

        if worker.get("end_location_id"):
            end_location_id = worker["end_location_id"]
        elif worker.get("start_location_id"):
            end_location_id = worker["start_location_id"]
        elif office:
            end_location_id = office["location_id"]
        else:
            end_location_id = start_location_id

        location = locations.get(start_location_id) if start_location_id else None
        reason = None
        if roles.get(wid) != "worker":
            reason = reasons.invalid_worker_role(roles.get(wid))
        elif day_state and not day_state["available"]:
            reason = reasons.worker_unavailable(
                dt(day_state["expected_available_at"])
                if day_state.get("expected_available_at")
                else None
            )
        elif not worker["is_on_line"]:
            reason = reasons.worker_offline()
        elif not office:
            reason = reasons.missing_office()
        elif not location or location["latitude"] is None or location["longitude"] is None:
            reason = reasons.office_without_coordinates(
                office["id"], start_location_id or office["location_id"]
            )
        elif start <= now and not (day_state and day_state.get("last_location_id")):
            reason = reasons.shift_already_started(start, now, day)
        elif day_state and day_state.get("current_ticket_id"):
            reason = (
                reasons.worker_en_route(day_state["current_ticket_id"])
                if day_state.get("current_destination_id") is not None
                else reasons.explain(
                    "worker_busy",
                    "availability",
                    "Инженер выполняет активную заявку",
                    constraint="eligible_workers=without_active_execution",
                    ids={"ticket_ids": [day_state["current_ticket_id"]]},
                )
            )
        elif worker["transport_type"] not in PROFILES:
            reason = reasons.unsupported_transport(worker["transport_type"], PROFILES)
        else:
            for assignment in snapshot["assignments"]:
                job = busy.get(assignment["ticket_id"])
                if assignment["worker_id"] != wid or job is None:
                    continue
                a = dt(job["planned_start_at"] or job["visit_window_start"])
                b = dt(job["planned_end_at"] or job["visit_window_end"])
                if job["status"] == "in_progress" or (a < end and start < b):
                    reason = reasons.worker_busy(job, a, b, day)
                    break
        if reason:
            excluded_workers.append({"worker_id": wid, "reason": reason})
            continue
        if start_location_id not in locations:
            excluded_workers.append({"worker_id": wid, "reason": "missing_last_location"})
            continue
        available_at = start
        if day_state and day_state.get("expected_available_at"):
            available_at = max(available_at, dt(day_state["expected_available_at"]))
        worker_area_id = (
            worker.get("service_area_id")
            or snapshot.get("worker_service_areas", {}).get(wid)
            or snapshot.get("service_area_id")
        )
        worker.update(
            {
                "office_id": office["id"],
                "service_area_id": worker_area_id,
                "location_id": start_location_id,
                "start_location_id": start_location_id,
                "end_location_id": end_location_id,
                "profile": PROFILES[worker["transport_type"]],
                "transport_type": worker["transport_type"],
                "window": [
                    math.ceil((available_at - epoch).total_seconds() / 60),
                    math.floor((end - epoch).total_seconds() / 60),
                ],
                "skill_ids": {s["skill_id"] for s in snapshot["skills"] if s["worker_id"] == wid},
            }
        )
        if worker["window"][0] > worker["window"][1]:
            excluded_workers.append({"worker_id": wid, "reason": "no_remaining_shift"})
            continue
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
    names = {x["id"]: x["name"] for x in snapshot["appliances"]}
    tickets, unassigned = [], []
    for ticket in snapshot["tickets"]:
        ticket = dict(ticket)
        tid = ticket["id"]
        raw_wt = ticket.get("work_type")
        raw_clean = raw_wt.strip().lower() if raw_wt else None
        if raw_clean in ("unknown", "unknown_work_type") or (
            raw_clean and "unconfigured" in raw_clean
        ):
            work_type = None
        else:
            work_type = types_by_id.get(ticket.get("work_type_id")) or (
                types_by_name.get(raw_clean) if raw_clean else None
            )
        rule = rules.get(work_type["id"]) if work_type else None
        location = locations.get(ticket["location_id"])
        allocations = [a for a in snapshot["allocations"] if a["ticket_id"] == tid]
        allocated = {a["appliance_id"]: a["quantity"] for a in allocations}
        assigned = sorted(a["worker_id"] for a in snapshot["assignments"] if a["ticket_id"] == tid)
        reason, candidates = None, []
        if ticket["status"] != "planned":
            reason = reasons.ticket_not_planned(ticket["status"])
        elif assigned:
            reason = reasons.already_assigned(assigned)
        elif not location or location["latitude"] is None or location["longitude"] is None:
            reason = reasons.ticket_without_coordinates(ticket["location_id"])
        elif not work_type:
            reason = reasons.unknown_work_type(ticket["work_type"])
        elif not rule:
            reason = reasons.requirements_not_configured(work_type)
        if reason is None:
            duration = (
                ticket["estimated_duration_minutes"]
                if rule["service_duration_source"] == "ticket_estimate"
                else work_type["work_minutes"] + work_type["documents_minutes"]
            )
            window_start = dt(ticket["visit_window_start"])
            if ticket.get("received_at"):
                received = dt(ticket["received_at"])
                if received > window_start:
                    window_start = received
            window_end = dt(ticket["visit_window_end"])
            if ticket.get("sla_deadline_at"):
                sla = dt(ticket["sla_deadline_at"])
                if sla < window_end:
                    window_end = sla
            window = policy.start_window(window_start, window_end, epoch, duration, horizon)
            required = [
                a for a in snapshot["required_appliances"] if a["work_type_id"] == work_type["id"]
            ]
            skills = {
                s["skill_id"]
                for s in snapshot["required_skills"]
                if s["work_type_id"] == work_type["id"]
            }
            req_transport = ticket.get("required_transport_type")
            not_reserved = [
                (a["appliance_id"], allocated.get(a["appliance_id"], 0), a["quantity"])
                for a in required
                if allocated.get(a["appliance_id"], 0) < a["quantity"]
            ]
            not_issuable = [
                {
                    "office_id": a["office_id"],
                    "appliance_id": a["appliance_id"],
                    "stock": stock.get((a["office_id"], a["appliance_id"]), 0),
                    "reserved": reserved.get((a["office_id"], a["appliance_id"]), 0),
                    "is_active": appliances.get(a["appliance_id"], {}).get("is_active", False),
                }
                for a in allocations
                if not appliances.get(a["appliance_id"], {}).get("is_active", False)
                or reserved.get((a["office_id"], a["appliance_id"]), 0)
                > stock.get((a["office_id"], a["appliance_id"]), 0)
            ]
            if not 0 < duration <= 2880:
                reason = reasons.invalid_duration(
                    duration, rule["service_duration_source"], work_type
                )
            elif window[0] > window[1]:
                reason = reasons.outside_horizon(
                    window_start, window_end, epoch, at(epoch, horizon), day
                )
            elif not_reserved:
                reason = reasons.equipment_not_reserved(not_reserved, names)
            elif not_issuable:
                reason = reasons.stock_inconsistent(not_issuable, names)
            else:
                allowed = []
                ticket_area_id = (
                    ticket.get("service_area_id")
                    or snapshot.get("ticket_service_areas", {}).get(tid)
                    or snapshot.get("service_area_id")
                )
                candidate_ticket = dict(
                    ticket,
                    service_area_id=ticket_area_id,
                    visit_window_start=window_start.isoformat(),
                    visit_window_end=window_end.isoformat(),
                )
                for v, w in enumerate(workers):
                    why = candidate_reason(
                        candidate_ticket,
                        window,
                        duration,
                        skills,
                        allocations,
                        w,
                        epoch,
                        req_transport,
                    )
                    if why:
                        candidates.append({"worker_id": w["user_id"], "reason": why})
                    else:
                        allowed.append(v)
                nobody = sorted(skills - set().union(*(w["skill_ids"] for w in workers)))
                if allowed:
                    ticket.update(
                        service_area_id=ticket_area_id,
                        window=window,
                        duration=duration,
                        allowed=allowed,
                        duration_source=rule["service_duration_source"],
                        category=ticket.get("category") or work_type.get("category") or "repair",
                        priority=ticket.get("priority") or work_type.get("default_priority") or 3,
                        work_type_id=work_type["id"],
                        rejected=candidates,
                        required_skill_ids=sorted(skills),
                        allocations=[
                            {
                                "appliance_id": a["appliance_id"],
                                "office_id": a["office_id"],
                                "quantity": a["quantity"],
                            }
                            for a in allocations
                        ],
                    )
                elif not workers:
                    reason = reasons.no_available_workers(len(excluded_workers))
                elif nobody:
                    reason = reasons.skill_nobody_has(nobody, skills, len(workers))
                else:
                    reason = reasons.no_eligible_worker(candidates)
        if reason:
            unassigned.append({"ticket_id": tid, "reason": reason, "candidates": candidates})
        else:
            tickets.append(ticket)
    req_route_end = (
        request.get("route_end")
        if isinstance(request, dict)
        else getattr(request, "route_end", None)
    )
    if req_route_end in ("open", "open_end"):
        open_end = True
    elif req_route_end in ("return_to_start", "return_to_brigade_office", "specific_finish"):
        open_end = False
    else:
        open_end = policy.route_end in ("open", "open_end")
    return {
        "policy": policy,
        "epoch": epoch,
        "horizon": horizon,
        "open_end": open_end,
        "route_end": req_route_end or ("open" if open_end else "return_to_start"),
        "service_area_id": snapshot.get("service_area_id"),
        "workers": workers,
        "tickets": tickets,
        "locations": locations,
        "appliance_names": names,
        "unassigned": unassigned,
        "excluded_workers": excluded_workers,
    }


def check_eligibility(snapshot: dict, now: datetime | None = None) -> dict:
    """Convenience helper to evaluate candidate eligibility and exclusions."""
    if now is None:
        now = datetime.min.replace(tzinfo=MOSCOW)
    return prepare(snapshot, now)

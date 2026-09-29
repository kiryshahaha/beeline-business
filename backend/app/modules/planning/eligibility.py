"""Convert domain restrictions to eligible vehicles and service-start windows."""

import math
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.modules.planning import reasons
from app.modules.planning.errors import PlanningError
from app.modules.planning.policy import snapshot_policy
from app.modules.users.shifts import get_worker_shift

MOSCOW = ZoneInfo("Europe/Moscow")
PROFILES = {
    "car": "drive",
    "walking": "walk",
    "bicycle": "bicycle",
    "public_transport": "approximated_transit",
}


def dt(value: str) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def by_id(mapping: dict | None, key):
    """A normalized snapshot keys its maps by strings, a hand-built one by integers."""
    mapping = mapping or {}
    return mapping.get(key, mapping.get(str(key)))


def active_stage_end(active_ticket: dict, now: datetime) -> datetime:
    """The earliest end of a trip or service that execution has not reported yet.

    Started service lasts at least its estimate from the actual start; an engineer still
    travelling has the whole service ahead. The published end stays a lower bound.
    """
    duration = timedelta(minutes=active_ticket.get("estimated_duration_minutes") or 0)
    ends = [now]
    if active_ticket.get("planned_end_at"):
        ends.append(dt(active_ticket["planned_end_at"]))
    if active_ticket.get("lifecycle_state") == "in_progress":
        started = active_ticket.get("actual_started_at")
        ends.append((dt(started) if started else now) + duration)
    else:
        ends.append(now + duration)
    return max(ends)


def worker_replan_anchor(
    day_state, active_ticket, now, *, default_location_id, estimate_active_stage=False
):
    """Return the confirmed or promised point and time from which the remainder can start.

    An emergency waits for the completion event of the current stage. An ordinary insertion
    may go after that stage, from its place and not before its earliest end.
    """
    current_ticket_id = day_state.get("current_ticket_id") if day_state else None
    expected = day_state.get("expected_available_at") if day_state else None
    if expected is not None:
        expected = dt(expected)

    if current_ticket_id is not None:
        lifecycle_state = (active_ticket or {}).get("lifecycle_state")
        if lifecycle_state in {"en_route", "in_progress"} and estimate_active_stage:
            stage_end = active_stage_end(active_ticket, now)
            return {
                "location_id": day_state.get("current_destination_id")
                or active_ticket.get("location_id")
                or day_state.get("last_location_id"),
                "available_at": max(stage_end, expected) if expected is not None else stage_end,
                "reason": None,
            }
        if lifecycle_state in {"en_route", "in_progress"}:
            # The current trip or service is a frozen stage. Do not use its ETA as
            # a route start until execution records completion at a known location.
            return {
                "location_id": day_state.get("current_destination_id")
                or day_state.get("last_location_id"),
                "available_at": expected,
                "reason": "active_stage_not_completed",
            }
        planned_end = (active_ticket or {}).get("planned_end_at")
        destination_id = day_state.get("current_destination_id")
        if (
            destination_id is not None
            and active_ticket is not None
            and active_ticket.get("location_id") != destination_id
        ):
            planned_end = None
        planned_end = dt(planned_end) if planned_end is not None else None
        if expected is None:
            if planned_end is None or planned_end <= now:
                return {
                    "location_id": None,
                    "available_at": None,
                    "reason": "active_work_eta_unknown",
                }
            expected = planned_end
        location_id = day_state.get("current_destination_id") or day_state.get("last_location_id")
    else:
        if day_state and not day_state.get("available", True) and expected is None:
            return {"location_id": None, "available_at": None, "reason": "worker_unavailable"}
        location_id = day_state.get("last_location_id") if day_state else None

    return {
        "location_id": location_id or default_location_id,
        "available_at": max(now, expected) if expected is not None else now,
        "reason": None,
    }


def at(epoch: datetime, minutes: int) -> datetime:
    return epoch + timedelta(minutes=minutes)


def candidate_reason(
    ticket, window, duration, skills, allocations, worker, epoch, required_transport_type=None
):
    """First failed hard rule for one engineer; the order goes from qualification to time."""
    day = epoch.date()
    if ticket.get("brigade_resolution_required"):
        return reasons.brigade_resolution_required(ticket.get("service_area_id"))
    ticket_brigade_id = ticket.get("brigade_id")
    if ticket_brigade_id is not None and worker.get("brigade_id") != ticket_brigade_id:
        return reasons.brigade_mismatch(ticket_brigade_id, worker.get("brigade_id"))
    missing = sorted(skills - worker["skill_ids"])
    if missing:
        return reasons.missing_skill(missing, skills)
    worker_area = worker.get("service_area_id")
    ticket_area = ticket.get("service_area_id")
    if (worker_area is None) != (ticket_area is None):
        return reasons.service_area_unknown(worker_area, ticket_area)
    if worker_area != ticket_area:
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


def prepare(snapshot: dict, now: datetime, *, estimate_active_stage: bool = False) -> dict:
    policy = snapshot_policy(snapshot)
    request = snapshot["request"]
    replan = bool(request.get("replan"))
    replan_ticket_ids = set(request.get("ticket_ids", [])) if replan else set()
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
    archived = set(snapshot.get("archived_worker_ids", []))
    day_states = {x["worker_id"]: x for x in snapshot.get("worker_day_states", [])}
    busy = {x["id"]: x for x in snapshot["busy_tickets"]}
    # A replan request lists the current in-progress ticket among its tickets, not as busy.
    requested = {x["id"]: x for x in snapshot["tickets"]}
    area_id = snapshot.get("service_area_id")
    resolved_worker_areas = snapshot.get("worker_service_areas")
    workers, excluded_workers = [], []
    for worker in snapshot["workers"]:
        worker = dict(worker)
        wid = worker["user_id"]
        day_state = day_states.get(wid)
        exceptions = [e for e in snapshot.get("shift_exceptions", []) if e.get("worker_id") == wid]
        shift = get_worker_shift(worker, day, exceptions=exceptions)
        if shift is None:
            # Worker is off-duty (day off by schedule or exception)
            start = datetime.combine(
                epoch.date(), time.fromisoformat(worker["workshift_start"]), MOSCOW
            )
            end = datetime.combine(
                epoch.date(), time.fromisoformat(worker["workshift_end"]), MOSCOW
            )
            if end <= start:
                end += timedelta(days=1)
        else:
            start, end = shift
        brigade = brigades.get(members.get(wid))
        office_id = worker.get("stock_office_id") or (brigade["office_id"] if brigade else None)
        office = offices.get(office_id) if office_id else None

        default_location_id = worker.get("start_location_id") or (
            office["location_id"] if office else None
        )
        anchor = None
        if replan:
            current_ticket_id = day_state.get("current_ticket_id") if day_state else None
            anchor = worker_replan_anchor(
                day_state,
                busy.get(current_ticket_id) or requested.get(current_ticket_id),
                now,
                default_location_id=default_location_id,
                estimate_active_stage=estimate_active_stage,
            )
        if anchor and anchor["reason"] is None:
            start_location_id = anchor["location_id"]
        elif day_state and day_state.get("last_location_id"):
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
        # The resolved area never falls back to the area of this request.
        worker_area_id = (
            by_id(resolved_worker_areas, wid)
            if resolved_worker_areas is not None
            else worker.get("service_area_id")
        )
        area_issue = by_id(snapshot.get("worker_area_issues"), wid)
        reason = None
        if roles.get(wid) != "worker":
            reason = reasons.invalid_worker_role(roles.get(wid))
        elif wid in archived:
            reason = reasons.worker_archived()
        elif area_issue:
            reason = reasons.worker_service_area_unresolved(area_issue)
        elif area_id is not None and worker_area_id is None:
            reason = reasons.worker_service_area_unresolved(
                {"code": "service_area_missing", "subject_id": wid, "sources": {}}
            )
        elif area_id is not None and worker_area_id != area_id:
            reason = reasons.worker_outside_service_area(worker_area_id, area_id)
        elif shift is None:
            reason = reasons.worker_day_off(day)
        elif (
            replan
            and anchor
            and anchor["reason"]
            in {
                "active_work_eta_unknown",
                "active_stage_not_completed",
            }
        ):
            active_stage_not_completed = anchor["reason"] == "active_stage_not_completed"
            reason = reasons.explain(
                anchor["reason"],
                "availability",
                (
                    "Инженер завершает текущий этап; расчёт нового маршрута ждёт события завершения"
                    if active_stage_not_completed
                    else "Инженер занят начатой заявкой без времени освобождения"
                ),
                constraint=(
                    "active_stage_requires_completion_event"
                    if active_stage_not_completed
                    else "active_work_requires_expected_end"
                ),
                ids={"ticket_ids": [day_state["current_ticket_id"]]},
                observed={
                    "expected_available_at": (
                        anchor["available_at"].isoformat() if anchor["available_at"] else None
                    )
                },
                required={"execution_state": "completed"} if active_stage_not_completed else None,
            )
        elif (
            day_state
            and not day_state["available"]
            and not (replan and day_state.get("expected_available_at"))
        ):
            reason = reasons.worker_unavailable(
                dt(day_state["expected_available_at"])
                if day_state.get("expected_available_at")
                else None
            )
        elif not worker["is_on_line"] and not (
            replan and day_state and day_state.get("expected_available_at")
        ):
            reason = reasons.worker_offline()
        elif not office:
            reason = reasons.missing_office()
        elif not location or location["latitude"] is None or location["longitude"] is None:
            reason = reasons.office_without_coordinates(
                office["id"], start_location_id or office["location_id"]
            )
        elif replan and day == now.date() and end <= now:
            reason = reasons.worker_shift_ended(end, now, day)
        elif (
            day == now.date()
            and start <= now
            and not (day_state and day_state.get("last_location_id"))
            and not replan
        ):
            reason = reasons.shift_already_started(start, now, day)
        elif day_state and day_state.get("current_ticket_id") and not replan:
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
                if (
                    replan
                    and day_state
                    and assignment["ticket_id"] == day_state.get("current_ticket_id")
                ):
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
        if replan:
            available_at = max(start, now, anchor["available_at"] if anchor else now)
        elif day_state and day_state.get("expected_available_at"):
            available_at = max(available_at, dt(day_state["expected_available_at"]))
        worker.update(
            {
                "office_id": office["id"],
                "brigade_id": members.get(wid),
                "service_area_id": worker_area_id,
                "location_id": start_location_id,
                "start_location_id": start_location_id,
                "end_location_id": end_location_id,
                "profile": PROFILES[worker["transport_type"]],
                "transport_type": worker["transport_type"],
                "shift_start": start,
                "shift_end": end,
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
        work_type = types_by_id.get(ticket.get("work_type_id"))
        rule = rules.get(work_type["id"]) if work_type else None
        location = locations.get(ticket["location_id"])
        allocations = [a for a in snapshot["allocations"] if a["ticket_id"] == tid]
        allocated = {a["appliance_id"]: a["quantity"] for a in allocations}
        assigned = sorted(a["worker_id"] for a in snapshot["assignments"] if a["ticket_id"] == tid)
        reason, candidates = None, []
        if ticket["status"] != "planned":
            reason = reasons.ticket_not_planned(ticket["status"])
        elif assigned and not (replan and tid in replan_ticket_ids):
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
            received_at = dt(ticket["received_at"]) if ticket.get("received_at") else None
            if ticket.get("received_at"):
                window_start = max(window_start, received_at)
            window_end = dt(ticket["visit_window_end"])
            sla_deadline_at = (
                dt(ticket["sla_deadline_at"]) if ticket.get("sla_deadline_at") else None
            )
            earliest_completion = window_start + timedelta(minutes=duration)
            if sla_deadline_at is not None and earliest_completion > sla_deadline_at:
                reason = reasons.sla_deadline_missed(earliest_completion, sla_deadline_at, ticket)
                window = None
            else:
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
            if reason is not None:
                pass
            elif not 0 < duration <= 2880:
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
                    if ticket.get("service_area_id") is not None
                    else by_id(snapshot.get("ticket_service_areas"), tid)
                )
                area_brigades = snapshot.get("service_area_brigades")
                area_brigade_ids = by_id(area_brigades, ticket_area_id) or []
                candidate_ticket = dict(
                    ticket,
                    brigade_id=(
                        ticket.get("brigade_id")
                        if ticket.get("brigade_id") is not None
                        else area_brigade_ids[0]
                        if len(area_brigade_ids) == 1
                        else None
                    ),
                    service_area_id=ticket_area_id,
                    brigade_resolution_required=(
                        ticket.get("brigade_id") is None and len(area_brigade_ids) > 1
                    ),
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
                        received_at=received_at.isoformat() if received_at else None,
                        sla_deadline_at=(sla_deadline_at.isoformat() if sla_deadline_at else None),
                        response_deadline_at=(
                            dt(ticket["response_deadline_at"]).isoformat()
                            if ticket.get("response_deadline_at")
                            else None
                        ),
                        intake_source=ticket.get("intake_source"),
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
            reason = reasons.annotate_priority(
                reason,
                ticket.get("category") or (work_type or {}).get("category") or "repair",
                ticket.get("priority") or (work_type or {}).get("default_priority") or 3,
            )
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

"""Local slot finder for regular new ticket insertion without global replan.

Implements T4-03: adds a regular ticket into an existing day plan by finding an
available gap in the schedule of one of the current day's workers.
OR-Tools global permuting is NOT invoked.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.modules.planning.day_plans import (
    get_worker_safe_point,
    validate_immutable_route_invariants,
)


@dataclass
class SlotCandidate:
    worker_id: int
    insertion_sequence: int  # sequence in updated route (1-based)
    estimated_arrival_at: datetime
    service_start_at: datetime
    service_end_at: datetime
    travel_to_minutes: int
    travel_from_minutes: int
    replaced_travel_minutes: int
    added_travel_minutes: int
    shifted_visits_count: int
    proposed_state: dict


@dataclass
class InsertionResult:
    status: str  # "slot_found" or "not_insertable"
    ticket_id: int
    selected: SlotCandidate | None = None
    candidate_reasons: dict[int, dict] = field(default_factory=dict)
    summary_message: str = ""


def _parse_iso(val: str | datetime | None) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    return datetime.fromisoformat(val)


def find_regular_ticket_slot(
    *,
    ticket: dict,
    candidate_workers: list[dict],
    baseline_state: dict,
    lifecycle_by_ticket: dict[int, str],
    travel_time_fn: Callable[[int, int, str], int],
    office_location_id: int,
    now: datetime,
) -> InsertionResult:
    """Find the best feasible slot for an incoming regular ticket across day workers.

    Args:
        ticket: Dict with keys: id, location_id, estimated_duration_minutes,
                visit_window_start, visit_window_end, required_transport_type,
                required_skills, required_appliances
        candidate_workers: List of worker dicts: user_id, skills (set/list),
                           transport_type, available_appliances (dict of type_id -> qty),
                           shift_start_at, shift_end_at
        baseline_state: Published DayPlanRevision.plan_state dict
        lifecycle_by_ticket: Current lifecycle states of area tickets
        travel_time_fn: Function (from_loc_id, to_loc_id, transport_profile) -> travel_minutes
        office_location_id: Depot/office location id for route start/end
        now: Current timestamp
    """
    ticket_id = ticket["id"]
    ticket_loc = ticket["location_id"]
    duration = timedelta(minutes=ticket.get("estimated_duration_minutes", 30))
    window_start = _parse_iso(ticket["visit_window_start"])
    window_end = _parse_iso(ticket["visit_window_end"])
    req_transport = ticket.get("required_transport_type")
    req_skills = set(ticket.get("required_skills") or [])
    req_appliances = ticket.get("required_appliances") or {}

    candidate_reasons: dict[int, dict] = {}
    feasible_slots: list[SlotCandidate] = []

    # Map existing visits by worker
    visits_by_worker: dict[int, list[dict]] = {}
    for v in (baseline_state or {}).get("visits", []):
        wid = v.get("worker_id")
        if wid is not None:
            visits_by_worker.setdefault(wid, []).append(dict(v))

    for w in visits_by_worker.values():
        w.sort(key=lambda item: item.get("sequence", 0))

    for worker in candidate_workers:
        wid = worker["user_id"]
        w_skills = set(worker.get("skills") or [])
        w_transport = worker.get("transport_profile", worker.get("transport_type", "car"))
        w_appliances = worker.get("available_appliances") or {}
        shift_start = _parse_iso(worker["shift_start_at"])
        shift_end = _parse_iso(worker["shift_end_at"])

        # 1. Eligibility prechecks
        if req_skills and not req_skills.issubset(w_skills):
            missing = sorted(req_skills - w_skills)
            candidate_reasons[wid] = {
                "code": "missing_skill",
                "category": "skill",
                "message": f"У работника {wid} отсутствуют требуемые навыки: {missing}",
                "ids": {"missing_skills": missing},
            }
            continue

        if req_transport and req_transport != w_transport:
            candidate_reasons[wid] = {
                "code": "transport_mismatch",
                "category": "transport",
                "message": (
                    f"Требуемый транспорт '{req_transport}' не совпадает "
                    f"с транспортом работника '{w_transport}'"
                ),
            }
            continue

        insufficient_appliances = []
        for app_type_id, required_qty in req_appliances.items():
            if w_appliances.get(app_type_id, 0) < required_qty:
                insufficient_appliances.append(app_type_id)
        if insufficient_appliances:
            candidate_reasons[wid] = {
                "code": "insufficient_appliances",
                "category": "inventory",
                "message": f"Недостаточно оборудования у работника {wid} на руках",
                "ids": {"appliance_type_ids": insufficient_appliances},
            }
            continue

        # 2. Worker existing route & safe point
        route_visits = visits_by_worker.get(wid, [])
        safe_point = get_worker_safe_point(
            wid, baseline_state, lifecycle_by_ticket, default_location_id=office_location_id
        )

        min_insertion_index = 0
        if safe_point["is_frozen"]:
            # Insertion must be strictly AFTER the frozen in-flight visit
            frozen_seq = safe_point["frozen_sequence"]
            min_insertion_index = frozen_seq  # 1-based index corresponds to after frozen visit

        worker_best_slot: SlotCandidate | None = None
        rejection_reasons_worker: list[str] = []
        worker_office_location_id = worker.get("office_location_id", office_location_id)

        # 3. Test each insertion index from min_insertion_index to len(route_visits)
        num_existing = len(route_visits)
        for insert_idx in range(min_insertion_index, num_existing + 1):
            # Previous stop
            if insert_idx == 0:
                prev_loc = worker_office_location_id
                prev_finish_time = max(shift_start, now)
            else:
                prev_v = route_visits[insert_idx - 1]
                prev_loc = prev_v.get("location_id", worker_office_location_id)
                prev_finish_time = _parse_iso(prev_v["service_end_at"])
                if lifecycle_by_ticket.get(prev_v["ticket_id"]) == "completed":
                    prev_finish_time = max(prev_finish_time, now)
                elif safe_point["is_frozen"] and insert_idx == min_insertion_index:
                    prev_finish_time = max(prev_finish_time, now)

            # Next stop
            if insert_idx < num_existing:
                next_v = route_visits[insert_idx]
                next_loc = next_v.get("location_id", worker_office_location_id)
            else:
                next_loc = worker_office_location_id

            # Leg 1: prev -> ticket
            travel_to = travel_time_fn(prev_loc, ticket_loc, w_transport)
            arrival_at = prev_finish_time + timedelta(minutes=travel_to)
            service_start = max(arrival_at, window_start)
            service_end = service_start + duration

            # Check new ticket window and shift
            if service_end > window_end:
                rejection_reasons_worker.append(
                    f"pos_{insert_idx}: service ends after window ({service_end} > {window_end})"
                )
                continue

            if service_end > shift_end:
                rejection_reasons_worker.append(f"pos_{insert_idx}: service ends after shift end")
                continue

            # Leg 2: ticket -> next
            travel_from = travel_time_fn(ticket_loc, next_loc, w_transport)

            # Check cascade shifts on subsequent visits
            cascade_ok = True
            current_sim_time = service_end
            current_sim_loc = ticket_loc
            simulated_next_times = []

            for idx in range(insert_idx, num_existing):
                subsequent_v = route_visits[idx]
                sub_loc = subsequent_v.get("location_id", worker_office_location_id)
                sub_leg = travel_time_fn(current_sim_loc, sub_loc, w_transport)
                sub_arr = current_sim_time + timedelta(minutes=sub_leg)
                sub_win_start = _parse_iso(
                    subsequent_v.get("visit_window_start", subsequent_v["service_start_at"])
                )
                sub_win_end = _parse_iso(
                    subsequent_v.get("visit_window_end", subsequent_v["service_end_at"])
                )
                sub_start = max(sub_arr, sub_win_start)
                sub_dur = _parse_iso(subsequent_v["service_end_at"]) - _parse_iso(
                    subsequent_v["service_start_at"]
                )
                sub_end = sub_start + sub_dur

                if sub_end > sub_win_end:
                    cascade_ok = False
                    rejection_reasons_worker.append(
                        f"pos_{insert_idx}: window violation on ticket {subsequent_v['ticket_id']}"
                    )
                    break

                if sub_end > shift_end:
                    cascade_ok = False
                    rejection_reasons_worker.append(
                        f"pos_{insert_idx}: shift violation on ticket {subsequent_v['ticket_id']}"
                    )
                    break

                simulated_next_times.append(
                    {
                        "ticket_id": subsequent_v["ticket_id"],
                        "arrival_at": sub_arr.isoformat(),
                        "service_start_at": sub_start.isoformat(),
                        "service_end_at": sub_end.isoformat(),
                    }
                )
                current_sim_time = sub_end
                current_sim_loc = sub_loc

            if not cascade_ok:
                continue

            return_leg = travel_time_fn(current_sim_loc, worker_office_location_id, w_transport)
            if current_sim_time + timedelta(minutes=return_leg) > shift_end:
                rejection_reasons_worker.append(
                    f"pos_{insert_idx}: return to office exceeds shift end"
                )
                continue

            # Calculate added travel time: travel_to + travel_from - original_leg
            orig_leg = (
                travel_time_fn(prev_loc, next_loc, w_transport)
                if (insert_idx > 0 and insert_idx < num_existing)
                else 0
            )
            added_travel = max(0, travel_to + travel_from - orig_leg)

            # Build proposed_state
            new_ticket_visit = {
                "ticket_id": ticket_id,
                "worker_id": wid,
                "sequence": insert_idx + 1,
                "arrival_at": arrival_at.isoformat(),
                "service_start_at": service_start.isoformat(),
                "service_end_at": service_end.isoformat(),
                "location_id": ticket_loc,
            }

            # Assemble proposed route visits
            updated_worker_visits = []
            for v in route_visits[:insert_idx]:
                updated_worker_visits.append(dict(v))

            updated_worker_visits.append(new_ticket_visit)

            sim_map = {item["ticket_id"]: item for item in simulated_next_times}
            for i, v in enumerate(route_visits[insert_idx:]):
                sim = sim_map.get(v["ticket_id"])
                new_v = dict(v)
                new_v["sequence"] = insert_idx + 2 + i
                if sim:
                    new_v["arrival_at"] = sim["arrival_at"]
                    new_v["service_start_at"] = sim["service_start_at"]
                    new_v["service_end_at"] = sim["service_end_at"]
                updated_worker_visits.append(new_v)

            # Merge with other workers' visits
            all_proposed_visits = []
            for other_wid, other_visits in visits_by_worker.items():
                if other_wid == wid:
                    all_proposed_visits.extend(updated_worker_visits)
                else:
                    all_proposed_visits.extend([dict(v) for v in other_visits])
            if wid not in visits_by_worker:
                all_proposed_visits.extend(updated_worker_visits)

            proposed_state = {
                **(baseline_state or {}),
                "visits": all_proposed_visits,
            }

            # Invariant check (guarantee no regression of order/assignments)
            violations = validate_immutable_route_invariants(
                baseline_state,
                proposed_state,
                inserted_ticket_id=ticket_id,
                lifecycle_by_ticket=lifecycle_by_ticket,
            )
            if violations:
                rejection_reasons_worker.append(
                    f"pos_{insert_idx}: invariant violation ({violations[0]})"
                )
                continue

            candidate = SlotCandidate(
                worker_id=wid,
                insertion_sequence=insert_idx + 1,
                estimated_arrival_at=arrival_at,
                service_start_at=service_start,
                service_end_at=service_end,
                travel_to_minutes=travel_to,
                travel_from_minutes=travel_from,
                replaced_travel_minutes=orig_leg,
                added_travel_minutes=added_travel,
                shifted_visits_count=len(simulated_next_times),
                proposed_state=proposed_state,
            )

            # Keep candidate with smallest added_travel_minutes
            if (
                worker_best_slot is None
                or candidate.added_travel_minutes < worker_best_slot.added_travel_minutes
            ):
                worker_best_slot = candidate

        if worker_best_slot is not None:
            feasible_slots.append(worker_best_slot)
        else:
            reasons_summary = "; ".join(rejection_reasons_worker[:2])
            candidate_reasons[wid] = {
                "code": "no_feasible_slot",
                "category": "time",
                "message": f"У работника {wid} нет допустимого слота: {reasons_summary}",
            }

    if not feasible_slots:
        return InsertionResult(
            status="not_insertable",
            ticket_id=ticket_id,
            selected=None,
            candidate_reasons=candidate_reasons,
            summary_message="Заявка не может быть добавлена без изменения назначений",
        )

    # Choose slot with minimal added_travel_minutes, tie-break by earlier service_start_at
    best = min(
        feasible_slots,
        key=lambda s: (s.added_travel_minutes, s.service_start_at),
    )

    return InsertionResult(
        status="slot_found",
        ticket_id=ticket_id,
        selected=best,
        candidate_reasons=candidate_reasons,
        summary_message=(
            f"Найден слот у работника {best.worker_id} на позиции {best.insertion_sequence}"
        ),
    )

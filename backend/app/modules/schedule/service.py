"""Build the day timeline without HTTP-specific exceptions."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import RowMapping
from sqlalchemy.orm import Session

from app.core.workday import MOSCOW, day_bounds, today
from app.modules.planning.day_plans import current_revision
from app.modules.routing.service import plan_revisions_of
from app.modules.schedule import repository
from app.modules.schedule.schemas import (
    ScheduleAvailability,
    ScheduleBrigade,
    ScheduleConflict,
    ScheduleForeman,
    SchedulePlanRevision,
    ScheduleRead,
    ScheduleRoute,
    ScheduleTicket,
    ScheduleUnassignedTicket,
    ScheduleVisit,
    ScheduleWorker,
    ScheduleWorkerDay,
    ShiftInterval,
)
from app.modules.schedule.timeline import WorkerDay, attribution_window, build_worker_day
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead

__all__ = ["MOSCOW", "OfficeNotFoundError", "day_bounds", "get_schedule", "today"]


class OfficeNotFoundError(Exception):
    pass


@dataclass
class LoadedDay:
    timeline: WorkerDay
    state: RowMapping | None
    route: RowMapping | None
    route_marks: dict


def _route_stops(route: RowMapping | None) -> list[dict] | None:
    if route is None:
        return None
    return [
        feature["properties"]
        for feature in route["geojson"].get("features", [])
        if feature.get("geometry", {}).get("type") == "Point"
    ]


def load_worker_days(session: Session, day: date, workers: list[RowMapping]) -> dict:
    """Every worker's day in the planner's own shift model, from one set of queries.

    The caller owns the transaction. Workers are rows with `id`, `workshift_start`
    and `workshift_end`.
    """
    if not workers:
        return {}
    ids = [row["id"] for row in workers]
    windows = {
        row["id"]: attribution_window(day, row["workshift_start"], row["workshift_end"])
        for row in workers
    }
    tickets = repository.find_worker_day_tickets(
        session,
        ids,
        min(window[0] for window in windows.values()),
        max(window[1] for window in windows.values()),
    )
    by_worker: dict[int, list[dict]] = defaultdict(list)
    for row in tickets:
        start, end = windows[row["worker_id"]]
        if start <= row["planned_start_at"] < end:
            by_worker[row["worker_id"]].append(dict(row))
    routes = {row["worker_id"]: row for row in repository.find_latest_routes(session, ids, day)}
    marks = plan_revisions_of(session, [row["id"] for row in routes.values()])
    states = {row["worker_id"]: row for row in repository.find_day_states(session, ids, day)}
    result = {}
    for row in workers:
        state = states.get(row["id"])
        route = routes.get(row["id"])
        result[row["id"]] = LoadedDay(
            timeline=build_worker_day(
                day,
                shift_start=row["workshift_start"],
                shift_end=row["workshift_end"],
                route_stops=_route_stops(route),
                tickets=by_worker.get(row["id"], []),
                available=state["available"] if state else True,
                unavailable_at=state["unavailable_at"] if state else None,
                unavailable_until=state["unavailable_until"] if state else None,
            ),
            state=state,
            route=route,
            route_marks=marks.get(route["id"], {}) if route else {},
        )
    return result


def _worker_day(loaded: LoadedDay) -> ScheduleWorkerDay:
    day = loaded.timeline
    state, route = loaded.state, loaded.route
    return ScheduleWorkerDay(
        shift_start=day.shift_start,
        shift_end=day.shift_end,
        availability=ScheduleAvailability(
            available=state["available"] if state else True,
            unavailable_at=state["unavailable_at"] if state else None,
            unavailable_until=state["unavailable_until"] if state else None,
            expected_available_at=state["expected_available_at"] if state else None,
            reason=state["reason"] if state else None,
        ),
        route=ScheduleRoute(
            id=route["id"],
            route_number=route["route_number"],
            created_at=route["created_at"],
            day_revision=loaded.route_marks.get("day_revision"),
            is_current_plan=loaded.route_marks.get("is_current_plan"),
        )
        if route
        else None,
        visits=[
            ScheduleVisit(
                ticket_id=visit.ticket_id,
                sequence=visit.sequence,
                arrival=visit.arrival.astimezone(MOSCOW) if visit.arrival else None,
                start=visit.start.astimezone(MOSCOW),
                end=visit.end.astimezone(MOSCOW),
                waiting_minutes=visit.waiting_minutes,
                source=visit.source,
            )
            for visit in day.visits
        ],
        service_minutes=day.service_minutes,
        travel_minutes=day.travel_minutes,
        waiting_minutes=day.waiting_minutes,
        free_minutes=day.free_minutes,
        overtime_minutes=day.overtime_minutes,
        conflicts=[
            ScheduleConflict(code=item.code, message=item.message, ticket_ids=item.ticket_ids)
            for item in day.conflicts
        ],
    )


def shift_intervals(day: date, shift_start: time, shift_end: time) -> list[ShiftInterval]:
    """Whole shifts touching the day; a night shift from yesterday ends this morning."""
    day_start, day_end = day_bounds(day)
    overnight = shift_end <= shift_start
    intervals = []
    for shift_day in (day - timedelta(days=1), day):
        start = datetime.combine(shift_day, shift_start, MOSCOW)
        end = datetime.combine(shift_day + timedelta(days=overnight), shift_end, MOSCOW)
        if start < day_end and end > day_start:
            intervals.append(ShiftInterval(start=start, end=end))
    return intervals


def _full_name(surname: str, name: str, lastname: str | None) -> str:
    return " ".join(part for part in (surname, name, lastname) if part)


def _worker(
    row: RowMapping,
    day: date,
    tickets: dict[int, list[ScheduleTicket]],
    days: dict[int, LoadedDay],
) -> ScheduleWorker:
    return ScheduleWorker(
        id=row["id"],
        full_name=_full_name(row["surname"], row["name"], row["lastname"]),
        transport_type=row["transport_type"],
        is_on_line=row["is_on_line"],
        workshift_start=row["workshift_start"],
        workshift_end=row["workshift_end"],
        shifts=shift_intervals(day, row["workshift_start"], row["workshift_end"]),
        tickets=tickets.get(row["id"], []),
        day_plan=_worker_day(days[row["id"]]),
    )


def get_schedule(
    session: Session, day: date, office_id: int | None, current_user: UserRead
) -> ScheduleRead:
    # A foreman sees only their own brigade; office_id narrows the result and never widens it.
    foreman_id = current_user.id if current_user.role == UserRole.FOREMAN else None
    day_start, day_end = day_bounds(day)
    with session.begin():
        if office_id is not None and not repository.office_exists(session, office_id):
            raise OfficeNotFoundError
        brigades = repository.find_brigades(session, office_id=office_id, foreman_id=foreman_id)
        members = repository.find_brigade_workers(session, [row["id"] for row in brigades])
        unassigned = (
            repository.find_unassigned_workers(session)
            if office_id is None and foreman_id is None
            else []
        )
        ticket_rows = repository.find_planned_tickets(
            session, [row["id"] for row in [*members, *unassigned]], day_start, day_end
        )
        days = load_worker_days(session, day, [*members, *unassigned])
        # The queue waiting for an engineer is scoped by area: a foreman or an office
        # sees the areas of its offices, an unfiltered dispatcher sees all of them.
        office_areas = repository.find_office_areas(
            session, sorted({row["office_id"] for row in brigades})
        )
        scoped = office_id is not None or foreman_id is not None
        area_ids = sorted(set(office_areas.values())) if scoped else None
        open_tickets = repository.find_unassigned_tickets(session, day_start, day_end, area_ids)
        visible_areas = set(office_areas.values()) | {
            row["service_area_id"]
            for row in [*members, *unassigned]
            if row["service_area_id"] is not None
        }
        if not scoped:
            visible_areas |= {
                row["service_area_id"] for row in open_tickets if row["service_area_id"]
            }
        revisions = [
            SchedulePlanRevision(
                service_area_id=area_id, current_revision=current_revision(session, area_id, day)
            )
            for area_id in sorted(visible_areas)
        ]

    tickets: dict[int, list[ScheduleTicket]] = defaultdict(list)
    for row in ticket_rows:
        tickets[row["worker_id"]].append(
            ScheduleTicket(
                id=row["id"],
                title=row["title"],
                work_type=row["work_type"],
                status=row["status"],
                start=row["planned_start_at"].astimezone(MOSCOW),
                end=row["planned_end_at"].astimezone(MOSCOW),
            )
        )
    brigade_workers: dict[int, list[ScheduleWorker]] = defaultdict(list)
    for row in members:
        brigade_workers[row["brigade_id"]].append(_worker(row, day, tickets, days))

    return ScheduleRead(
        date=day,
        office_id=office_id,
        day_start=day_start,
        day_end=day_end,
        brigades=[
            ScheduleBrigade(
                id=row["id"],
                name=row["name"],
                office_id=row["office_id"],
                office_name=row["office_name"],
                foreman=ScheduleForeman(
                    id=row["foreman_id"],
                    full_name=_full_name(
                        row["foreman_surname"], row["foreman_name"], row["foreman_lastname"]
                    ),
                ),
                workers=brigade_workers.get(row["id"], []),
            )
            for row in brigades
        ],
        unassigned_workers=[_worker(row, day, tickets, days) for row in unassigned],
        unassigned_tickets=[ScheduleUnassignedTicket(**row) for row in open_tickets],
        plan_revisions=revisions,
    )

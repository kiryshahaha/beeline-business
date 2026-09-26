"""One worker's working day: the shift the planner uses, the promised visits and gaps.

The schedule and the workload analytics both read this module, so they cannot tell two
different stories about the same day. Visits come from the worker's latest saved route
for the day — the timeline the planner produced, with arrival, waiting and service
separated — and a ticket assigned for the day that is missing from that route is still
shown, from its own planned times, and reported as a conflict.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from app.core.workday import MOSCOW


def planning_shift(day: date, shift_start: time, shift_end: time) -> tuple[datetime, datetime]:
    """The shift the planner assigns to `day`: it starts on that day, a night one ends
    the next morning. This is the same interval `planning.eligibility.prepare` uses."""
    start = datetime.combine(day, shift_start, MOSCOW)
    end = datetime.combine(day, shift_end, MOSCOW)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def attribution_window(day: date, shift_start: time, shift_end: time) -> tuple[datetime, datetime]:
    """The 24 hours that belong to this day's shift.

    The time off between two shifts is split in half, so every moment belongs to
    exactly one worker-day: an overtime visit at 19:30 after a 9–18 shift is part of
    today, and a visit at 02:00 is part of last night's 22–06 shift, not of today's.
    """
    start, end = planning_shift(day, shift_start, shift_end)
    margin = (timedelta(days=1) - (end - start)) / 2
    return start - margin, end + margin


def _minutes(delta: timedelta) -> int:
    return max(0, round(delta.total_seconds() / 60))


def _moment(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


@dataclass
class Visit:
    ticket_id: int
    start: datetime
    end: datetime
    arrival: datetime | None = None
    waiting_minutes: int = 0
    sequence: int | None = None
    source: str = "route"


@dataclass
class Conflict:
    code: str
    message: str
    ticket_ids: list[int] = field(default_factory=list)


@dataclass
class WorkerDay:
    shift_start: datetime
    shift_end: datetime
    available: bool
    visits: list[Visit]
    service_minutes: int
    travel_minutes: int
    waiting_minutes: int
    overtime_minutes: int
    conflicts: list[Conflict]

    @property
    def shift_minutes(self) -> int:
        return _minutes(self.shift_end - self.shift_start) if self.available else 0

    @property
    def free_minutes(self) -> int:
        busy = self.service_minutes + self.travel_minutes + self.waiting_minutes
        return max(0, self.shift_minutes - busy + self.overtime_minutes)


def route_visits(stops: list[dict]) -> tuple[list[Visit], int]:
    """Visits of a saved route and the minutes spent getting between its points.

    Travel is measured from leaving a point (end of service, or arrival at a point
    without service such as the office) to arriving at the next one; the wait before a
    client's window opens is counted separately by the planner and is kept apart here.
    """
    ordered = sorted(stops, key=lambda stop: stop.get("sequence") or 0)
    visits, travel, leave = [], 0, None
    for stop in ordered:
        arrival = _moment(stop.get("arrival_at"))
        if leave is not None and arrival is not None:
            travel += _minutes(arrival - leave)
        start = _moment(stop.get("service_start_at"))
        end = _moment(stop.get("service_end_at"))
        leave = end or arrival
        if stop.get("ticket_id") is None or start is None or end is None:
            continue
        visits.append(
            Visit(
                ticket_id=stop["ticket_id"],
                start=start,
                end=end,
                arrival=arrival,
                waiting_minutes=stop.get("waiting_minutes")
                or (_minutes(start - arrival) if arrival else 0),
                sequence=stop.get("sequence"),
            )
        )
    return visits, travel


def build_worker_day(
    day: date,
    *,
    shift_start: time,
    shift_end: time,
    route_stops: list[dict] | None,
    tickets: list[dict],
    available: bool = True,
    unavailable_at: datetime | None = None,
    unavailable_until: datetime | None = None,
) -> WorkerDay:
    """Combine the saved route with the tickets actually assigned for the day."""
    start, end = planning_shift(day, shift_start, shift_end)
    visits, travel = route_visits(route_stops or [])
    assigned = {ticket["id"]: ticket for ticket in tickets}
    conflicts: list[Conflict] = []

    stale = sorted(visit.ticket_id for visit in visits if visit.ticket_id not in assigned)
    if stale:
        conflicts.append(
            Conflict(
                "route_outdated",
                "Маршрут содержит заявки, которые больше не запланированы "
                "у исполнителя на этот день",
                stale,
            )
        )
        visits = [visit for visit in visits if visit.ticket_id in assigned]
    in_route = {visit.ticket_id for visit in visits}
    missing = sorted(ticket_id for ticket_id in assigned if ticket_id not in in_route)
    if route_stops and missing:
        conflicts.append(
            Conflict(
                "not_in_route",
                "Назначенные на день заявки отсутствуют в сохранённом маршруте",
                missing,
            )
        )
    for ticket_id in missing:
        ticket = assigned[ticket_id]
        visits.append(
            Visit(
                ticket_id=ticket_id,
                start=ticket["planned_start_at"],
                end=ticket["planned_end_at"],
                source="ticket",
            )
        )
    moved = sorted(
        visit.ticket_id
        for visit in visits
        if visit.source == "route"
        and (
            assigned[visit.ticket_id]["planned_start_at"] != visit.start
            or assigned[visit.ticket_id]["planned_end_at"] != visit.end
        )
    )
    if moved:
        conflicts.append(
            Conflict(
                "route_time_mismatch",
                "Плановое время заявки отличается от времени в сохранённом маршруте",
                moved,
            )
        )

    visits.sort(key=lambda visit: (visit.start, visit.ticket_id))
    overlapping = sorted(
        {
            ticket_id
            for previous, current in zip(visits, visits[1:])
            if current.start < previous.end
            for ticket_id in (previous.ticket_id, current.ticket_id)
        }
    )
    if overlapping:
        conflicts.append(
            Conflict("visits_overlap", "Визиты исполнителя пересекаются по времени", overlapping)
        )
    outside = sorted(visit.ticket_id for visit in visits if visit.start < start or visit.end > end)
    if outside:
        conflicts.append(Conflict("outside_shift", "Визит выходит за пределы смены", outside))
    if not available and visits:
        absent_from = unavailable_at or start
        absent_until = unavailable_until or end
        absent = sorted(
            visit.ticket_id
            for visit in visits
            if visit.start < absent_until and visit.end > absent_from
        )
        if absent:
            conflicts.append(
                Conflict(
                    "during_absence",
                    "Визит приходится на время, когда исполнитель недоступен",
                    absent,
                )
            )

    service = sum(_minutes(visit.end - visit.start) for visit in visits)
    overtime = sum(
        _minutes(min(visit.end, max(visit.start, start)) - visit.start)
        + _minutes(visit.end - max(visit.start, end))
        for visit in visits
        if visit.start < start or visit.end > end
    )
    return WorkerDay(
        shift_start=start,
        shift_end=end,
        available=available,
        visits=visits,
        service_minutes=service,
        travel_minutes=travel,
        waiting_minutes=sum(visit.waiting_minutes for visit in visits),
        overtime_minutes=overtime,
        conflicts=conflicts,
    )

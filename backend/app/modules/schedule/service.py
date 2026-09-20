"""Build the day timeline without HTTP-specific exceptions."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import RowMapping
from sqlalchemy.orm import Session

from app.modules.schedule import repository
from app.modules.schedule.schemas import (
    ScheduleBrigade,
    ScheduleForeman,
    ScheduleRead,
    ScheduleTicket,
    ScheduleWorker,
    ShiftInterval,
)
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead

# The project plans in Moscow time, as routing does; Moscow has no daylight saving time.
MOSCOW = timezone(timedelta(hours=3))


class OfficeNotFoundError(Exception):
    pass


def today() -> date:
    return datetime.now(MOSCOW).date()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0), MOSCOW)
    return start, start + timedelta(days=1)


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


def _worker(row: RowMapping, day: date, tickets: dict[int, list[ScheduleTicket]]) -> ScheduleWorker:
    return ScheduleWorker(
        id=row["id"],
        full_name=_full_name(row["surname"], row["name"], row["lastname"]),
        transport_type=row["transport_type"],
        workshift_start=row["workshift_start"],
        workshift_end=row["workshift_end"],
        shifts=shift_intervals(day, row["workshift_start"], row["workshift_end"]),
        tickets=tickets.get(row["id"], []),
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
        brigade_workers[row["brigade_id"]].append(_worker(row, day, tickets))

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
        unassigned_workers=[_worker(row, day, tickets) for row in unassigned],
    )

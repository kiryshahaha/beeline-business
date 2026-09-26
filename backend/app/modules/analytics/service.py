"""Business rules for ticket analytics."""

from collections import defaultdict
from datetime import date, datetime

from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.core.workday import MOSCOW, Period, day_bounds, period_bounds, today
from app.modules.analytics import repository
from app.modules.analytics.schemas import (
    ActivityDetails,
    ActivityItem,
    ActivityPerson,
    ActivityTicket,
    AnalyticsPeriod,
    BrigadeWorkloadItem,
    FastStats,
    TicketsSummary,
)
from app.modules.brigades.repository import find_brigade_by_foreman
from app.modules.execution.enums import TicketLifecycleState
from app.modules.execution.service import _LEGACY_STATUS_BY_STATE as STATUS_OF_STATE
from app.modules.schedule.service import load_worker_days
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead


def _foreman_brigade(session: Session, current_user: UserRead) -> tuple[bool, int | None]:
    """(visible, brigade_id): a foreman without a brigade sees nothing at all."""
    if current_user.role != UserRole.FOREMAN:
        return True, None
    brigade = find_brigade_by_foreman(session, current_user.id)
    return (brigade is not None), (brigade["id"] if brigade else None)


def get_tickets_summary(
    session: Session,
    *,
    period: AnalyticsPeriod,
    office_id: int | None,
    current_user: UserRead,
    plan_date: date | None = None,
    now: datetime | None = None,
) -> TicketsSummary:
    period_start, period_end = period_bounds(Period(period.value), now)
    plan_date = plan_date or (now.astimezone(MOSCOW).date() if now else today())
    plan_start, plan_end = day_bounds(plan_date)
    visible, brigade_id = _foreman_brigade(session, current_user)
    counts = dict.fromkeys(
        (
            "open_unassigned",
            "open_assigned",
            "in_progress",
            "created_in_period",
            "completed_in_period",
            "planned_for_date",
        ),
        0,
    )
    if visible:
        row = repository.find_tickets_summary(
            session,
            period_start=period_start,
            period_end=period_end,
            plan_start=plan_start,
            plan_end=plan_end,
            # A foreman's scope is the brigade; a requested office never widens it.
            office_id=None if brigade_id is not None else office_id,
            brigade_id=brigade_id,
        )
        counts = {key: int(row[key]) for key in counts}
    return TicketsSummary(
        period_start=period_start,
        period_end=period_end,
        plan_date=plan_date,
        open=counts["open_unassigned"],
        assigned=counts["open_assigned"],
        completed=counts["completed_in_period"],
        **counts,
    )


def get_fast_stats(
    session: Session,
    *,
    office_id: int | None,
    current_user: UserRead,
) -> FastStats:
    if current_user.role == UserRole.FOREMAN:
        # If foreman, they can only view stats for their office / brigade area
        brigade = find_brigade_by_foreman(session, current_user.id)
        if brigade:
            office_id = brigade["office_id"]
        else:
            return FastStats(
                sla_compliance_percent=100,
                at_risk_tickets_count=0,
                average_delay_minutes=0,
                idle_workers_count=0,
            )

    data = repository.find_fast_stats(
        session,
        office_id=office_id,
    )
    return FastStats(**data)


def get_brigades_workload(
    session: Session,
    *,
    current_user: UserRead,
    day: date | None = None,
) -> list[BrigadeWorkloadItem]:
    """Capacity and load of each visible brigade for one date, from the same worker
    days the schedule shows: the planner's shift, saved routes and dated absences."""
    day = day or today()
    visible, brigade_id = _foreman_brigade(session, current_user)
    if not visible:
        return []
    day_start, day_end = day_bounds(day)
    rows = repository.find_brigade_members(session, brigade_id=brigade_id)
    workers = [row for row in rows if row["id"] is not None]
    days = load_worker_days(session, day, workers)
    completed = repository.find_completed_by_brigade(
        session, day_start=day_start, day_end=day_end, brigade_id=brigade_id
    )

    names: dict[int, str] = {}
    members: dict[int, list[int]] = defaultdict(list)
    for row in rows:
        names[row["brigade_id"]] = row["brigade_name"]
        if row["id"] is not None:
            members[row["brigade_id"]].append(row["id"])
    result = []
    for brigade, name in names.items():
        timelines = [days[worker_id].timeline for worker_id in members[brigade]]
        tickets = sum(len(timeline.visits) for timeline in timelines)
        result.append(
            BrigadeWorkloadItem(
                brigade_id=brigade,
                brigade_name=name,
                date=day,
                workers=len(timelines),
                available_workers=sum(timeline.available for timeline in timelines),
                tickets=tickets,
                shift_minutes=sum(timeline.shift_minutes for timeline in timelines),
                service_minutes=sum(timeline.service_minutes for timeline in timelines),
                travel_minutes=sum(timeline.travel_minutes for timeline in timelines),
                waiting_minutes=sum(timeline.waiting_minutes for timeline in timelines),
                free_minutes=sum(timeline.free_minutes for timeline in timelines),
                overtime_minutes=sum(timeline.overtime_minutes for timeline in timelines),
                conflicts=sum(len(timeline.conflicts) for timeline in timelines),
                active_tickets=tickets,
                completed_today=completed.get(brigade, 0),
            )
        )
    return result


def _person(row: RowMapping, prefix: str) -> ActivityPerson | None:
    if row[f"{prefix}_id"] is None:
        return None
    return ActivityPerson(
        id=row[f"{prefix}_id"],
        full_name=f"{row[f'{prefix}_surname']} {row[f'{prefix}_name']}",
        role=row[f"{prefix}_role"],
    )


def _state(value: str | None) -> TicketLifecycleState | None:
    return TicketLifecycleState(value) if value else None


def _activity_item(row: RowMapping) -> ActivityItem:
    excerpt = row["comment_excerpt"]
    if excerpt is not None and row["comment_truncated"]:
        excerpt += "…"
    previous_state, state = _state(row["previous_state"]), _state(row["new_state"])
    return ActivityItem(
        kind=row["kind"],
        occurred_at=row["occurred_at"],
        ticket=ActivityTicket(
            id=row["ticket_id"],
            title=row["ticket_title"],
            work_type_id=row["work_type_id"],
            work_type=row["work_type"],
            category=row["category"],
            priority=row["priority"],
            received_at=row["received_at"],
            sla_deadline_at=row["sla_deadline_at"],
            status=row["ticket_status"],
        ),
        actor=_person(row, "actor"),
        details=ActivityDetails(
            previous_status=STATUS_OF_STATE.get(previous_state),
            status=STATUS_OF_STATE.get(state),
            previous_state=previous_state,
            state=state,
            worker=_person(row, "assignee"),
            previous_worker=_person(row, "previous"),
            assignment_source=row["assignment_source"],
            reason=row["reason"],
            comment_id=row["comment_id"],
            comment_excerpt=excerpt,
        ),
    )


def get_recent_activity(
    session: Session,
    *,
    limit: int,
    offset: int,
    current_user: UserRead,
) -> list[ActivityItem]:
    visible, brigade_id = _foreman_brigade(session, current_user)
    if not visible:
        return []
    rows = repository.find_recent_activity(
        session, limit=limit, offset=offset, brigade_id=brigade_id
    )
    return [_activity_item(row) for row in rows]

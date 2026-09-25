"""Business rules for ticket analytics."""

from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

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
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead


def get_tickets_summary(
    session: Session,
    *,
    period: AnalyticsPeriod,
    office_id: int | None,
    current_user: UserRead,
) -> TicketsSummary:
    brigade_id = None
    if current_user.role == UserRole.FOREMAN:
        brigade = find_brigade_by_foreman(session, current_user.id)
        if brigade is None:
            return TicketsSummary(open=0, assigned=0, in_progress=0, completed=0)
        brigade_id = brigade["id"]
        office_id = None

    row = repository.find_tickets_summary(
        session,
        period=period,
        office_id=office_id,
        brigade_id=brigade_id,
    )
    return TicketsSummary(
        open=int(row["open"]),
        assigned=int(row["assigned"]),
        in_progress=int(row["in_progress"]),
        completed=int(row["completed"]),
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
) -> list[BrigadeWorkloadItem]:
    brigade_id = None
    if current_user.role == UserRole.FOREMAN:
        brigade = find_brigade_by_foreman(session, current_user.id)
        if brigade is None:
            return []
        brigade_id = brigade["id"]

    rows = repository.find_brigades_workload(session, brigade_id=brigade_id)
    return [
        BrigadeWorkloadItem(
            brigade_name=row["brigade_name"],
            active_tickets=int(row["active_tickets"]),
            completed_today=int(row["completed_today"]),
        )
        for row in rows
    ]


def _person(row: RowMapping, prefix: str) -> ActivityPerson | None:
    if row[f"{prefix}_id"] is None:
        return None
    return ActivityPerson(
        id=row[f"{prefix}_id"],
        full_name=f"{row[f'{prefix}_surname']} {row[f'{prefix}_name']}",
        role=row[f"{prefix}_role"],
    )


def _activity_item(row: RowMapping) -> ActivityItem:
    excerpt = row["comment_excerpt"]
    if excerpt is not None and row["comment_truncated"]:
        excerpt += "…"
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
            previous_status=row["previous_status"],
            status=row["new_status"],
            worker=_person(row, "assignee"),
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
    brigade_id = None
    if current_user.role == UserRole.FOREMAN:
        brigade = find_brigade_by_foreman(session, current_user.id)
        if brigade is None:
            return []
        brigade_id = brigade["id"]

    rows = repository.find_recent_activity(
        session, limit=limit, offset=offset, brigade_id=brigade_id
    )
    return [_activity_item(row) for row in rows]

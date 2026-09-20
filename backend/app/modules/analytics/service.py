"""Business rules for ticket analytics."""

from sqlalchemy.orm import Session

from app.modules.analytics import repository
from app.modules.analytics.schemas import AnalyticsPeriod, TicketsSummary
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

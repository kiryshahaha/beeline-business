"""Ticket analytics HTTP endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.analytics import service
from app.modules.analytics.schemas import AnalyticsPeriod, TicketsSummary
from app.modules.auth.dependencies import require_roles
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])
DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentAnalyticsUser = Annotated[
    UserRead, Depends(require_roles(UserRole.OBSERVER, UserRole.FOREMAN))
]


@router.get("/tickets-summary", response_model=TicketsSummary)
def tickets_summary(
    period: Annotated[
        AnalyticsPeriod,
        Query(description="Период отчёта: today, week или month."),
    ],
    session: DatabaseSession,
    current_user: CurrentAnalyticsUser,
    office_id: Annotated[
        int | None,
        Query(ge=1, le=2_147_483_647, description="ID офиса для отчёта наблюдателя."),
    ] = None,
) -> TicketsSummary:
    """Return ticket counts for the requested period and visible scope."""
    return service.get_tickets_summary(
        session,
        period=period,
        office_id=office_id,
        current_user=current_user,
    )

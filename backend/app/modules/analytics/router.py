"""Ticket analytics HTTP endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.analytics import service
from app.modules.analytics.schemas import (
    ActivityItem,
    AnalyticsPeriod,
    BrigadeWorkloadItem,
    FastStats,
    TicketsSummary,
)
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


@router.get("/fast-stats", response_model=FastStats)
def fast_stats(
    session: DatabaseSession,
    current_user: CurrentAnalyticsUser,
    office_id: Annotated[
        int | None,
        Query(ge=1, le=2_147_483_647, description="ID офиса для отчёта наблюдателя."),
    ] = None,
) -> FastStats:
    """Return fast operational stats for today."""
    return service.get_fast_stats(
        session,
        office_id=office_id,
        current_user=current_user,
    )


@router.get("/brigades-workload", response_model=list[BrigadeWorkloadItem])
def brigades_workload(
    session: DatabaseSession,
    current_user: CurrentAnalyticsUser,
) -> list[BrigadeWorkloadItem]:
    """Return workload counts for every visible brigade."""
    return service.get_brigades_workload(session, current_user=current_user)


@router.get("/recent-activity", response_model=list[ActivityItem])
def recent_activity(
    session: DatabaseSession,
    current_user: CurrentAnalyticsUser,
    limit: Annotated[int, Query(ge=1, le=100, description="Сколько событий вернуть.")] = 20,
    offset: Annotated[
        int, Query(ge=0, le=2_147_483_647, description="Сколько свежих событий пропустить.")
    ] = 0,
) -> list[ActivityItem]:
    """Получить общую ленту последних изменений по заявкам, новые сверху.

    Наблюдатель видит все заявки, бригадир — только заявки исполнителей своей бригады.
    """
    return service.get_recent_activity(
        session, limit=limit, offset=offset, current_user=current_user
    )

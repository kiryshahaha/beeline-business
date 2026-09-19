"""HTTP endpoints for downloadable reports."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth.dependencies import require_roles
from app.modules.reports import service
from app.modules.tickets.enums import TicketStatus
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])
DatabaseSession = Annotated[Session, Depends(get_session)]
Observer = Annotated[UserRead, Depends(require_roles(UserRole.OBSERVER))]


@router.get(
    "/tickets/export",
    response_class=Response,
    responses={
        200: {
            "description": "Файл с отфильтрованными заявками.",
            "content": {
                "text/csv": {},
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
            },
        }
    },
)
def export_tickets(
    session: DatabaseSession,
    _observer: Observer,
    format: Annotated[Literal["csv", "xlsx"], Query(description="Формат файла.")] = "xlsx",
    status: Annotated[TicketStatus | None, Query(description="Фильтр по статусу заявки.")] = None,
    city_id: Annotated[
        int | None, Query(ge=1, le=2_147_483_647, description="ID города места выполнения.")
    ] = None,
    district_id: Annotated[
        int | None, Query(ge=1, le=2_147_483_647, description="ID района места выполнения.")
    ] = None,
    brigade_id: Annotated[
        int | None,
        Query(ge=1, le=2_147_483_647, description="ID бригады назначенных исполнителей."),
    ] = None,
) -> Response:
    """Download all tickets matching the supplied filters."""

    exported = service.export_tickets(
        session,
        format=format,
        status=status,
        city_id=city_id,
        district_id=district_id,
        brigade_id=brigade_id,
    )
    return Response(
        content=exported.content,
        media_type=exported.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{exported.filename}"',
            "Cache-Control": "no-store",
        },
    )

"""HTTP endpoints for downloadable reports."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth.dependencies import require_roles
from app.modules.planning.router import get_clock
from app.modules.reports import plans, service
from app.modules.reports.errors import ReportError
from app.modules.reports.tables import (
    CSV_MEDIA_TYPE,
    XLSX_MEDIA_TYPE,
    ZIP_MEDIA_TYPE,
    ExportFile,
)
from app.modules.tickets.enums import TicketStatus
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])
DatabaseSession = Annotated[Session, Depends(get_session)]
Observer = Annotated[UserRead, Depends(require_roles(UserRole.OBSERVER))]
REFUSALS = {
    404: {"description": "План не найден."},
    422: {
        "description": (
            "Неверный параметр, превышен лимит строк выгрузки или текст длиннее ячейки XLSX "
            "(`detail.code`: `report_too_large`, `xlsx_cell_too_long`)."
        )
    },
}


def download(exported: ExportFile) -> StreamingResponse:
    return StreamingResponse(
        exported.chunks(),
        media_type=exported.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{exported.filename}"',
            "Content-Length": str(exported.size),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/tickets/export",
    response_class=Response,
    responses={
        200: {
            "description": "Файл с отфильтрованными заявками.",
            "content": {CSV_MEDIA_TYPE: {}, XLSX_MEDIA_TYPE: {}},
        },
        422: REFUSALS[422],
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
) -> StreamingResponse:
    """Download all tickets matching the supplied filters."""

    try:
        exported = service.export_tickets(
            session,
            format=format,
            status=status,
            city_id=city_id,
            district_id=district_id,
            brigade_id=brigade_id,
        )
    except ReportError as error:
        raise HTTPException(error.status, detail=error.detail) from error
    return download(exported)


@router.get(
    "/plans/{plan_id}/export",
    response_class=Response,
    responses={
        200: {
            "description": (
                "Отчёт по плану: сводка и метрики, маршруты, порядок и время визитов, "
                "причины неназначения. XLSX — листы, CSV — ZIP с таблицами."
            ),
            "content": {XLSX_MEDIA_TYPE: {}, ZIP_MEDIA_TYPE: {}},
        },
        **REFUSALS,
    },
)
def export_plan(
    plan_id: UUID,
    session: DatabaseSession,
    _observer: Observer,
    format: Annotated[
        Literal["csv", "xlsx"], Query(description="xlsx — листы, csv — ZIP с CSV-таблицами.")
    ] = "xlsx",
    clock=Depends(get_clock),
) -> StreamingResponse:
    """Download one preview or applied plan as a report, separate from the ticket export."""

    try:
        exported = plans.export_plan(session, plan_id, format=format, clock=clock)
    except ReportError as error:
        raise HTTPException(error.status, detail=error.detail) from error
    return download(exported)

"""Dispatcher-only API for complete domain exports and transactional file imports."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth.dependencies import require_roles
from app.modules.data_exchange.formats import MAX_FILE_BYTES, ExchangeError, parse_file, serialize
from app.modules.data_exchange.registry import describe_tables
from app.modules.data_exchange.service import export_data, import_data
from app.modules.users.enums import UserRole

router = APIRouter(
    prefix="/api/v1/data",
    tags=["data-exchange"],
    dependencies=[Depends(require_roles(UserRole.OBSERVER))],
)
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.get("/schema")
def get_schema():
    return describe_tables()


@router.get("/export")
def export_all(session: DatabaseSession, format: Literal["csv", "xlsx"] = "xlsx"):
    try:
        content = serialize(export_data(session), format)
    except ExchangeError as error:
        raise HTTPException(422, error.detail) from error
    extension = "zip" if format == "csv" else "xlsx"
    media_type = (
        "application/zip"
        if format == "csv"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return Response(
        content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="beeline-data.{extension}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/import")
def import_all(
    file: UploadFile,
    session: DatabaseSession,
    dry_run: bool = True,
    entity: Annotated[str | None, Query(max_length=50)] = None,
):
    """По умолчанию только проверка; dry_run=false сохраняет весь пакет одной транзакцией."""
    content = file.file.read(MAX_FILE_BYTES + 1)
    try:
        data = parse_file(content, file.filename or "", entity)
        return import_data(session, data, dry_run=dry_run)
    except ExchangeError as error:
        raise HTTPException(422, error.detail) from error

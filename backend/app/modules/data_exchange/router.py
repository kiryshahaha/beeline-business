"""Dispatcher-only API for complete domain exports and transactional file imports."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile
from sqlalchemy import text
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


@router.post("/clear")
def clear_all_data(session: DatabaseSession):
    """Стереть все бизнес-данные (заявки, маршруты, адреса, локации и т.д.), сохранив учетные записи пользователей."""
    tables_res = session.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "AND table_name NOT IN ('alembic_version', 'users', 'refresh_tokens')"
        )
    ).fetchall()
    if tables_res:
        table_names = ", ".join(f'"{t[0]}"' for t in tables_res)
        session.execute(text(f"TRUNCATE TABLE {table_names} CASCADE;"))

    # Восстанавливаем 4 канонических вида работ по регламенту кейса
    session.execute(
        text(
            """
            INSERT INTO work_types (name, code, category, default_priority, travel_minutes, work_minutes, documents_minutes)
            VALUES 
                ('Подключение клиентов Базовая', 'connection', 'connection', 2, 20, 60, 10),
                ('Аварий на ТКД', 'emergency', 'emergency', 1, 20, 80, 0),
                ('Дозаказ оборудования', 'additional', 'additional', 3, 20, 10, 10),
                ('Локальная заявка/ремонт у клиента', 'repair', 'repair', 3, 20, 30, 0)
            ON CONFLICT (lower(name)) DO NOTHING;
            """
        )
    )
    session.commit()
    return {
        "success": True,
        "message": "Все бизнес-данные успешно очищены. Учетные записи пользователей сохранены.",
    }


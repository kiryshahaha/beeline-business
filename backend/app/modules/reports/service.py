"""Build CSV and XLSX downloads from filtered ticket rows."""

from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session

from app.core.spreadsheet import XLSX_MAX_CELL_UNITS
from app.modules.reports import repository
from app.modules.reports.errors import ReportError
from app.modules.reports.tables import (
    CSV_MEDIA_TYPE,
    XLSX_MEDIA_TYPE,
    CellTooLongError,
    ExportFile,
    Table,
    build_file,
    write_csv,
    write_xlsx,
)
from app.modules.tickets.enums import TicketStatus

MOSCOW = ZoneInfo("Europe/Moscow")

EXPORT_COLUMNS = (
    "id",
    "location_id",
    "title",
    "description",
    "work_type",
    "work_type_id",
    "category",
    "priority",
    "received_at",
    "sla_deadline_at",
    "required_transport_type",
    "service_duration_source",
    "status",
    "visit_window_start",
    "visit_window_end",
    "planned_start_at",
    "planned_end_at",
    "estimated_duration_minutes",
    "actual_duration_minutes",
    "created_at",
    "assigned_worker_id",
    "is_pinned",
    "city_id",
    "city",
    "service_area_id",
    "district",
    "street_id",
    "street",
    "building_id",
    "building_number",
    "block",
    "entrance_id",
    "entrance_number",
    "floor",
    "apartment",
    "latitude",
    "longitude",
    "address",
)

HUMAN_COLUMNS = (
    "ID заявки",
    "Название",
    "Описание",
    "Вид работ",
    "Категория",
    "Приоритет",
    "Статус",
    "Состояние",
    "Исполнитель",
    "Бригада",
    "Адрес",
    "Город",
    "Район / Участок",
    "Окно визита с (МСК)",
    "Окно визита по (МСК)",
    "Плановое начало (МСК)",
    "Плановое окончание (МСК)",
    "Фактическое начало (МСК)",
    "Фактическое окончание (МСК)",
    "Норматив (мин)",
    "Фактическая длительность (мин)",
    "Дедлайн SLA (МСК)",
    "Причина отмены",
    "Закреплена",
    "Время создания (МСК)",
)

HUMAN_COLUMN_WIDTHS = {
    0: 12,  # ID
    1: 30,  # Название
    2: 35,  # Описание
    3: 25,  # Вид работ
    4: 16,  # Категория
    5: 12,  # Приоритет
    6: 16,  # Статус
    7: 20,  # Состояние
    8: 28,  # Исполнитель
    9: 20,  # Бригада
    10: 38,  # Адрес
    11: 18,  # Город
    12: 24,  # Район / Участок
    13: 20,  # Окно с
    14: 20,  # Окно по
    15: 20,  # План начало
    16: 20,  # План конец
    17: 20,  # Факт начало
    18: 20,  # Факт конец
    19: 16,  # Норматив
    20: 18,  # Факт длительность
    21: 20,  # SLA
    22: 25,  # Причина отмены
    23: 14,  # Закреплена
    24: 20,  # Создана
}

STATUS_TRANSLATIONS = {
    "planned": "Запланирована",
    "in_progress": "В работе",
    "completed": "Выполнена",
    "wont_fix": "Отменена",
}

STATE_TRANSLATIONS = {
    "waiting_assignment": "Ожидает назначения",
    "assigned": "Назначена",
    "dispatched": "Отправлена",
    "en_route": "В пути",
    "arrived": "Прибыл на объект",
    "in_progress": "В работе",
    "completion_requested": "Запрос завершения",
    "completed": "Выполнена",
    "cancelled": "Отменена",
}

CATEGORY_TRANSLATIONS = {
    "emergency": "Аварийная",
    "repair": "Ремонт",
    "connection": "Подключение",
    "maintenance": "Обслуживание",
}

# At the limit XLSX takes about 11 s and CSV about 3 s; memory stays bounded either way.
MAX_EXPORT_ROWS = 50_000


def too_large(rows: int | None) -> ReportError:
    return ReportError(
        422,
        "report_too_large",
        f"В выгрузку попадает больше {MAX_EXPORT_ROWS} строк; уточните фильтры",
        rows=rows,
        max_rows=MAX_EXPORT_ROWS,
    )


def _address(row: dict[str, Any]) -> str:
    parts = [row["city"], row["district"], row["street"], f"д. {row['building_number']}"]
    if row["block"] is not None:
        parts.append(row["block"])
    if row["entrance_number"] is not None:
        parts.append(f"подъезд {row['entrance_number']}")
    if row["floor"] is not None:
        parts.append(f"этаж {row['floor']}")
    if row["apartment"] is not None:
        parts.append(f"кв./пом. {row['apartment']}")
    return ", ".join(parts)


def _format_msk(dt: Any) -> str:
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(MOSCOW).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(dt, date):
        return dt.isoformat()
    return str(dt)


def _export_row_raw(row: dict[str, Any]) -> list[Any]:
    values = dict(row)
    values["assigned_worker_id"] = (
        str(values["assigned_worker_id"]) if values["assigned_worker_id"] else ""
    )
    values["address"] = _address(values)
    return [values[column] for column in EXPORT_COLUMNS]


def _export_row_human(
    row: dict[str, Any],
    workers: dict[int, str],
    brigades: dict[int, str],
) -> list[Any]:
    worker_id = row.get("assigned_worker_id")
    worker_label = workers.get(worker_id) if worker_id else ""
    if not worker_label and worker_id:
        worker_label = f"Инженер #{worker_id}"

    brigade_id = row.get("brigade_id")
    brigade_label = brigades.get(brigade_id) if brigade_id else ""
    if not brigade_label and brigade_id:
        brigade_label = f"Бригада #{brigade_id}"

    status = row.get("status")
    status_label = STATUS_TRANSLATIONS.get(status, status or "")

    state = row.get("state")
    state_label = STATE_TRANSLATIONS.get(state, state or "")

    category = row.get("category")
    if hasattr(category, "value"):
        category = category.value
    category_label = CATEGORY_TRANSLATIONS.get(category, category or "")

    is_pinned = "Да" if row.get("is_pinned") else "Нет"

    return [
        row.get("id"),
        row.get("title") or "",
        row.get("description") or "",
        row.get("work_type") or "",
        category_label,
        row.get("priority") or "",
        status_label,
        state_label,
        worker_label,
        brigade_label,
        _address(row),
        row.get("city") or "",
        row.get("district") or "",
        _format_msk(row.get("visit_window_start")),
        _format_msk(row.get("visit_window_end")),
        _format_msk(row.get("planned_start_at")),
        _format_msk(row.get("planned_end_at")),
        _format_msk(row.get("actual_started_at")),
        _format_msk(row.get("actual_completed_at")),
        row.get("estimated_duration_minutes") or "",
        row.get("actual_duration_minutes") or "",
        _format_msk(row.get("sla_deadline_at")),
        row.get("cancel_reason") or "",
        is_pinned,
        _format_msk(row.get("created_at")),
    ]


def _export_rows_raw(rows: Iterable[RowMapping]) -> Iterator[list[Any]]:
    for number, row in enumerate(rows, 1):
        if number > MAX_EXPORT_ROWS:
            raise too_large(None)
        yield _export_row_raw(dict(row))


def _export_rows_human(
    rows: Iterable[RowMapping],
    workers: dict[int, str],
    brigades: dict[int, str],
) -> Iterator[list[Any]]:
    for number, row in enumerate(rows, 1):
        if number > MAX_EXPORT_ROWS:
            raise too_large(None)
        yield _export_row_human(dict(row), workers, brigades)


def export_tickets(
    session: Session,
    *,
    format: str,
    status: TicketStatus | None,
    city_id: int | None,
    service_area_id: int | None,
    brigade_id: int | None,
    date_from: date | None = None,
    date_to: date | None = None,
    exclude_cancelled: bool = False,
    profile: str = "human",
) -> ExportFile:
    filters = {
        "status": status.value if status is not None else None,
        "city_id": city_id,
        "service_area_id": service_area_id,
        "brigade_id": brigade_id,
        "date_from": date_from,
        "date_to": date_to,
        "exclude_cancelled": exclude_cancelled,
    }

    def write(file) -> None:
        with session.begin():
            total = repository.count_tickets(session, **filters)
            if total > MAX_EXPORT_ROWS:
                raise too_large(total)
            with repository.stream_tickets(session, limit=MAX_EXPORT_ROWS + 1, **filters) as rows:
                if profile == "raw":
                    table = Table("tickets", EXPORT_COLUMNS, _export_rows_raw(rows), delimiter=",")
                else:
                    workers = repository.worker_names(
                        session,
                        session.execute(text("SELECT id FROM users")).scalars().all(),
                    )
                    brigades = repository.brigade_names(
                        session,
                        session.execute(text("SELECT id FROM brigades")).scalars().all(),
                    )
                    table = Table(
                        "tickets",
                        HUMAN_COLUMNS,
                        _export_rows_human(rows, workers, brigades),
                        delimiter=";",
                        column_widths=HUMAN_COLUMN_WIDTHS,
                    )

                if format == "csv":
                    write_csv(file, table)
                else:
                    write_xlsx(file, [table])

    try:
        if format == "csv":
            return build_file(write, CSV_MEDIA_TYPE, "tickets.csv")
        return build_file(write, XLSX_MEDIA_TYPE, "tickets.xlsx")
    except CellTooLongError as error:
        ticket_id = error.values[0] if error.values else "N/A"
        raise ReportError(
            422,
            "xlsx_cell_too_long",
            f"Текст поля {error.column} заявки №{ticket_id} длиннее лимита ячейки XLSX "
            f"({XLSX_MAX_CELL_UNITS}); выгрузите CSV — в нём значение сохраняется полностью",
            ticket_id=ticket_id,
            column=error.column,
            length=error.length,
            max_length=XLSX_MAX_CELL_UNITS,
        ) from error

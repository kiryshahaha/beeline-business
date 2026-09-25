"""Build CSV and XLSX downloads from filtered ticket rows."""

from collections.abc import Iterable, Iterator
from typing import Any

from sqlalchemy import RowMapping
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
    "updated_at",
    "assignee_ids",
    "city_id",
    "city",
    "district_id",
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


def _export_row(row: dict[str, Any]) -> list[Any]:
    values = dict(row)
    values["assignee_ids"] = ",".join(str(worker_id) for worker_id in values["assignee_ids"])
    values["address"] = _address(values)
    return [values[column] for column in EXPORT_COLUMNS]


def _export_rows(rows: Iterable[RowMapping]) -> Iterator[list[Any]]:
    for number, row in enumerate(rows, 1):
        # Tickets committed after the count must not stretch the file past the limit.
        if number > MAX_EXPORT_ROWS:
            raise too_large(None)
        yield _export_row(dict(row))


def export_tickets(
    session: Session,
    *,
    format: str,
    status: TicketStatus | None,
    city_id: int | None,
    district_id: int | None,
    brigade_id: int | None,
) -> ExportFile:
    filters = {
        "status": status.value if status is not None else None,
        "city_id": city_id,
        "district_id": district_id,
        "brigade_id": brigade_id,
    }

    def write(file) -> None:
        with session.begin():
            total = repository.count_tickets(session, **filters)
            if total > MAX_EXPORT_ROWS:
                raise too_large(total)
            with repository.stream_tickets(session, limit=MAX_EXPORT_ROWS + 1, **filters) as rows:
                table = Table("tickets", EXPORT_COLUMNS, _export_rows(rows))
                if format == "csv":
                    write_csv(file, table)
                else:
                    write_xlsx(file, [table])

    try:
        if format == "csv":
            return build_file(write, CSV_MEDIA_TYPE, "tickets.csv")
        return build_file(write, XLSX_MEDIA_TYPE, "tickets.xlsx")
    except CellTooLongError as error:
        ticket_id = error.values[EXPORT_COLUMNS.index("id")]
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

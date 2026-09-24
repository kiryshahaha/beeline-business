"""Build CSV and XLSX downloads from filtered ticket rows."""

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, time
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.modules.reports import repository
from app.modules.tickets.enums import TicketStatus

EXPORT_COLUMNS = (
    "id",
    "location_id",
    "title",
    "description",
    "work_type",
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


@dataclass(frozen=True)
class ExportFile:
    content: bytes
    media_type: str
    filename: str


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


def _export_row(row: dict[str, Any]) -> dict[str, Any]:
    values = dict(row)
    values["assigned_worker_id"] = (
        str(values["assigned_worker_id"]) if values["assigned_worker_id"] else ""
    )
    values["address"] = _address(values)
    return values


def _cell_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def _csv_value(value: Any) -> str:
    value = _cell_value(value)
    return "" if value is None else str(value)


def _serialize_csv(rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(EXPORT_COLUMNS)
    for row in rows:
        writer.writerow([_csv_value(row.get(column)) for column in EXPORT_COLUMNS])
    return stream.getvalue().encode("utf-8-sig")


def _serialize_xlsx(rows: list[dict[str, Any]]) -> bytes:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("tickets")
    sheet.append(list(EXPORT_COLUMNS))
    for row in rows:
        sheet.append([_cell_value(row.get(column)) for column in EXPORT_COLUMNS])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def export_tickets(
    session: Session,
    *,
    format: str,
    status: TicketStatus | None,
    city_id: int | None,
    district_id: int | None,
    brigade_id: int | None,
) -> ExportFile:
    rows = repository.find_tickets(
        session,
        status=status.value if status is not None else None,
        city_id=city_id,
        district_id=district_id,
        brigade_id=brigade_id,
    )
    values = [_export_row(dict(row)) for row in rows]
    if format == "csv":
        return ExportFile(_serialize_csv(values), "text/csv", "tickets.csv")
    return ExportFile(
        _serialize_xlsx(values),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "tickets.xlsx",
    )

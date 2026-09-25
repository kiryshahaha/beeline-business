"""Readable CSV/XLSX tables: user text never becomes a formula, numbers stay numbers."""

import csv
import io
from collections.abc import Iterable, Iterator, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from tempfile import SpooledTemporaryFile
from typing import IO, Any
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ERROR_CODES

from app.core.spreadsheet import (
    XLSX_MAX_CELL_UNITS,
    XML_ILLEGAL_CHARACTERS,
    starts_like_formula,
    xlsx_length,
)

CSV_MEDIA_TYPE = "text/csv"
ZIP_MEDIA_TYPE = "application/zip"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# Files larger than this move from memory to a temporary file on disk.
SPOOL_BYTES = 8 * 1024 * 1024
CHUNK_BYTES = 64 * 1024


class CellTooLongError(ValueError):
    """XLSX cannot hold the text without cutting it; CSV keeps the whole value."""

    def __init__(self, sheet: str, column: str, length: int, values: Sequence[Any]):
        super().__init__(f"{sheet}.{column}: {length}")
        self.sheet = sheet
        self.column = column
        self.length = length
        self.values = values


@dataclass(frozen=True)
class Table:
    name: str
    columns: Sequence[str]
    rows: Iterable[Sequence[Any]]


@dataclass(frozen=True)
class ExportFile:
    """A finished file, positioned at its start; the reader must close it."""

    file: IO[bytes]
    size: int
    media_type: str
    filename: str

    def chunks(self) -> Iterator[bytes]:
        try:
            while chunk := self.file.read(CHUNK_BYTES):
                yield chunk
        finally:
            self.file.close()


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        value = value.value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def csv_cell(value: Any) -> str:
    value = _plain(value)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        # Unlike the reversible exchange format, the report adds only this visible apostrophe.
        return "'" + value if starts_like_formula(value) else value
    return str(value)


def xlsx_cell(sheet, value: Any) -> Any:
    """Return a value or cell for a write-only sheet; the text length is checked by the caller."""
    value = _plain(value)
    if not isinstance(value, str):
        return value
    if not (starts_like_formula(value) or value in ERROR_CODES):
        return value
    cell = WriteOnlyCell(sheet, value=value)
    # openpyxl stores "=..." as a formula and "#N/A" as an error unless the type is fixed.
    cell.data_type = "s"
    # Excel keeps such a cell literal even after the user edits it.
    cell.quotePrefix = True
    return cell


def _xlsx_row(sheet, table: Table, values: Sequence[Any]) -> list[Any]:
    cells = []
    for column, value in zip(table.columns, values, strict=True):
        if isinstance(value, str):
            # XML cannot store control characters: show the replacement mark, not a 500.
            value = XML_ILLEGAL_CHARACTERS.sub("\ufffd", value)
            if xlsx_length(value) > XLSX_MAX_CELL_UNITS:
                raise CellTooLongError(table.name, column, xlsx_length(value), values)
        cells.append(xlsx_cell(sheet, value))
    return cells


def write_csv(file: IO[bytes], table: Table) -> None:
    text = io.TextIOWrapper(file, encoding="utf-8-sig", newline="")
    writer = csv.writer(text, lineterminator="\r\n")
    writer.writerow(table.columns)
    for values in table.rows:
        writer.writerow([csv_cell(value) for value in values])
    text.flush()
    text.detach()


def _discard(workbook: Workbook) -> None:
    """openpyxl deletes a write-only sheet's temporary file only after a successful save."""
    for sheet in workbook.worksheets:
        writer = sheet._writer
        if writer is None:
            continue
        with suppress(Exception):
            if not sheet.closed:
                sheet.close()
        with suppress(OSError, ValueError):
            writer.cleanup()


def write_xlsx(file: IO[bytes], tables: Iterable[Table]) -> None:
    workbook = Workbook(write_only=True)
    try:
        for table in tables:
            sheet = workbook.create_sheet(table.name)
            sheet.append(list(table.columns))
            for values in table.rows:
                sheet.append(_xlsx_row(sheet, table, values))
        workbook.save(file)
    except BaseException:
        # A refused row must not leave partial ticket data in the temporary directory.
        _discard(workbook)
        raise


def write_csv_zip(file: IO[bytes], tables: Iterable[Table]) -> None:
    with ZipFile(file, "w", compression=ZIP_DEFLATED) as archive:
        for table in tables:
            with archive.open(table.name + ".csv", "w") as entry:
                write_csv(entry, table)


def build_file(writer, media_type: str, filename: str) -> ExportFile:
    """Run writer(file) into a spooled temporary file; memory stays bounded for large files."""
    file = SpooledTemporaryFile(max_size=SPOOL_BYTES)
    try:
        writer(file)
        file.seek(0, io.SEEK_END)
        size = file.tell()
        file.seek(0)
    except BaseException:
        file.close()
        raise
    return ExportFile(file, size, media_type, filename)

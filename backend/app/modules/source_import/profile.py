"""Read the organizer's day file: one table per sheet, the office address below it.

Nothing here touches the database. Every kept cell stays as the original text, so the
provenance record can show exactly what the file said.
"""

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from zipfile import BadZipFile
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

MOSCOW = ZoneInfo("Europe/Moscow")
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5_000
MAX_CELL_CHARS = 1_000

# Header spelling differs between exports; the key is the meaning, not the text.
HEADER_ALIASES = {
    "external_id": ("заявка", "номер заявки", "id заявки", "№ заявки"),
    "bk_type": ("тип заявки bk", "тип заявки вк", "тип bk", "тип вк"),
    "bk_status": ("статус bk", "статус вк"),
    "hd_type": ("тип заявки hd", "тип hd"),
    "window_start": ("начало", "начало окна"),
    "window_end": ("окончание", "конец", "конец окна"),
    "district": ("район",),
    "address": ("адрес",),
    "brigade": ("бригада", "исполнитель"),
    "connection": ("подключение", "технология подключения"),
    "gigabit": ("гигабитное подключение",),
}
REQUIRED = ("external_id", "bk_type", "window_start", "window_end", "district", "address")
OFFICE_LABEL = "адрес офиса"
TIME_FORMATS = ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S")


class SourceFormatError(ValueError):
    def __init__(self, message: str, *, sheet: str | None = None, row: int | None = None):
        super().__init__(message)
        self.detail = {"message": message, "sheet": sheet, "row": row}


def normalize(text: str) -> str:
    return " ".join(str(text).replace("\xa0", " ").split()).lower().replace("ё", "е")


ALIASES = {normalize(alias): name for name, aliases in HEADER_ALIASES.items() for alias in aliases}


@dataclass
class SourceRow:
    sheet: str | None
    number: int
    values: dict[str, str]
    raw: dict[str, str]


@dataclass
class SourceFile:
    filename: str
    sha256: str
    encoding: str | None
    delimiter: str | None
    columns: dict[str, str]
    unknown_columns: list[str]
    rows: list[SourceRow]
    office_address: str | None = None
    office_row: int | None = None
    sheets: list[str] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    @property
    def is_control(self) -> bool:
        return "brigade" in self.columns or "bk_status" in self.columns


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).replace("\xa0", " ").split())


def _decode(content: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise SourceFormatError("Файл не в UTF-8 и не в Windows-1251")


def _table(result: SourceFile, sheet: str | None, rows) -> None:
    header, start = None, 0
    rows = [[_cell(value) for value in row] for row in rows]
    for index, row in enumerate(rows):
        if any(row):
            header, start = row, index
            break
    if header is None:
        result.warnings.append({"sheet": sheet, "row": None, "message": "Пустой лист пропущен"})
        return
    columns: dict[str, int] = {}
    for position, title in enumerate(header):
        name = ALIASES.get(normalize(title))
        if name is not None and name not in columns:
            columns[name] = position
        elif title and title not in result.unknown_columns:
            result.unknown_columns.append(title)
    missing = [name for name in REQUIRED if name not in columns]
    if missing:
        if sheet is not None and len(columns) < 2:
            result.warnings.append(
                {"sheet": sheet, "row": start + 1, "message": "Лист без таблицы заявок пропущен"}
            )
            return
        titles = ", ".join(HEADER_ALIASES[name][0] for name in missing)
        raise SourceFormatError(f"Нет столбцов: {titles}", sheet=sheet, row=start + 1)
    if result.columns and set(result.columns) != set(columns):
        raise SourceFormatError("Листы файла имеют разные столбцы", sheet=sheet, row=start + 1)
    result.columns = {name: header[position] for name, position in columns.items()}
    if sheet is not None:
        result.sheets.append(sheet)
    after_office = False
    for index in range(start + 1, len(rows)):
        row, number = rows[index], index + 1
        if not any(row):
            continue
        if normalize(row[0]).startswith(OFFICE_LABEL):
            address = next((cell for cell in row[1:] if cell), "")
            if not address:
                raise SourceFormatError("Строка адреса офиса пуста", sheet=sheet, row=number)
            if result.office_address not in (None, address):
                raise SourceFormatError("В файле два разных адреса офиса", sheet=sheet, row=number)
            result.office_address, result.office_row = address, number
            after_office = True
            continue
        if after_office:
            result.warnings.append(
                {"sheet": sheet, "row": number, "message": "Строка после адреса офиса пропущена"}
            )
            continue
        if len(result.rows) >= MAX_ROWS:
            raise SourceFormatError(f"Больше {MAX_ROWS} строк", sheet=sheet, row=number)
        if any(len(cell) > MAX_CELL_CHARS for cell in row):
            raise SourceFormatError("Слишком длинное значение ячейки", sheet=sheet, row=number)
        values = {
            name: row[position] if position < len(row) else "" for name, position in columns.items()
        }
        raw = {
            title: row[position] if position < len(row) else ""
            for position, title in enumerate(header)
            if title
        }
        result.rows.append(SourceRow(sheet, number, values, raw))


def read_source(content: bytes, filename: str) -> SourceFile:
    if not content or len(content) > MAX_FILE_BYTES:
        raise SourceFormatError("Пустой файл или размер больше 5 MiB")
    extension = filename.rsplit(".", 1)[-1].lower()
    result = SourceFile(
        filename=filename,
        sha256=hashlib.sha256(content).hexdigest(),
        encoding=None,
        delimiter=None,
        columns={},
        unknown_columns=[],
        rows=[],
    )
    if extension == "csv":
        text, result.encoding = _decode(content)
        first = next((line for line in text.splitlines() if line.strip()), "")
        result.delimiter = max((";", ",", "\t"), key=first.count)
        try:
            rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=result.delimiter))
        except csv.Error as error:
            raise SourceFormatError("Некорректный CSV: " + str(error)) from error
        _table(result, None, rows)
    elif extension == "xlsx":
        try:
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except (BadZipFile, KeyError, ValueError, OSError) as error:
            raise SourceFormatError("Повреждённый XLSX") from error
        try:
            for sheet in workbook.worksheets:
                if (sheet.max_row or 0) > MAX_ROWS + 50 or (sheet.max_column or 0) > 50:
                    raise SourceFormatError("Превышены размеры листа", sheet=sheet.title)
                _table(result, sheet.title, sheet.iter_rows(values_only=True))
        finally:
            workbook.close()
        if not result.columns:
            raise SourceFormatError("Ни на одном листе нет таблицы заявок")
    else:
        raise SourceFormatError("Поддерживаются .csv и .xlsx")
    return result


def parse_moment(text: str) -> datetime:
    """Local Moscow time from the file; «0:01» and «23:59» mark a whole-day window."""
    value = " ".join(text.split())
    for pattern in TIME_FORMATS:
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=MOSCOW)
        except ValueError:
            continue
    raise ValueError(f"Непонятное время «{text}»")


def work_date(moments: list[datetime]) -> date | None:
    return min(moment.date() for moment in moments) if moments else None


def dataset_from_filename(filename: str) -> str:
    """«Восток Синтетические данные.csv» and «Восток Контрольное распределение..csv» -> Восток."""
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    stem = re.split(r"\s+(?:синтетические данные|контрольное распределение)", stem, flags=re.I)[0]
    return " ".join(stem.strip(" ._-").split())


def midnight(day: date) -> datetime:
    return datetime.combine(day, time(), MOSCOW)

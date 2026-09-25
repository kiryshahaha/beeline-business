"""One rule for user text in CSV/XLSX files, shared by reports and the data exchange."""

import re

# Excel keeps at most 32 767 UTF-16 code units in a cell; openpyxl silently cuts longer text.
XLSX_MAX_CELL_UNITS = 32_767
# XML 1.0, and therefore XLSX, cannot store these characters at all.
XML_ILLEGAL_CHARACTERS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def starts_like_formula(value: str) -> bool:
    """Spreadsheets run text starting with = + - @, also after spaces, tabs or line breaks."""
    return value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@"))


def xlsx_length(value: str) -> int:
    """Characters outside the BMP, such as emoji, take two units of the XLSX cell limit."""
    return len(value.encode("utf-16-le")) // 2

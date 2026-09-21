"""CSV reading functions and data models.

The interactive Tkinter dialog lives in mapper.ui.csv_dialog.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

def __getattr__(name: str):
    if name == "ColumnMappingDialog":
        from mapper.ui.csv_dialog import ColumnMappingDialog
        return ColumnMappingDialog
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


@dataclass
class CSVData:
    headers: list[str]
    rows: list[list[str]]


def read_csv(path: Path) -> CSVData:
    raw = path.read_bytes()
    decoded = None
    for encoding in ("utf-8-sig", "utf-8", "cp1258", "cp1252"):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise ValueError("The CSV encoding could not be read. Export it as UTF-8 CSV and try again.")

    sample = decoded[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    rows = list(csv.reader(io.StringIO(decoded), dialect))
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise ValueError("The CSV needs a header and at least one product row.")
    return CSVData(headers=[header.strip() for header in rows[0]], rows=rows[1:])


__all__ = ["CSVData", "read_csv", "ColumnMappingDialog"]

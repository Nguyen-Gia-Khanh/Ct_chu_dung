"""CSV reading functions and data models.

The interactive Tkinter dialog lives in ui.desktop.csv_dialog.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CSVData:
    headers: list[str]
    rows: list[list[str]]


def read_csv(path: Path) -> CSVData:
    raw = path.read_bytes()
    decoded = None
    for encoding in ("utf-8-sig", "cp1258", "cp1252"):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise ValueError(
            "The CSV encoding could not be read. Export it as UTF-8 CSV and try again."
        )

    sample = decoded[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        # Short product rows can defeat sniffing even when the header is valid.
        # ponytail: fallback assumes a one-line header; add a delimiter option if needed.
        header = next((line for line in sample.splitlines() if line.strip()), "")
        try:
            dialect = csv.Sniffer().sniff(header, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel

    rows = [
        row for row in csv.reader(io.StringIO(decoded), dialect)
        if any(cell.strip() for cell in row)
    ]
    if len(rows) < 2:
        raise ValueError("The CSV needs a header and at least one product row.")
    return CSVData(headers=[header.strip() for header in rows[0]], rows=rows[1:])


__all__ = ["CSVData", "read_csv"]

"""CSV reading and the product-column selection dialog."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk


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


class ColumnMappingDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, headers: list[str]):
        super().__init__(parent)
        self.title("Choose CSV columns")
        self.resizable(False, False)
        self.result: tuple[int, int, int] | None = None
        self.transient(parent)
        self.grab_set()

        ttk.Label(
            self,
            text="Choose the three product columns to import. Other CSV columns will be ignored.",
        ).grid(row=0, column=0, columnspan=2, padx=16, pady=(16, 12), sticky="w")

        ttk.Label(self, text="Product ID column").grid(row=1, column=0, padx=16, pady=6, sticky="w")
        self.id_column = ttk.Combobox(self, values=headers, state="readonly", width=32)
        self.id_column.grid(row=1, column=1, padx=(0, 16), pady=6)

        ttk.Label(self, text="Product name column").grid(row=2, column=0, padx=16, pady=6, sticky="w")
        self.name_column = ttk.Combobox(self, values=headers, state="readonly", width=32)
        self.name_column.grid(row=2, column=1, padx=(0, 16), pady=6)

        ttk.Label(self, text="Shortened name column").grid(row=3, column=0, padx=16, pady=6, sticky="w")
        self.short_name_column = ttk.Combobox(self, values=headers, state="readonly", width=32)
        self.short_name_column.grid(row=3, column=1, padx=(0, 16), pady=6)

        normalized = [re.sub(r"[^a-z0-9]", "", header.casefold()) for header in headers]
        id_candidates = ("productid", "productcode", "sku", "itemid", "itemcode", "id", "code")
        name_candidates = ("productname", "itemname", "name", "description", "productdescription")
        short_name_candidates = (
            "shortenedname", "shortname", "labelname", "displayname", "abbreviatedname", "abbreviation"
        )

        id_index = next((normalized.index(candidate) for candidate in id_candidates if candidate in normalized), 0)
        name_index = next(
            (normalized.index(candidate) for candidate in name_candidates if candidate in normalized),
            1 if len(headers) > 1 else 0,
        )
        self.id_column.current(id_index)
        self.name_column.current(name_index)
        short_name_index = next(
            (normalized.index(candidate) for candidate in short_name_candidates if candidate in normalized),
            2 if len(headers) > 2 else name_index,
        )
        self.short_name_column.current(short_name_index)

        buttons = ttk.Frame(self)
        buttons.grid(row=4, column=0, columnspan=2, padx=16, pady=16, sticky="e")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Import", command=self.confirm).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_visibility()
        self.focus_set()

    def confirm(self) -> None:
        id_index = self.id_column.current()
        name_index = self.name_column.current()
        short_name_index = self.short_name_column.current()
        if id_index < 0 or name_index < 0 or short_name_index < 0:
            messagebox.showerror("Columns missing", "Choose all three columns.", parent=self)
            return
        if len({id_index, name_index, short_name_index}) != 3:
            messagebox.showerror("Columns duplicated", "Product ID, full name, and shortened name must use different columns.", parent=self)
            return
        self.result = (id_index, name_index, short_name_index)
        self.destroy()

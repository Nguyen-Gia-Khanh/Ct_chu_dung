"""Tkinter dialog for selecting product columns during CSV import."""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import messagebox, ttk


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

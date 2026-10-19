"""Tab 4: read-only shelf browser, also used to preview an uncommitted designer layout."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from mapper.core.common import clean_location_segment, vietnam_time
from mapper.persistence.database import Placement, WarehouseDatabase
from mapper.services.shelf_grid import GridCell, build_grid, load_grid
from .shelf_address_lookup import ShelfAddressLookup
from .widgets import ShelfGridCanvas, sync_tree_rows

Contents = list[tuple[str, str, Placement]]


def shelf_label(floor: str, side: str, shelf_code: str) -> str:
    return f"Floor {floor} — Side {side} — Shelf {shelf_code}"


class ShelfBrowserView(ttk.Frame):
    def __init__(self, parent: tk.Misc, database: WarehouseDatabase):
        super().__init__(parent, padding=10)
        self.database = database
        self.shelf_choices: dict[str, int] = {}
        self.current_shelf_id: int | None = None
        self.current_key: tuple[str, str, str] | None = None
        self.current_contents: Contents = []

        chooser = ttk.Frame(self)
        chooser.pack(fill="x", pady=(0, 8))
        ttk.Label(chooser, text="Existing shelf:").pack(side="left")
        self.shelf_selector = ttk.Combobox(chooser, state="readonly", width=42)
        self.shelf_selector.pack(side="left", padx=(6, 5))
        self.shelf_selector.bind("<<ComboboxSelected>>", lambda _event: self.load_selected())
        ttk.Button(chooser, text="Load shelf", command=self.load_selected).pack(side="left")
        ttk.Button(chooser, text="Refresh list", command=self.refresh).pack(side="left", padx=(6, 0))
        self.summary_text = tk.StringVar(value="Read-only view")
        ttk.Label(chooser, textvariable=self.summary_text, foreground="#555555").pack(side="right")

        self.shelf_address_lookup = ShelfAddressLookup(self, self.database.list_shelves, self.show_saved_shelf)
        self.shelf_address_lookup.pack(fill="x", pady=(0, 8))

        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True)
        shelf_panel = ttk.LabelFrame(pane, text="Saved shelf — click a cell to view", padding=8)
        details = ttk.LabelFrame(pane, text="Selected cell contents", padding=8)
        pane.add(shelf_panel, weight=3)
        pane.add(details, weight=2)

        self.shelf_grid = ShelfGridCanvas(
            shelf_panel, on_select=lambda cell: self.select_slot(cell.slot_name),
            label=self._cell_label, cell_width=88, cell_height=64, min_row_width=400,
            row_label=lambda row: f"Row {row}" + (" — ground" if row == 1 else ""))
        self.shelf_grid.pack(fill="both", expand=True)

        self.selected_slot_text = tk.StringVar(value="No cell selected")
        ttk.Label(details, textvariable=self.selected_slot_text, style="Heading.TLabel").pack(anchor="w", pady=(0, 6))
        body = ttk.Frame(details)
        body.pack(fill="both", expand=True)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self.contents_tree = ttk.Treeview(
            body, columns=("product_id", "product_name", "stock_qty", "assigned_at", "state"),
            show="headings", selectmode="extended", height=18)
        for column, heading, width, anchor in (
            ("product_id", "Product ID", 95, "w"), ("product_name", "Product name", 160, "w"),
            ("stock_qty", "Stock qty", 80, "e"), ("assigned_at", "Added to shelf ↑", 200, "w"),
            ("state", "State", 70, "w"),
        ):
            self.contents_tree.heading(column, text=heading)
            self.contents_tree.column(column, width=width, minwidth=50, anchor=anchor,
                                      stretch=column == "product_name")
        y_scroll = ttk.Scrollbar(body, orient="vertical", command=self.contents_tree.yview)
        x_scroll = ttk.Scrollbar(body, orient="horizontal", command=self.contents_tree.xview)
        self.contents_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.contents_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.contents_tree.bind("<Double-1>", self.copy_product_id)
        self.copy_status_text = tk.StringVar(value="Double-click a product row to copy its Product ID.")
        ttk.Label(details, textvariable=self.copy_status_text, foreground="#555555").pack(anchor="w", pady=(6, 0))
        self.clear_shelf()

    def _cell_label(self, cell: GridCell) -> str:
        code = clean_location_segment(self.current_key[2]) if self.current_key else ""
        return f"{code}{cell.row}-{cell.cell}"

    @property
    def selected_slot(self) -> str | None:
        return self.shelf_grid.selected

    def clear_shelf(self) -> None:
        self.current_shelf_id = None
        self.current_key = None
        self.current_contents = []
        self.shelf_selector.set("")
        self.shelf_address_lookup.set_address("", "", "")
        self.summary_text.set("Committed SQLite data")
        self.shelf_grid.show_message("Choose a shelf above.")
        self._show_contents(None)

    def refresh(self, *, select_shelf_id: int | None = None) -> None:
        self.shelf_choices = {shelf_label(floor, side, code): shelf_id
                              for shelf_id, floor, side, code in self.database.list_shelves()}
        self.shelf_selector.configure(values=list(self.shelf_choices))
        target = select_shelf_id if select_shelf_id is not None else self.current_shelf_id
        if target is not None:
            label = next((label for label, shelf_id in self.shelf_choices.items() if shelf_id == target), "")
            self.shelf_selector.set(label)
            if not label:
                self.current_shelf_id = None
        elif self.shelf_selector.get() not in self.shelf_choices:
            self.shelf_selector.set("")

    def load_selected(self) -> None:
        shelf_id = self.shelf_choices.get(self.shelf_selector.get())
        if shelf_id is None:
            messagebox.showinfo("Choose a shelf", "Select an existing shelf first.", parent=self)
            return
        self.show_saved_shelf(shelf_id)

    def show_saved_shelf(self, shelf_id: int) -> None:
        try:
            grid, contents = load_grid(self.database, shelf_id)
        except Exception as error:
            messagebox.showerror("Shelf could not be loaded", str(error), parent=self)
            return
        self.current_shelf_id = shelf_id
        self._show(grid, contents, summary="Committed SQLite data")
        label = shelf_label(*grid.key)
        if label not in self.shelf_choices:
            self.refresh(select_shelf_id=shelf_id)
        else:
            self.shelf_selector.set(label)

    def show_preview(self, floor: str, side: str, shelf_code: str, layout: list[int],
                     contents: Contents | None = None) -> None:
        """Show an editor preview without pretending it is already committed."""
        contents = list(contents or [])
        self.current_shelf_id = None
        self.shelf_selector.set("")
        self._show(build_grid(floor, side, shelf_code, layout, (p.slot_name for _, _, p in contents)),
                   contents, summary="Uncommitted shelf preview")

    def _show(self, grid, contents: Contents, *, summary: str) -> None:
        self.current_key = grid.key
        self.current_contents = contents
        self.shelf_address_lookup.set_address(*grid.key)
        layout = grid.layout
        self.summary_text.set(f"{summary} · {len(layout)} rows · {sum(layout)} cells")
        self.shelf_grid.show(grid, selected=self.shelf_grid.selected)
        self._show_contents(self.shelf_grid.selected)

    def refresh_cell(self, slot_name: str, contents: Contents) -> None:
        if self.current_shelf_id is None or slot_name not in self.shelf_grid:
            return
        self.current_contents = [item for item in self.current_contents if item[2].slot_name != slot_name] + list(contents)
        self.shelf_grid.set_count(slot_name, len(contents))
        if self.selected_slot == slot_name:
            self._show_contents(slot_name)

    def refresh_loaded_contents(self) -> None:
        if self.current_shelf_id is not None:
            self.show_saved_shelf(self.current_shelf_id)

    def select_slot(self, slot_name: str) -> None:
        self.shelf_grid.select(slot_name, reveal=False)
        self._show_contents(slot_name)

    def _show_contents(self, slot_name: str | None) -> None:
        self.selected_slot_text.set(slot_name or "No cell selected")
        state = "Saved" if self.current_shelf_id is not None else "Preview"
        sync_tree_rows(self.contents_tree, [
            (f"saved::{pid}", (pid, name, p.stock_qty if p.stock_qty is not None else "Unknown",
                               vietnam_time(p.assigned_at) if p.assigned_at else "Unknown", state), ())
            for pid, name, p in self.current_contents if slot_name and p.slot_name == slot_name
        ])

    def copy_product_id(self, event) -> str | None:
        row_id = self.contents_tree.identify_row(event.y)
        values = self.contents_tree.item(row_id, "values") if row_id else ()
        product_id = str(values[0]).strip() if values else ""
        if not product_id:
            return None
        self.contents_tree.selection_set(row_id)
        self.contents_tree.focus(row_id)
        self.clipboard_clear()
        self.clipboard_append(product_id)
        self.copy_status_text.set(f"Copied {product_id}")
        return "break"

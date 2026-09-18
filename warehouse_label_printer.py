"""Separate Tkinter app for printing labels from the warehouse mapper database.

Put this file beside warehouse_mapper.py and keep warehouse_label_pdf.py inside
the print_layout folder, then run:
    python warehouse_label_printer.py

Only PDF generation needs an extra package: python -m pip install reportlab
The SQLite connection is read-only. No schema updates or backups are performed.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
from queue import Empty, Queue
import sqlite3
import subprocess
import sys
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from print_layout.warehouse_label_pdf import (
    Cell,
    Product,
    label_count,
    render_labels_pdf,
)


@dataclass(frozen=True)
class Shelf:
    shelf_id: int
    floor: str
    side: str
    code: str
    rows: tuple[tuple[int, int], ...]
    cells: tuple[Cell, ...]


class LabelDatabase:
    """Read the existing schema and the stored slot names, without changing either."""

    def __init__(self, path: Path):
        self.path = Path(path).expanduser().resolve()

    def connect(self):
        if not self.path.is_file():
            raise FileNotFoundError(
                f"Choose your existing warehouse database:\n{self.path}"
            )
        connection = sqlite3.connect(
            self.path.as_uri() + "?mode=ro", uri=True, timeout=5
        )
        connection.row_factory = sqlite3.Row
        return connection

    def list_shelves(self):
        with closing(self.connect()) as connection:
            return connection.execute("""
                SELECT s.shelf_id, s.floor, s.side, s.shelf_code,
                       COUNT(DISTINCT sl.slot_id) AS cell_count
                FROM shelves s
                LEFT JOIN shelf_rows r ON r.shelf_id = s.shelf_id
                LEFT JOIN slots sl ON sl.row_id = r.row_id
                GROUP BY s.shelf_id
                ORDER BY s.floor COLLATE NOCASE, s.side COLLATE NOCASE, s.shelf_code COLLATE NOCASE
            """).fetchall()

    def read_shelves(self, shelf_ids) -> tuple[Shelf, ...]:
        # All requested shelves/placements come from one consistent read snapshot.
        result = []
        with closing(self.connect()) as connection:
            connection.execute("BEGIN")
            for shelf_id in dict.fromkeys(shelf_ids):
                info = connection.execute(
                    "SELECT shelf_id, floor, side, shelf_code FROM shelves WHERE shelf_id = ?",
                    (shelf_id,),
                ).fetchone()
                if info is None:
                    raise ValueError(
                        "A selected shelf was removed. Refresh the database list."
                    )
                rows = connection.execute(
                    "SELECT row_number, slot_count FROM shelf_rows WHERE shelf_id = ? ORDER BY row_number",
                    (shelf_id,),
                ).fetchall()
                product_columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(products)")
                }
                label_name = (
                    "COALESCE(NULLIF(TRIM(p.shortened_name), ''), p.product_name)"
                    if "shortened_name" in product_columns
                    else "p.product_name"
                )
                records = connection.execute(
                    f"""
                    SELECT sl.slot_id, sl.slot_name, r.row_number, sl.slot_number,
                           p.product_id, {label_name} AS label_name
                    FROM shelf_rows r JOIN slots sl ON sl.row_id = r.row_id
                    LEFT JOIN placements pl ON pl.slot_id = sl.slot_id
                    LEFT JOIN products p ON p.product_id = pl.product_id
                    WHERE r.shelf_id = ?
                    ORDER BY r.row_number, sl.slot_number, p.product_id COLLATE NOCASE
                """,
                    (shelf_id,),
                ).fetchall()
                metadata, products = {}, defaultdict(list)
                for record in records:
                    slot_id = record["slot_id"]
                    metadata[slot_id] = record
                    if record["product_id"] is not None:
                        products[slot_id].append(
                            Product(record["product_id"], record["label_name"])
                        )
                cells = tuple(
                    Cell(
                        shelf_id,
                        slot_id,
                        record["row_number"],
                        record["slot_number"],
                        record["slot_name"],
                        tuple(products[slot_id]),
                    )
                    for slot_id, record in metadata.items()
                )
                result.append(
                    Shelf(
                        shelf_id,
                        info["floor"],
                        info["side"],
                        info["shelf_code"],
                        tuple((row["row_number"], row["slot_count"]) for row in rows),
                        cells,
                    )
                )
        return tuple(result)


def cells_for_printing(
    shelves: tuple[Shelf, ...], selected_slot_ids=None
) -> tuple[Cell, ...]:
    """Keep numeric ground-up row/cell order; never sort by the location string."""
    cells = tuple(cell for shelf in shelves for cell in shelf.cells)
    if selected_slot_ids is not None:
        wanted = set(selected_slot_ids)
        existing = {cell.slot_id for cell in cells}
        if wanted - existing:
            raise ValueError(
                "Some selected cells were removed. Refresh the database and select them again."
            )
        cells = tuple(cell for cell in cells if cell.slot_id in wanted)
    if not cells:
        raise ValueError(
            "Select at least one cell to print."
            if selected_slot_ids is not None
            else "These shelves have no cells."
        )
    return cells


class LabelPrinterApp:
    def __init__(self, root: tk.Tk, database_path: Path):
        self.root = root
        self.root.title("Warehouse Label Printer")
        self.root.state("zoomed")
        self.root.minsize(1080, 650)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.database = LabelDatabase(database_path)
        self.shelf_rows = []
        self.cache: dict[int, Shelf] = {}
        self.marked: set[int] = set()
        self.cell_shelves: dict[int, int] = {}
        self.active_shelf: Shelf | None = None
        self.active_cell: Cell | None = None
        self.rectangles = {}
        self.busy = False
        self.poll_id = None
        self.events = Queue()
        self.last_pdf = None
        self.db_text = tk.StringVar(value=str(self.database.path))
        self.search_text = tk.StringVar()
        self.label_height = tk.IntVar(value=7)
        self.summary_text = tk.StringVar(value="Select a shelf to begin.")
        self.location_text = tk.StringVar(value="Click a cell")
        self.status_text = tk.StringVar(
            value="Uses committed data. Commit changes in the mapper, then press Refresh here."
        )
        self._build_ui()
        if self.database.path.is_file():
            self.refresh_database()
        else:
            self.status_text.set(
                "Choose your existing warehouse_locations.db with Browse database."
            )

    def _build_ui(self):
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        header = ttk.Frame(self.root, padding=(12, 10))
        header.pack(fill="x")
        ttk.Label(
            header, text="Warehouse Label Printer", font=("Segoe UI", 17, "bold")
        ).pack(side="left")
        ttk.Label(header, text="Landscape A4 labels from saved shelf contents").pack(
            side="left", padx=20
        )
        database_bar = ttk.Frame(self.root, padding=(12, 0, 12, 10))
        database_bar.pack(fill="x")
        ttk.Label(database_bar, text="Database:").pack(side="left")
        ttk.Entry(database_bar, textvariable=self.db_text, state="readonly").pack(
            side="left", fill="x", expand=True, padx=8
        )
        ttk.Button(
            database_bar, text="Browse database", command=self.browse_database
        ).pack(side="left")
        ttk.Button(database_bar, text="Refresh", command=self.refresh_database).pack(
            side="left", padx=(6, 0)
        )

        panes = ttk.Panedwindow(self.root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=12)
        shelf_panel = ttk.LabelFrame(panes, text="Shelves", padding=8, width=270)
        drawing_panel = ttk.LabelFrame(
            panes, text="Shelf view - click cells to select / deselect", padding=8
        )
        details_panel = ttk.LabelFrame(
            panes, text="Cell contents", padding=10, width=300
        )
        panes.add(shelf_panel, weight=2)
        panes.add(drawing_panel, weight=6)
        panes.add(details_panel, weight=3)

        ttk.Label(shelf_panel, text="Filter floor, side or shelf code").pack(anchor="w")
        search = ttk.Entry(shelf_panel, textvariable=self.search_text)
        search.pack(fill="x", pady=(4, 8))
        self.search_text.trace_add("write", self.filter_shelves)
        tree_frame = ttk.Frame(shelf_panel)
        tree_frame.pack(fill="both", expand=True)
        self.shelf_tree = ttk.Treeview(
            tree_frame,
            columns=("floor", "side", "code", "cells"),
            show="headings",
            selectmode="extended",
        )
        for name, heading, width in [
            ("floor", "Floor", 55),
            ("side", "Side", 50),
            ("code", "Shelf", 65),
            ("cells", "Cells", 50),
        ]:
            self.shelf_tree.heading(name, text=heading)
            self.shelf_tree.column(
                name, width=width, minwidth=40, anchor="center", stretch=True
            )
        scrollbar = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.shelf_tree.yview
        )
        self.shelf_tree.configure(yscrollcommand=scrollbar.set)
        self.shelf_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.shelf_tree.bind("<<TreeviewSelect>>", self.on_shelf_selection)
        ttk.Label(
            shelf_panel, text="Ctrl / Shift selects multiple shelves.", wraplength=230
        ).pack(anchor="w", pady=(8, 0))

        controls = ttk.Frame(drawing_panel)
        controls.pack(fill="x", pady=(0, 7))
        for title, mode in [
            ("Select all cells", "all"),
            ("Select occupied", "occupied"),
            ("Clear cells", "clear"),
        ]:
            ttk.Button(
                controls,
                text=title,
                command=lambda action=mode: self.mark_active_shelf(action),
            ).pack(side="left", padx=(0, 5))
        drawing = ttk.Frame(drawing_panel)
        drawing.pack(fill="both", expand=True)
        drawing.rowconfigure(0, weight=1)
        drawing.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(drawing, background="white", highlightthickness=0)
        vertical = ttk.Scrollbar(drawing, orient="vertical", command=self.canvas.yview)
        horizontal = ttk.Scrollbar(
            drawing, orient="horizontal", command=self.canvas.xview
        )
        self.canvas.configure(
            yscrollcommand=vertical.set, xscrollcommand=horizontal.set
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.canvas.bind("<Configure>", lambda _event: self.draw_shelf())
        self.canvas.bind(
            "<MouseWheel>",
            lambda event: self.canvas.yview_scroll(-int(event.delta / 120), "units"),
        )
        self.canvas.bind(
            "<Shift-MouseWheel>",
            lambda event: self.canvas.xview_scroll(-int(event.delta / 120), "units"),
        )
        ttk.Label(
            drawing_panel,
            text="Blue = selected for printing    Green = occupied    Gray = empty",
        ).pack(anchor="w", pady=(7, 0))

        ttk.Label(
            details_panel,
            textvariable=self.location_text,
            font=("Segoe UI", 18, "bold"),
            wraplength=285,
        ).pack(anchor="w", pady=(0, 10))
        self.details = tk.Text(
            details_panel,
            width=30,
            wrap="word",
            font=("Segoe UI", 10),
            relief="flat",
            state="disabled",
        )
        self.details.pack(fill="both", expand=True)
        self.details.tag_configure("id", font=("Segoe UI", 10, "bold"), spacing1=12)
        self.details.tag_configure("name", spacing1=3, spacing3=8)
        self.details.tag_configure("note", foreground="#666666")

        footer = ttk.Frame(self.root, padding=12)
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.summary_text).pack(anchor="w", pady=(0, 8))
        buttons = ttk.Frame(footer)
        buttons.pack(fill="x")
        ttk.Label(buttons, text="Label height:").pack(side="left")
        ttk.Radiobutton(
            buttons,
            text="7 cm (3 per landscape A4)",
            variable=self.label_height,
            value=7,
        ).pack(side="left", padx=(6, 8))
        ttk.Radiobutton(
            buttons,
            text="15 cm (1 per landscape A4)",
            variable=self.label_height,
            value=15,
        ).pack(side="left", padx=(0, 15))
        self.print_all_button = ttk.Button(
            buttons,
            text="Print all cells (PDF)...",
            command=lambda: self.start_print(False),
        )
        self.print_all_button.pack(side="left", padx=(0, 8))
        self.print_selected_button = ttk.Button(
            buttons,
            text="Print selected cells (PDF)...",
            command=lambda: self.start_print(True),
        )
        self.print_selected_button.pack(side="left")
        ttk.Button(buttons, text="Open last PDF", command=self.open_last_pdf).pack(
            side="right"
        )
        ttk.Label(
            footer,
            text="Print buttons open a landscape A4 PDF. Press Ctrl+P in the PDF viewer; use Actual size / 100%. Empty cells get location-only labels.",
        ).pack(anchor="w", pady=(8, 0))
        ttk.Label(
            self.root,
            textvariable=self.status_text,
            relief="sunken",
            anchor="w",
            padding=(8, 4),
        ).pack(fill="x")
        self.update_summary()

    def selected_shelf_ids(self):
        selected = set(self.shelf_tree.selection())
        # The list's order is stable even when shelves were selected in another order.
        return [
            int(item.split("::", 1)[1])
            for item in self.shelf_tree.get_children()
            if item in selected
        ]

    def browse_database(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Choose the warehouse mapper database",
            filetypes=[
                ("SQLite database", "*.db *.sqlite *.sqlite3"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.refresh_database(Path(path))

    def refresh_database(self, path=None):
        candidate = LabelDatabase(path or self.database.path)
        try:
            rows = candidate.list_shelves()
        except (OSError, sqlite3.Error) as error:
            messagebox.showerror("Cannot read database", str(error), parent=self.root)
            return
        self.database = candidate
        self.db_text.set(str(candidate.path))
        self.shelf_rows = rows
        self.cache.clear()
        self.marked.clear()
        self.cell_shelves.clear()
        self.active_shelf = self.active_cell = None
        self.filter_shelves()
        self.show_cell(None)
        self.draw_shelf()
        self.status_text.set(
            f"Loaded {len(rows)} shelves. Cell selections cleared. Only committed placements are shown."
        )

    def filter_shelves(self, *_args):
        previous = set(self.shelf_tree.selection())
        self.shelf_tree.delete(*self.shelf_tree.get_children())
        query = self.search_text.get().strip().casefold()
        for row in self.shelf_rows:
            if query in f"{row['floor']} {row['side']} {row['shelf_code']}".casefold():
                self.shelf_tree.insert(
                    "",
                    "end",
                    iid=f"shelf::{row['shelf_id']}",
                    values=(
                        row["floor"],
                        row["side"],
                        row["shelf_code"],
                        row["cell_count"],
                    ),
                )
        available = self.shelf_tree.get_children()
        retained = [item for item in available if item in previous]
        if not retained and available:
            retained = [available[0]]
        if retained:
            self.shelf_tree.selection_set(retained)
            self.shelf_tree.focus(retained[0])
        self.on_shelf_selection()

    def on_shelf_selection(self, _event=None):
        selected = self.selected_shelf_ids()
        self.marked = {
            slot for slot in self.marked if self.cell_shelves.get(slot) in selected
        }
        if not selected:
            self.active_shelf = None
            self.show_cell(None)
        else:
            focus = self.shelf_tree.focus()
            shelf_id = (
                int(focus.split("::", 1)[1])
                if focus in self.shelf_tree.selection()
                else selected[0]
            )
            try:
                if shelf_id not in self.cache:
                    self.cache[shelf_id] = self.database.read_shelves([shelf_id])[0]
                self.active_shelf = self.cache[shelf_id]
                for cell in self.active_shelf.cells:
                    self.cell_shelves[cell.slot_id] = shelf_id
                if self.active_cell is None or self.active_cell.shelf_id != shelf_id:
                    self.show_cell(None)
            except (OSError, sqlite3.Error, ValueError) as error:
                self.active_shelf = None
                self.show_cell(None)
                messagebox.showerror("Cannot load shelf", str(error), parent=self.root)
        self.draw_shelf()
        self.update_summary()

    def draw_shelf(self):
        self.canvas.delete("all")
        self.rectangles.clear()
        shelf = self.active_shelf
        if shelf is None:
            self.canvas.create_text(
                25,
                30,
                anchor="nw",
                text="Select a saved shelf from the list.",
                font=("Segoe UI", 12),
            )
            return
        self.canvas.create_text(
            18,
            18,
            anchor="nw",
            text=f"Floor {shelf.floor} / Side {shelf.side} / Shelf {shelf.code}",
            font=("Segoe UI", 14, "bold"),
        )
        max_columns = max((count for _, count in shelf.rows), default=1)
        row_w = max(600, self.canvas.winfo_width() - 115, max_columns * 100)
        by_row = defaultdict(list)
        for cell in shelf.cells:
            by_row[cell.row_number].append(cell)
        for screen_row, (number, count) in enumerate(reversed(shelf.rows)):
            y = 60 + screen_row * 82
            self.canvas.create_text(
                10,
                y + 35,
                anchor="w",
                text=f"Row {number}" + ("\nGround" if number == 1 else ""),
                font=("Segoe UI", 10, "bold"),
            )
            self.canvas.create_rectangle(
                90, y, 90 + row_w, y + 74, fill="#eeeeee", outline="#bbbbbb"
            )
            if not count:
                self.canvas.create_text(100, y + 35, anchor="w", text="No cells")
                continue
            for cell in by_row[number]:
                width = row_w / count
                x = 90 + (cell.slot_number - 1) * width
                tag = f"cell_{cell.slot_id}"
                marked = cell.slot_id in self.marked
                fill = (
                    "#cce4ff" if marked else "#e4efdf" if cell.products else "#f6f6f6"
                )
                active = (
                    self.active_cell is not None
                    and self.active_cell.slot_id == cell.slot_id
                )
                rectangle = self.canvas.create_rectangle(
                    x + 2,
                    y + 2,
                    x + width - 2,
                    y + 72,
                    fill=fill,
                    outline="#2864a0" if active else "#a0a0a0",
                    width=3 if active else 1,
                    tags=tag,
                )
                self.rectangles[cell.slot_id] = rectangle
                self.canvas.create_text(
                    x + width / 2,
                    y + 25,
                    text=cell.location_id,
                    width=width - 10,
                    font=("Segoe UI", 9, "bold"),
                    tags=tag,
                )
                self.canvas.create_text(
                    x + width / 2,
                    y + 54,
                    text=f"{'[x] ' if marked else ''}{len(cell.products)} product(s)",
                    font=("Segoe UI", 9),
                    tags=tag,
                )
                self.canvas.tag_bind(
                    tag,
                    "<Button-1>",
                    lambda _event, chosen=cell: self.toggle_cell(chosen),
                )
        self.canvas.configure(
            scrollregion=(0, 0, row_w + 105, 75 + len(shelf.rows) * 82)
        )

    def toggle_cell(self, cell):
        if cell.slot_id in self.marked:
            self.marked.remove(cell.slot_id)
        else:
            self.marked.add(cell.slot_id)
        self.show_cell(cell)
        self.draw_shelf()
        self.update_summary()

    def mark_active_shelf(self, action):
        if self.active_shelf is None:
            return
        ids = {cell.slot_id for cell in self.active_shelf.cells}
        self.marked.difference_update(ids)
        if action != "clear":
            self.marked.update(
                cell.slot_id
                for cell in self.active_shelf.cells
                if action == "all" or cell.products
            )
        self.draw_shelf()
        self.update_summary()

    def show_cell(self, cell):
        self.active_cell = cell
        self.location_text.set(cell.location_id if cell else "Click a cell")
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        if cell is not None:
            self.details.insert(
                "end", f"Row {cell.row_number} / Cell {cell.slot_number}\n", "note"
            )
            for product in cell.products:
                self.details.insert("end", product.product_id + "\n", "id")
                self.details.insert("end", product.name + "\n", "name")
            if not cell.products:
                self.details.insert(
                    "end",
                    "\nNo products assigned. The location ID will still print.",
                    "note",
                )
        self.details.configure(state="disabled")

    def update_summary(self):
        selected = self.selected_shelf_ids()
        self.summary_text.set(
            f"{len(selected)} shelf(s) selected / {len(self.marked)} cells marked. Print order: ground row upward, left to right."
        )
        self.print_all_button.configure(
            state="normal" if selected and not self.busy else "disabled"
        )
        self.print_selected_button.configure(
            state="normal" if self.marked and selected and not self.busy else "disabled"
        )

    def start_print(self, selected_only):
        if self.busy:
            return
        try:
            shelves = self.database.read_shelves(self.selected_shelf_ids())
            cells = cells_for_printing(shelves, self.marked if selected_only else None)
            height_cm = int(self.label_height.get())
        except (OSError, sqlite3.Error, ValueError) as error:
            messagebox.showerror("Cannot print labels", str(error), parent=self.root)
            return
        output = (
            Path(__file__).resolve().parent
            / "label_printouts"
            / f"warehouse_labels_{height_cm}cm_{datetime.now():%Y%m%d_%H%M%S_%f}.pdf"
        )
        self.busy = True
        self.update_summary()
        self.status_text.set(
            f"Preparing {label_count(cells)} labels at {height_cm} cm from the latest committed placements..."
        )
        Thread(
            target=self._generate_pdf, args=(cells, output, height_cm), daemon=True
        ).start()
        self.poll_id = self.root.after(100, self._poll)

    def _generate_pdf(self, cells, output, height_cm):
        try:
            result = render_labels_pdf(
                cells,
                output,
                label_height_cm=height_cm,
                progress=lambda text: self.events.put(("progress", text)),
            )
            self.events.put(("done", result))
        except Exception as error:
            self.events.put(("error", str(error)))

    def _poll(self):
        self.poll_id = None
        while True:
            try:
                event, value = self.events.get_nowait()
            except Empty:
                break
            if event == "progress":
                self.status_text.set(value)
                continue
            self.busy = False
            self.update_summary()
            if event == "error":
                self.status_text.set("PDF was not created. See the error message.")
                messagebox.showerror("Label printing", value, parent=self.root)
            else:
                self.last_pdf = value.path
                self.status_text.set(
                    f"{value.labels} labels / {value.pages} A4 page(s). Press Ctrl+P in the opened PDF. Saved: {value.path.name}"
                )
                self.open_last_pdf()
            return
        if self.busy:
            self.poll_id = self.root.after(100, self._poll)

    def open_last_pdf(self):
        if self.last_pdf is None:
            messagebox.showinfo(
                "No PDF yet",
                "Choose Print all cells or Print selected cells first.",
                parent=self.root,
            )
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(self.last_pdf))
            else:
                subprocess.Popen(
                    [
                        "open" if sys.platform == "darwin" else "xdg-open",
                        str(self.last_pdf),
                    ]
                )
        except OSError as error:
            messagebox.showinfo(
                "PDF saved",
                f"Open this file manually to print:\n{self.last_pdf}\n\n{error}",
                parent=self.root,
            )

    def close(self):
        if self.busy:
            messagebox.showinfo(
                "Preparing PDF",
                "Wait for the PDF to finish before closing.",
                parent=self.root,
            )
            return
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(
        description="Print A4 labels from a warehouse mapper SQLite database."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(__file__).resolve().parent / "warehouse_locations.db",
    )
    args = parser.parse_args()
    root = tk.Tk()
    LabelPrinterApp(root, args.db)
    root.mainloop()


if __name__ == "__main__":
    main()

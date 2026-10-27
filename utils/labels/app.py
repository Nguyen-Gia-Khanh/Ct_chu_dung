r"""Separate Tkinter app for printing labels from the warehouse mapper database.

Run with ``.venv\Scripts\python.exe warehouse_label_printer.py`` from the project root.

PDF generation needs ReportLab; reading previous PDFs needs pypdf:
    .venv\Scripts\python.exe -m pip install -r requirements.txt
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
import re
from queue import Empty, Queue
import sqlite3
import subprocess
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utils.runtime import ensure_repo_venv

if __name__ == "__main__":
    ensure_repo_venv()

from threading import Thread
import unicodedata
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from mapper.core.common import data_directory, default_database_path, shelf_cell_number
from utils.labels.pdf import (
    LABEL_HEIGHTS_CM,
    SIGNS_PER_PAGE,
    Cell,
    Product,
    clean_sign_name,
    label_count,
    render_labels_pdf,
    render_shelf_signs_pdf,
    sign_page_count,
)


@dataclass(frozen=True)
class Shelf:
    shelf_id: int
    floor: str
    side: str
    code: str
    rows: tuple[tuple[int, int], ...]
    cells: tuple[Cell, ...]
    revert_location_id: bool = False


@dataclass(frozen=True)
class PrintedPdfHit:
    path: Path
    created_at: datetime


DRAG_THRESHOLD_PX = 5
SELECTED_FILL = "#cce4ff"


@dataclass
class CellDrag:
    """A press on the shelf view; it becomes a selection box once the mouse moves."""
    press_x: int
    press_y: int
    start_x: float  # canvas coordinates, so scrolling keeps the anchor in place
    start_y: float
    cell: Cell | None
    select: bool  # starting on a selected cell makes the box deselect
    pointer: tuple[int, int]
    started: bool = False
    band: int | None = None


_PRINT_FILE_TIME = re.compile(
    r"warehouse_labels_(?:location_only_|product_only_|location_|product_)?[\d.]+cm_(?:portrait_|landscape_)?(\d{8})_(\d{6})_(\d{6})\.pdf$",
    re.IGNORECASE,
)


def _location_key(value: str) -> str:
    """Match printed location text even when the PDF split it across two lines."""
    normalized = unicodedata.normalize("NFC", str(value))
    return "".join(normalized.split()).casefold()


def _pdf_created_at(path: Path, reader=None) -> datetime:
    """Best available PDF-generation time; this is not a physical-printer timestamp."""
    if reader is not None:
        try:
            created = reader.metadata.creation_date if reader.metadata else None
            if created is not None:
                return created.astimezone().replace(tzinfo=None) if created.tzinfo else created
        except (AttributeError, ValueError):
            pass
    match = _PRINT_FILE_TIME.search(path.name)
    if match:
        try:
            return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S%f")
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def scan_printed_pdfs(
    pdf_paths: tuple[Path, ...] | list[Path],
    known_locations: tuple[str, ...] | list[str],
) -> dict[str, tuple[PrintedPdfHit, ...]]:
    """Find current warehouse location IDs inside PDFs made by this label app."""
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise RuntimeError(
            "Reading previous label PDFs needs pypdf. Install it in this app's venv:\n\n"
            ".venv\\Scripts\\python.exe -m pip install pypdf"
        ) from error

    known = {_location_key(location): location for location in known_locations}
    known_keys = set(known)
    hits = defaultdict(list)

    for raw_path in pdf_paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Previous label PDF not found:\n{path}")
        try:
            reader = PdfReader(str(path))
            found_here = set()
            for page in reader.pages:
                text = page.extract_text() or ""
                lines = [_location_key(line) for line in text.splitlines() if line.strip()]
                candidates = set(lines)
                candidates.update(lines[index] + lines[index + 1] for index in range(len(lines) - 1))
                found_here.update(known_keys.intersection(candidates))
            created_at = _pdf_created_at(path, reader)
        except Exception as error:
            raise ValueError(f"Could not read previous label PDF:\n{path.name}\n\n{error}") from error

        for key in found_here:
            hits[key].append(PrintedPdfHit(path, created_at))

    return {
        key: tuple(sorted(values, key=lambda hit: hit.created_at))
        for key, values in hits.items()
    }


class LabelDatabase:
    """Read the existing schema and the stored slot names, without changing either."""

    def __init__(self, path: Path):
        self.path = Path(path).expanduser().resolve()

    def connect(self):
        if not self.path.is_file():
            raise FileNotFoundError(f"Choose your existing warehouse database:\n{self.path}")
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.row_factory = sqlite3.Row
        return connection

    def list_shelves(self):
        with closing(self.connect()) as connection:
            return connection.execute("""
                SELECT s.shelf_id, s.floor, s.side, s.shelf_code,
                       COUNT(DISTINCT sl.slot_id) AS cell_count
                FROM shelves s
                LEFT JOIN slots sl ON sl.shelf_id = s.shelf_id
                GROUP BY s.shelf_id
                ORDER BY s.floor COLLATE NOCASE, s.side COLLATE NOCASE, s.shelf_code COLLATE NOCASE
            """).fetchall()

    def list_location_ids(self) -> tuple[str, ...]:
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT slot_name FROM slots ORDER BY slot_id"
            ).fetchall()
        return tuple(row["slot_name"] for row in rows)

    def read_shelves(self, shelf_ids) -> tuple[Shelf, ...]:
        # All requested shelves/placements come from one consistent read snapshot.
        result = []
        with closing(self.connect()) as connection:
            connection.execute("BEGIN")
            for shelf_id in dict.fromkeys(shelf_ids):
                info = connection.execute(
                    "SELECT shelf_id, floor, side, shelf_code, row_count, revert_location_id FROM shelves WHERE shelf_id = ?", (shelf_id,),
                ).fetchone()
                if info is None:
                    raise ValueError("A selected shelf was removed. Refresh the database list.")
                rows = connection.execute(
                    "SELECT row_number, COUNT(*) AS slot_count FROM slots WHERE shelf_id = ? GROUP BY row_number", (shelf_id,),
                ).fetchall()
                counts = {row['row_number']:row['slot_count'] for row in rows}
                label_name = "COALESCE(p.full_name,p.brand_name,p.product_id)"
                records = connection.execute(f"""
                    SELECT sl.slot_id, sl.slot_name, sl.row_number, sl.slot_number,
                           p.product_id, {label_name} AS label_name
                    FROM slots sl
                    LEFT JOIN (SELECT product_id,slot_id FROM placements UNION SELECT product_id,slot_id FROM exception_placements) pl ON pl.slot_id = sl.slot_id
                    LEFT JOIN catalog_products p ON p.product_id = pl.product_id
                    WHERE sl.shelf_id = ?
                    ORDER BY sl.row_number, sl.slot_number, p.product_id COLLATE NOCASE
                """, (shelf_id,)).fetchall()
                metadata, products = {}, defaultdict(list)
                for record in records:
                    slot_id = record["slot_id"]
                    metadata[slot_id] = record
                    if record["product_id"] is not None:
                        products[slot_id].append(Product(record["product_id"], record["label_name"]))
                cells = tuple(Cell(
                    shelf_id, slot_id, record["row_number"], record["slot_number"],
                    record["slot_name"], tuple(products[slot_id]),
                ) for slot_id, record in metadata.items())
                result.append(Shelf(
                    shelf_id, info["floor"], info["side"], info["shelf_code"],
                    tuple((number,counts.get(number,0)) for number in range(1,info['row_count']+1)), cells,
                    bool(info['revert_location_id']),
                ))
        return tuple(result)


MAX_SIGN_RANGE = 500


def _range_values(start: str, end: str, part: str) -> list[str]:
    """Whole numbers (3 to 5, keeping 01-style padding) or single letters (A to G).

    A blank end repeats the start, and a reversed range counts down.
    """
    start, end = start.strip(), end.strip() or start.strip()
    if not start:
        raise ValueError(f"Type the starting {part}.")
    if start.casefold() == end.casefold():
        return [start]
    if re.fullmatch(r"\d+", start, re.ASCII) and re.fullmatch(r"\d+", end, re.ASCII):
        first, last = int(start), int(end)
        width = len(start) if start.startswith("0") else 0
        step = 1 if last >= first else -1
        return [str(number).zfill(width) for number in range(first, last + step, step)]
    if re.fullmatch(r"[A-Za-z]", start) and re.fullmatch(r"[A-Za-z]", end):
        first, last = ord(start.upper()), ord(end.upper())
        step = 1 if last >= first else -1
        letters = [chr(code) for code in range(first, last + step, step)]
        return [letter.lower() for letter in letters] if start.islower() else letters
    raise ValueError(
        f"The {part} range {start!r} to {end!r} must be two whole numbers (3 to 5) "
        "or two single letters (A to G)."
    )


def expand_sign_range(start_side: str, start_shelf: str, end_side: str = "", end_shelf: str = "") -> tuple[str, ...]:
    """Every side/shelf pair in the range, side by side: 3A..3G, 4A..4G, 5A..5G."""
    sides = _range_values(start_side, end_side, "side")
    shelves = _range_values(start_shelf, end_shelf, "shelf")
    if len(sides) * len(shelves) > MAX_SIGN_RANGE:
        raise ValueError(
            f"That range makes {len(sides) * len(shelves)} signs. "
            f"Keep one range to {MAX_SIGN_RANGE} or fewer."
        )
    return tuple(f"{side}{shelf}" for side in sides for shelf in shelves)


def parse_sign_names(text: str) -> tuple[str, ...]:
    """Typed names separated by commas, semicolons or new lines ("3A, 5B; 6E")."""
    return tuple(
        name for name in (clean_sign_name(part) for part in re.split(r"[,;\n]", text)) if name
    )


class HintEntry(ttk.Entry):
    """Entry that shows gray example text while it is empty and not focused."""

    def __init__(self, master, hint: str, on_change=None, **options):
        super().__init__(master, **options)
        self.hint = hint
        self.showing_hint = False
        self.bind("<FocusIn>", self._hide_hint, add="+")
        self.bind("<FocusOut>", self._show_hint, add="+")
        if on_change is not None:
            self.bind("<KeyRelease>", lambda _event: on_change(), add="+")
        self._show_hint()

    def value(self) -> str:
        return "" if self.showing_hint else self.get().strip()

    def clear(self):
        self.delete(0, "end")
        self.showing_hint = False
        if self.focus_get() is not self:
            self._show_hint()

    def _show_hint(self, _event=None):
        if not self.get():
            self.showing_hint = True
            self.configure(style="Hint.TEntry")
            self.insert(0, self.hint)

    def _hide_hint(self, _event=None):
        if self.showing_hint:
            self.showing_hint = False
            self.delete(0, "end")
            self.configure(style="TEntry")


def cells_for_printing(shelves: tuple[Shelf, ...], selected_slot_ids=None) -> tuple[Cell, ...]:
    """Keep numeric ground-up row/cell order; never sort by the location string."""
    cells = tuple(cell for shelf in shelves for cell in shelf.cells)
    if selected_slot_ids is not None:
        wanted = set(selected_slot_ids)
        existing = {cell.slot_id for cell in cells}
        if wanted - existing:
            raise ValueError("Some selected cells were removed. Refresh the database and select them again.")
        cells = tuple(cell for cell in cells if cell.slot_id in wanted)
    if not cells:
        raise ValueError("Select at least one cell to print." if selected_slot_ids is not None else "These shelves have no cells.")
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
        self.cell_boxes: dict[int, tuple[Cell, tuple[float, float, float, float]]] = {}
        self.drag: CellDrag | None = None
        self.autoscroll_id = None
        self.busy = False
        self.poll_id = None
        self.events = Queue()
        self.last_pdf = None
        self.print_reference_paths: tuple[Path, ...] = ()
        self.printed_locations: dict[str, tuple[PrintedPdfHit, ...]] = {}
        self.skip_printed = tk.BooleanVar(value=False)
        self.is_portrait = tk.BooleanVar(value=False)
        self.location_only = tk.BooleanVar(value=False)
        self.product_only = tk.BooleanVar(value=False)
        self.limit_to_30_characters = tk.BooleanVar(value=True)
        self.print_reference_text = tk.StringVar(value="No previous PDFs loaded.")
        self.db_text = tk.StringVar(value=str(self.database.path))
        self.search_text = tk.StringVar()
        self.label_height = tk.DoubleVar(value=7.0)
        self.summary_text = tk.StringVar(value="Select a shelf to begin.")
        self.location_text = tk.StringVar(value="Click a cell")
        self.sign_names: list[str] = []
        self.sign_filter_text = tk.StringVar()
        self.sign_preview_text = tk.StringVar()
        self.sign_summary_text = tk.StringVar()
        self.job_noun = "labels"
        self.status_text = tk.StringVar(value="Uses committed data. Commit changes in the mapper, then press Refresh here.")
        self._build_ui()
        if self.database.path.is_file():
            self.refresh_database()
        else:
            self.status_text.set("Choose your existing warehouse_locations.db with Browse database.")

    def _build_ui(self):
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Hint.TEntry", foreground="#8a8a8a")
        header = ttk.Frame(self.root, padding=(12, 10))
        header.pack(fill="x")
        ttk.Label(header, text="Warehouse Label Printer", font=("Segoe UI", 17, "bold")).pack(side="left")
        ttk.Label(header, text="A4 labels from saved shelf contents").pack(side="left", padx=20)
        database_bar = ttk.Frame(self.root, padding=(12, 0, 12, 10))
        database_bar.pack(fill="x")
        ttk.Label(database_bar, text="Database:").pack(side="left")
        ttk.Entry(database_bar, textvariable=self.db_text, state="readonly").pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(database_bar, text="Browse database", command=self.browse_database).pack(side="left")
        ttk.Button(database_bar, text="Refresh", command=self.refresh_database).pack(side="left", padx=(6, 0))

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=12)
        cell_tab = ttk.Frame(notebook)
        sign_tab = ttk.Frame(notebook)
        notebook.add(cell_tab, text="Cell labels")
        notebook.add(sign_tab, text="Shelf signs (14 x 14 cm)")

        panes = ttk.Panedwindow(cell_tab, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=(8, 0))
        shelf_panel = ttk.LabelFrame(panes, text="Shelves", padding=8, width=270)
        drawing_panel = ttk.LabelFrame(panes, text="Shelf view - click or drag across cells to select / deselect", padding=8)
        details_panel = ttk.LabelFrame(panes, text="Cell contents", padding=10, width=300)
        panes.add(shelf_panel, weight=2)
        panes.add(drawing_panel, weight=6)
        panes.add(details_panel, weight=3)

        ttk.Label(shelf_panel, text="Filter floor, side or shelf code").pack(anchor="w")
        search = ttk.Entry(shelf_panel, textvariable=self.search_text)
        search.pack(fill="x", pady=(4, 8))
        self.search_text.trace_add("write", self.filter_shelves)
        tree_frame = ttk.Frame(shelf_panel)
        tree_frame.pack(fill="both", expand=True)
        self.shelf_tree = ttk.Treeview(tree_frame, columns=("floor", "side", "code", "cells"), show="headings", selectmode="extended")
        for name, heading, width in [("floor", "Floor", 55), ("side", "Side", 50), ("code", "Shelf", 65), ("cells", "Cells", 50)]:
            self.shelf_tree.heading(name, text=heading)
            self.shelf_tree.column(name, width=width, minwidth=40, anchor="center", stretch=True)
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.shelf_tree.yview)
        self.shelf_tree.configure(yscrollcommand=scrollbar.set)
        self.shelf_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.shelf_tree.bind("<<TreeviewSelect>>", self.on_shelf_selection)
        ttk.Label(shelf_panel, text="Ctrl / Shift selects multiple shelves.", wraplength=230).pack(anchor="w", pady=(8, 0))

        controls = ttk.Frame(drawing_panel)
        controls.pack(fill="x", pady=(0, 7))
        for title, mode in [("Select all cells", "all"), ("Select occupied", "occupied"), ("Clear cells", "clear")]:
            ttk.Button(controls, text=title, command=lambda action=mode: self.mark_active_shelf(action)).pack(side="left", padx=(0, 5))
        drawing = ttk.Frame(drawing_panel)
        drawing.pack(fill="both", expand=True)
        drawing.rowconfigure(0, weight=1)
        drawing.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(drawing, background="white", highlightthickness=0)
        vertical = ttk.Scrollbar(drawing, orient="vertical", command=self.canvas.yview)
        horizontal = ttk.Scrollbar(drawing, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.canvas.bind("<Configure>", lambda _event: self.draw_shelf())
        self.canvas.bind("<MouseWheel>", lambda event: self.canvas.yview_scroll(-int(event.delta / 120), "units"))
        self.canvas.bind("<Shift-MouseWheel>", lambda event: self.canvas.xview_scroll(-int(event.delta / 120), "units"))
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Escape>", self.cancel_cell_drag)
        ttk.Label(drawing_panel, text="Blue = selected    Yellow = found in loaded PDF(s)    Green = occupied    Gray = empty").pack(anchor="w", pady=(7, 0))
        ttk.Label(
            drawing_panel,
            text="Drag a box to select cells. Start the drag on a blue cell to deselect instead. Esc cancels a drag.",
            foreground="#666666",
        ).pack(anchor="w", pady=(2, 0))

        ttk.Label(details_panel, textvariable=self.location_text, font=("Segoe UI", 18, "bold"), wraplength=285).pack(anchor="w", pady=(0, 10))
        self.details = tk.Text(details_panel, width=30, wrap="word", font=("Segoe UI", 10), relief="flat", state="disabled")
        self.details.pack(fill="both", expand=True)
        self.details.tag_configure("id", font=("Segoe UI", 10, "bold"), spacing1=12)
        self.details.tag_configure("name", spacing1=3, spacing3=8)
        self.details.tag_configure("note", foreground="#666666")
        self.details.tag_configure("history", font=("Segoe UI", 10, "bold"), foreground="#8a5a00")

        footer = ttk.Frame(cell_tab, padding=(0, 12))
        # Reserve the print controls before the expanding shelf view takes space.
        footer.pack(side="bottom", fill="x", before=panes)
        ttk.Label(footer, textvariable=self.summary_text).pack(anchor="w", pady=(0, 8))

        pdf_history = ttk.Frame(footer)
        pdf_history.pack(fill="x", pady=(0, 8))
        ttk.Button(pdf_history, text="Choose previous PDFs...", command=self.choose_printed_pdfs).pack(side="left")
        self.skip_printed_check = ttk.Checkbutton(
            pdf_history,
            text="Skip cells found in PDFs",
            variable=self.skip_printed,
            command=self.on_print_filter_changed,
        )
        self.skip_printed_check.pack(side="left", padx=(10, 8))
        ttk.Button(pdf_history, text="Clear PDFs", command=self.clear_printed_pdfs).pack(side="left")
        ttk.Checkbutton(
            pdf_history,
            text="Limit to 30 characters",
            variable=self.limit_to_30_characters,
        ).pack(side="left", padx=(12, 0))
        ttk.Label(pdf_history, textvariable=self.print_reference_text).pack(side="left", padx=(12, 0))

        buttons = ttk.Frame(footer)
        buttons.pack(fill="x")
        ttk.Label(buttons, text="Label height:").pack(side="left")
        for height in LABEL_HEIGHTS_CM:
            ttk.Radiobutton(
                buttons,
                text=f"{height:g} cm",
                variable=self.label_height,
                value=float(height),
            ).pack(side="left", padx=(6, 8))
        self.portrait_check = ttk.Checkbutton(
            buttons,
            text="Portrait orientation",
            variable=self.is_portrait,
        )
        self.portrait_check.pack(side="left", padx=(0, 10))
        self.location_only_check = ttk.Checkbutton(
            buttons,
            text="Location ID only",
            variable=self.location_only,
            command=self.on_location_only_toggle,
        )
        self.location_only_check.pack(side="left", padx=(0, 8))
        self.product_only_check = ttk.Checkbutton(
            buttons,
            text="Product list only",
            variable=self.product_only,
            command=self.on_product_only_toggle,
        )
        self.product_only_check.pack(side="left", padx=(0, 15))
        self.print_all_button = ttk.Button(buttons, text="Print all cells (PDF)...", command=lambda: self.start_print(False))
        self.print_all_button.pack(side="left", padx=(0, 8))
        self.print_selected_button = ttk.Button(buttons, text="Print selected cells (PDF)...", command=lambda: self.start_print(True))
        self.print_selected_button.pack(side="left")
        ttk.Button(buttons, text="Open last PDF", command=self.open_last_pdf).pack(side="right")
        ttk.Label(self.root, textvariable=self.status_text, relief="sunken", anchor="w", padding=(8, 4)).pack(
            side="bottom", fill="x", before=notebook,
        )
        self._build_sign_tab(sign_tab)
        self.update_summary()

    def _build_sign_tab(self, tab):
        panes = ttk.Panedwindow(tab, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=8)
        database_panel = ttk.LabelFrame(panes, text="Shelves in the database", padding=8, width=300)
        typed_panel = ttk.LabelFrame(panes, text="Type a range or names", padding=12, width=380)
        queue_panel = ttk.LabelFrame(panes, text="Signs to print", padding=8, width=300)
        panes.add(database_panel, weight=3)
        panes.add(typed_panel, weight=4)
        panes.add(queue_panel, weight=3)

        ttk.Label(database_panel, text="Filter floor, side or shelf code").pack(anchor="w")
        ttk.Entry(database_panel, textvariable=self.sign_filter_text).pack(fill="x", pady=(4, 8))
        self.sign_filter_text.trace_add("write", self.filter_sign_shelves)
        database_buttons = ttk.Frame(database_panel)
        database_buttons.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(database_buttons, text="Add selected", command=self.add_selected_database_signs).pack(side="left")
        ttk.Button(database_buttons, text="Add all shown", command=self.add_shown_database_signs).pack(side="left", padx=(6, 0))
        tree_frame = ttk.Frame(database_panel)
        tree_frame.pack(fill="both", expand=True)
        self.sign_tree = ttk.Treeview(tree_frame, columns=("sign", "floor", "side", "code"), show="headings", selectmode="extended")
        for name, heading, width in [("sign", "Sign", 60), ("floor", "Floor", 50), ("side", "Side", 50), ("code", "Shelf", 55)]:
            self.sign_tree.heading(name, text=heading)
            self.sign_tree.column(name, width=width, minwidth=40, anchor="center", stretch=True)
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.sign_tree.yview)
        self.sign_tree.configure(yscrollcommand=scrollbar.set)
        self.sign_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.sign_tree.bind("<Double-1>", lambda _event: self.add_selected_database_signs())

        ttk.Label(typed_panel, text="Range", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        range_grid = ttk.Frame(typed_panel)
        range_grid.pack(anchor="w", pady=(6, 0))
        ttk.Label(range_grid, text="Side").grid(row=0, column=1, sticky="w")
        ttk.Label(range_grid, text="Shelf").grid(row=0, column=3, sticky="w")
        self.sign_range_entries = []
        for row, (title, side_hint, shelf_hint) in enumerate([("From", "3", "A"), ("To", "5", "G")], start=1):
            ttk.Label(range_grid, text=title, width=6).grid(row=row, column=0, sticky="w", pady=3)
            side_entry = HintEntry(range_grid, side_hint, self.update_sign_preview, width=8, font=("Segoe UI", 12))
            side_entry.grid(row=row, column=1, pady=3)
            ttk.Label(range_grid, text="|", font=("Segoe UI", 12, "bold")).grid(row=row, column=2, padx=8)
            shelf_entry = HintEntry(range_grid, shelf_hint, self.update_sign_preview, width=8, font=("Segoe UI", 12))
            shelf_entry.grid(row=row, column=3, pady=3)
            for entry in (side_entry, shelf_entry):
                entry.bind("<Return>", lambda _event: self.add_range_signs())
            self.sign_range_entries += [side_entry, shelf_entry]
        ttk.Label(
            typed_panel, textvariable=self.sign_preview_text, wraplength=340, foreground="#2864a0",
        ).pack(anchor="w", fill="x", pady=(8, 0))
        ttk.Button(typed_panel, text="Add range to list", command=self.add_range_signs).pack(anchor="w", pady=(8, 0))
        ttk.Label(
            typed_panel,
            text="Numbers or single letters. Leave a To box blank to keep its From value: "
                 "From 3 | A To (blank) | G gives 3A to 3G.",
            wraplength=340, foreground="#666666",
        ).pack(anchor="w", fill="x", pady=(8, 0))

        ttk.Separator(typed_panel).pack(fill="x", pady=16)
        ttk.Label(typed_panel, text="Names", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.sign_names_entry = HintEntry(typed_panel, "3A, 5B, 6E", font=("Segoe UI", 12))
        self.sign_names_entry.pack(fill="x", pady=(6, 0))
        self.sign_names_entry.bind("<Return>", lambda _event: self.add_typed_signs())
        ttk.Button(typed_panel, text="Add names to list", command=self.add_typed_signs).pack(anchor="w", pady=(8, 0))
        ttk.Label(
            typed_panel,
            text="Separate names with commas. Any text works, even shelves that are not in the database yet.",
            wraplength=340, foreground="#666666",
        ).pack(anchor="w", fill="x", pady=(8, 0))

        queue_footer = ttk.Frame(queue_panel)
        queue_footer.pack(side="bottom", fill="x", pady=(8, 0))
        queue_buttons = ttk.Frame(queue_footer)
        queue_buttons.pack(fill="x")
        ttk.Button(queue_buttons, text="Remove selected", command=self.remove_selected_signs).pack(side="left")
        ttk.Button(queue_buttons, text="Clear list", command=self.clear_signs).pack(side="left", padx=(6, 0))
        ttk.Label(queue_footer, textvariable=self.sign_summary_text).pack(anchor="w", pady=(8, 8))
        print_buttons = ttk.Frame(queue_footer)
        print_buttons.pack(fill="x")
        self.print_signs_button = ttk.Button(print_buttons, text="Print signs (PDF)...", command=self.start_sign_print)
        self.print_signs_button.pack(side="left")
        ttk.Button(print_buttons, text="Open last PDF", command=self.open_last_pdf).pack(side="right")
        list_frame = ttk.Frame(queue_panel)
        list_frame.pack(fill="both", expand=True)
        self.sign_list = tk.Listbox(list_frame, selectmode="extended", font=("Segoe UI", 12), activestyle="none")
        list_scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.sign_list.yview)
        self.sign_list.configure(yscrollcommand=list_scrollbar.set)
        self.sign_list.pack(side="left", fill="both", expand=True)
        list_scrollbar.pack(side="right", fill="y")
        self.sign_list.bind("<Delete>", lambda _event: self.remove_selected_signs())
        self.update_sign_preview()

    def filter_sign_shelves(self, *_args):
        self.sign_tree.delete(*self.sign_tree.get_children())
        query = self.sign_filter_text.get().strip().casefold()
        for row in self.shelf_rows:
            if query in f"{row['floor']} {row['side']} {row['shelf_code']}".casefold():
                self.sign_tree.insert(
                    "", "end", iid=f"signshelf::{row['shelf_id']}",
                    values=(clean_sign_name(f"{row['side']}{row['shelf_code']}"), row["floor"], row["side"], row["shelf_code"]),
                )

    def _tree_signs(self, items):
        return [self.sign_tree.set(item, "sign") for item in items]

    def add_selected_database_signs(self):
        selected = set(self.sign_tree.selection())
        items = [item for item in self.sign_tree.get_children() if item in selected]
        if not items:
            self.status_text.set("Select shelves in the database list first (Ctrl / Shift selects several).")
            return
        self.add_signs(self._tree_signs(items), "the database")

    def add_shown_database_signs(self):
        self.add_signs(self._tree_signs(self.sign_tree.get_children()), "the database")

    def _range_text(self):
        return [entry.value() for entry in self.sign_range_entries]

    def update_sign_preview(self):
        from_side, from_shelf, to_side, to_shelf = self._range_text()
        if not (from_side or from_shelf or to_side or to_shelf):
            self.sign_preview_text.set("Type a range, for example From 3 | A To 5 | G.")
            return
        try:
            names = expand_sign_range(from_side, from_shelf, to_side, to_shelf)
        except ValueError as error:
            self.sign_preview_text.set(str(error))
            return
        shown = ", ".join(names) if len(names) <= 8 else f"{', '.join(names[:6])}, ... {names[-1]}"
        self.sign_preview_text.set(f"{len(names)} sign(s): {shown}")

    def add_range_signs(self):
        try:
            names = expand_sign_range(*self._range_text())
        except ValueError as error:
            messagebox.showerror("Cannot add range", str(error), parent=self.root)
            return
        self.add_signs(names, "the range")

    def add_typed_signs(self):
        names = parse_sign_names(self.sign_names_entry.value())
        if not names:
            self.status_text.set("Type one or more sign names, separated by commas.")
            return
        self.add_signs(names, "typed names")
        self.sign_names_entry.clear()

    def add_signs(self, names, source):
        """Append new names in order; names already in the list are not doubled."""
        queued = set(self.sign_names)
        added = []
        for name in map(clean_sign_name, names):
            if name and name not in queued:
                queued.add(name)
                added.append(name)
        self.sign_names += added
        self.sign_list.insert("end", *added)
        if added:
            self.sign_list.see("end")
        skipped = len(names) - len(added)
        skip_note = f" Skipped {skipped} already in the list." if skipped else ""
        self.status_text.set(f"Added {len(added)} sign(s) from {source}.{skip_note}")
        self.update_sign_summary()

    def remove_selected_signs(self):
        selected = self.sign_list.curselection()
        for index in reversed(selected):
            self.sign_list.delete(index)
            del self.sign_names[index]
        if selected:
            self.status_text.set(f"Removed {len(selected)} sign(s) from the list.")
        self.update_sign_summary()

    def clear_signs(self):
        self.sign_list.delete(0, "end")
        self.sign_names.clear()
        self.update_sign_summary()

    def update_sign_summary(self):
        count = len(self.sign_names)
        self.sign_summary_text.set(
            f"{count} sign(s) / {sign_page_count(count)} A4 page(s), {SIGNS_PER_PAGE} per page."
            if count else "Add signs from the database, a range or typed names."
        )
        self.print_signs_button.configure(state="normal" if count and not self.busy else "disabled")

    def on_location_only_toggle(self):
        if self.location_only.get():
            self.product_only.set(False)

    def on_product_only_toggle(self):
        if self.product_only.get():
            self.location_only.set(False)

    def selected_shelf_ids(self):
        selected = set(self.shelf_tree.selection())
        # The list's order is stable even when shelves were selected in another order.
        return [int(item.split("::", 1)[1]) for item in self.shelf_tree.get_children() if item in selected]

    def browse_database(self):
        path = filedialog.askopenfilename(parent=self.root, title="Choose the warehouse mapper database", filetypes=[("SQLite database", "*.db *.sqlite *.sqlite3"), ("All files", "*.*")])
        if path:
            self.refresh_database(Path(path))

    def choose_printed_pdfs(self):
        paths = filedialog.askopenfilenames(
            parent=self.root,
            title="Choose previously generated warehouse label PDFs",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not paths:
            return
        try:
            self._set_printed_pdfs(tuple(Path(path) for path in paths))
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
            messagebox.showerror("Cannot read previous PDFs", str(error), parent=self.root)

    def _set_printed_pdfs(self, paths: tuple[Path, ...]):
        known_locations = self.database.list_location_ids()
        hits = scan_printed_pdfs(paths, known_locations)
        self.print_reference_paths = tuple(Path(path).expanduser().resolve() for path in paths)
        self.printed_locations = hits
        self.skip_printed.set(bool(self.print_reference_paths))
        self.print_reference_text.set(
            f"{len(self.print_reference_paths)} PDF(s) loaded / {len(self.printed_locations)} matching cell(s)."
        )
        self.show_cell(self.active_cell)
        self.draw_shelf()
        self.update_summary()
        if not hits:
            messagebox.showinfo(
                "No matching cells found",
                "The selected PDFs were readable, but no current warehouse location IDs were found in them.",
                parent=self.root,
            )

    def clear_printed_pdfs(self):
        self.print_reference_paths = ()
        self.printed_locations.clear()
        self.skip_printed.set(False)
        self.print_reference_text.set("No previous PDFs loaded.")
        self.show_cell(self.active_cell)
        self.draw_shelf()
        self.update_summary()

    def on_print_filter_changed(self):
        self.update_summary()

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
        if self.print_reference_paths:
            try:
                self.printed_locations = scan_printed_pdfs(
                    self.print_reference_paths, candidate.list_location_ids()
                )
                self.print_reference_text.set(
                    f"{len(self.print_reference_paths)} PDF(s) loaded / {len(self.printed_locations)} matching cell(s)."
                )
            except (OSError, sqlite3.Error, ValueError, RuntimeError):
                self.print_reference_paths = ()
                self.printed_locations.clear()
                self.skip_printed.set(False)
                self.print_reference_text.set("Previous PDFs cleared after database refresh.")
        self.filter_shelves()
        self.filter_sign_shelves()
        self.show_cell(None)
        self.draw_shelf()
        self.status_text.set(f"Loaded {len(rows)} shelves. Cell selections cleared. Only committed placements are shown.")

    def filter_shelves(self, *_args):
        previous = set(self.shelf_tree.selection())
        self.shelf_tree.delete(*self.shelf_tree.get_children())
        query = self.search_text.get().strip().casefold()
        for row in self.shelf_rows:
            if query in f"{row['floor']} {row['side']} {row['shelf_code']}".casefold():
                self.shelf_tree.insert("", "end", iid=f"shelf::{row['shelf_id']}", values=(row["floor"], row["side"], row["shelf_code"], row["cell_count"]))
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
        self.marked = {slot for slot in self.marked if self.cell_shelves.get(slot) in selected}
        if not selected:
            self.active_shelf = None
            self.show_cell(None)
        else:
            focus = self.shelf_tree.focus()
            shelf_id = int(focus.split("::", 1)[1]) if focus in self.shelf_tree.selection() else selected[0]
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

    def _cell_fill(self, cell, marked):
        if marked:
            return SELECTED_FILL
        if _location_key(cell.location_id) in self.printed_locations:
            return "#fff2cc"
        return "#e4efdf" if cell.products else "#f6f6f6"

    def draw_shelf(self):
        self.canvas.delete("all")
        self.rectangles.clear()
        self.cell_boxes.clear()
        if self.drag is not None:
            self.drag.band = None
        shelf = self.active_shelf
        if shelf is None:
            self.canvas.create_text(25, 30, anchor="nw", text="Select a saved shelf from the list.", font=("Segoe UI", 12))
            return
        self.canvas.create_text(18, 18, anchor="nw", text=f"Floor {shelf.floor} / Side {shelf.side} / Shelf {shelf.code}", font=("Segoe UI", 14, "bold"))
        max_columns = max((count for _, count in shelf.rows), default=1)
        row_w = max(600, self.canvas.winfo_width() - 115, max_columns * 100)
        by_row = defaultdict(list)
        for cell in shelf.cells:
            by_row[cell.row_number].append(cell)
        for screen_row, (number, count) in enumerate(reversed(shelf.rows)):
            y = 60 + screen_row * 82
            self.canvas.create_text(10, y + 35, anchor="w", text=f"Row {number}" + ("\nGround" if number == 1 else ""), font=("Segoe UI", 10, "bold"))
            self.canvas.create_rectangle(90, y, 90 + row_w, y + 74, fill="#eeeeee", outline="#bbbbbb")
            if not count:
                self.canvas.create_text(100, y + 35, anchor="w", text="No cells")
                continue
            for cell in by_row[number]:
                width = row_w / count
                position = shelf_cell_number(cell.slot_number, count, shelf.revert_location_id)
                x = 90 + (position - 1) * width
                tag = f"cell_{cell.slot_id}"
                marked = cell.slot_id in self.marked
                active = self.active_cell is not None and self.active_cell.slot_id == cell.slot_id
                box = (x + 2, y + 2, x + width - 2, y + 72)
                rectangle = self.canvas.create_rectangle(*box, fill=self._cell_fill(cell, marked), outline="#2864a0" if active else "#a0a0a0", width=3 if active else 1, tags=tag)
                self.rectangles[cell.slot_id] = rectangle
                self.cell_boxes[cell.slot_id] = (cell, box)
                self.canvas.create_text(x + width / 2, y + 25, text=cell.location_id, width=width - 10, font=("Segoe UI", 9, "bold"), tags=tag)
                self.canvas.create_text(x + width / 2, y + 54, text=f"{'[x] ' if marked else ''}{len(cell.products)} product(s)", font=("Segoe UI", 9), tags=tag)
        self.canvas.configure(scrollregion=(0, 0, row_w + 105, 75 + len(shelf.rows) * 82))

    def _cell_at(self, x, y):
        for cell, (left, top, right, bottom) in self.cell_boxes.values():
            if left <= x <= right and top <= y <= bottom:
                return cell
        return None

    def _drag_box(self, drag):
        x = self.canvas.canvasx(drag.pointer[0])
        y = self.canvas.canvasy(drag.pointer[1])
        return min(drag.start_x, x), min(drag.start_y, y), max(drag.start_x, x), max(drag.start_y, y)

    def _cells_in_drag(self, drag):
        """Every cell the box touches, not only the ones fully inside it."""
        left, top, right, bottom = self._drag_box(drag)
        return {
            slot_id for slot_id, (_, (x1, y1, x2, y2)) in self.cell_boxes.items()
            if x1 <= right and x2 >= left and y1 <= bottom and y2 >= top
        }

    def on_canvas_press(self, event):
        self.canvas.focus_set()
        if self.active_shelf is None:
            return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        cell = self._cell_at(x, y)
        self.drag = CellDrag(
            event.x, event.y, x, y, cell,
            select=cell is None or cell.slot_id not in self.marked,
            pointer=(event.x, event.y),
        )

    def on_canvas_drag(self, event):
        drag = self.drag
        if drag is None:
            return
        drag.pointer = (event.x, event.y)
        if not drag.started:
            if max(abs(event.x - drag.press_x), abs(event.y - drag.press_y)) < DRAG_THRESHOLD_PX:
                return
            drag.started = True
        self._show_drag(drag)
        if self.autoscroll_id is None:
            self._autoscroll()

    def _show_drag(self, drag):
        """Draw the box and preview each cell's colour as if the mouse were released now."""
        colour = "#2864a0" if drag.select else "#c0392b"
        if drag.band is None:
            drag.band = self.canvas.create_rectangle(0, 0, 0, 0, outline=colour, width=2, dash=(5, 3))
        self.canvas.coords(drag.band, *self._drag_box(drag))
        self.canvas.tag_raise(drag.band)
        hits = self._cells_in_drag(drag)
        for slot_id, (cell, _) in self.cell_boxes.items():
            marked = drag.select if slot_id in hits else slot_id in self.marked
            self.canvas.itemconfigure(self.rectangles[slot_id], fill=self._cell_fill(cell, marked))
        action = "select" if drag.select else "deselect"
        self.status_text.set(f"Release to {action} {len(hits)} cell(s). Press Esc to cancel.")

    def _autoscroll(self):
        """Keep scrolling while a drag is held past the edge of the shelf view."""
        self.autoscroll_id = None
        drag = self.drag
        if drag is None or not drag.started:
            return
        x, y = drag.pointer
        dx = -1 if x < 0 else 1 if x > self.canvas.winfo_width() else 0
        dy = -1 if y < 0 else 1 if y > self.canvas.winfo_height() else 0
        if not (dx or dy):
            return
        if dx:
            self.canvas.xview_scroll(dx, "units")
        if dy:
            self.canvas.yview_scroll(dy, "units")
        self._show_drag(drag)
        self.autoscroll_id = self.root.after(60, self._autoscroll)

    def _end_drag(self):
        drag, self.drag = self.drag, None
        if self.autoscroll_id is not None:
            self.root.after_cancel(self.autoscroll_id)
            self.autoscroll_id = None
        return drag

    def on_canvas_release(self, event):
        drag = self.drag
        if drag is None:
            return
        drag.pointer = (event.x, event.y)
        hits = self._cells_in_drag(drag) if drag.started else set()
        self._end_drag()
        if not drag.started:
            if drag.cell is not None:
                self.toggle_cell(drag.cell)
            return
        if drag.select:
            self.marked.update(hits)
        else:
            self.marked.difference_update(hits)
        self.status_text.set(f"{'Selected' if drag.select else 'Deselected'} {len(hits)} cell(s) by dragging.")
        self.draw_shelf()
        self.update_summary()

    def cancel_cell_drag(self, _event=None):
        drag = self._end_drag()
        if drag is not None and drag.started:
            self.status_text.set("Drag cancelled. The selection did not change.")
            self.draw_shelf()

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
            self.marked.update(cell.slot_id for cell in self.active_shelf.cells if action == "all" or cell.products)
        self.draw_shelf()
        self.update_summary()

    def show_cell(self, cell):
        self.active_cell = cell
        self.location_text.set(cell.location_id if cell else "Click a cell")
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        if cell is not None:
            self.details.insert("end", f"Row {cell.row_number} / Cell {cell.slot_number}\n", "note")
            for product in cell.products:
                self.details.insert("end", product.product_id + "\n", "id")
                self.details.insert("end", product.name + "\n", "name")
            if not cell.products:
                self.details.insert("end", "\nNo products assigned. The location ID will still print.", "note")
            hits = self.printed_locations.get(_location_key(cell.location_id), ())
            if hits:
                latest = hits[-1]
                self.details.insert("end", f"\nFound in {len(hits)} loaded PDF(s)\n", "history")
                self.details.insert("end", f"Latest PDF: {latest.path.name}\n", "note")
                self.details.insert("end", f"PDF created: {latest.created_at:%Y-%m-%d %H:%M:%S}\n", "note")
                self.details.insert("end", "This records PDF generation, not confirmation from the physical printer.", "note")
        self.details.configure(state="disabled")

    def update_summary(self):
        selected = self.selected_shelf_ids()
        filter_note = ""
        if self.print_reference_paths:
            mode = "skipping matches" if self.skip_printed.get() else "filter off - reprints allowed"
            filter_note = f" Previous PDFs: {len(self.printed_locations)} cell(s) found, {mode}."
        self.summary_text.set(
            f"{len(selected)} shelf(s) selected / {len(self.marked)} cells marked. "
            f"Print order: ground row upward, left to right.{filter_note}"
        )
        self.print_all_button.configure(state="normal" if selected and not self.busy else "disabled")
        self.print_selected_button.configure(state="normal" if self.marked and selected and not self.busy else "disabled")
        self.skip_printed_check.configure(state="normal" if self.print_reference_paths and not self.busy else "disabled")
        self.update_sign_summary()

    def start_sign_print(self):
        if self.busy or not self.sign_names:
            return
        names = tuple(self.sign_names)
        output = data_directory() / "labels" / f"shelf_signs_14cm_{datetime.now():%Y%m%d_%H%M%S_%f}.pdf"
        self.busy = True
        self.job_noun = "signs"
        self.update_summary()
        self.status_text.set(f"Preparing {len(names)} shelf sign(s) on {sign_page_count(len(names))} A4 page(s)...")
        Thread(target=self._generate_signs_pdf, args=(names, output), daemon=True).start()
        self.poll_id = self.root.after(100, self._poll)

    def _generate_signs_pdf(self, names, output):
        try:
            result = render_shelf_signs_pdf(
                names, output, progress=lambda text: self.events.put(("progress", text)),
            )
            self.events.put(("done", result))
        except Exception as error:
            self.events.put(("error", str(error)))

    def start_print(self, selected_only):
        if self.busy:
            return
        try:
            shelves = self.database.read_shelves(self.selected_shelf_ids())
            cells = cells_for_printing(shelves, self.marked if selected_only else None)
            requested_count = len(cells)
            skipped_count = 0
            if self.skip_printed.get() and self.printed_locations:
                cells = tuple(
                    cell for cell in cells
                    if _location_key(cell.location_id) not in self.printed_locations
                )
                skipped_count = requested_count - len(cells)
                if not cells:
                    messagebox.showinfo(
                        "Nothing new to print",
                        f"All {requested_count} requested cell(s) were found in the loaded PDFs.\n\n"
                        "Uncheck 'Skip cells found in PDFs' to intentionally reprint them.",
                        parent=self.root,
                    )
                    return
            height_cm = self.label_height.get()
            height_label = f"{height_cm:g}"
            orientation = "portrait" if self.is_portrait.get() else "landscape"
            print_mode = (
                "location_only" if self.location_only.get()
                else "product_only" if self.product_only.get()
                else "full"
            )
            limit_to_30_characters = self.limit_to_30_characters.get()
        except (OSError, sqlite3.Error, ValueError) as error:
            messagebox.showerror("Cannot print labels", str(error), parent=self.root)
            return
        mode_prefix = f"{print_mode}_" if print_mode != "full" else ""
        output = data_directory() / "labels" / f"warehouse_labels_{mode_prefix}{height_label}cm_{orientation}_{datetime.now():%Y%m%d_%H%M%S_%f}.pdf"
        self.busy = True
        self.job_noun = "labels"
        self.update_summary()
        skip_note = f" Skipped {skipped_count} cell(s) found in previous PDFs." if skipped_count else ""
        mode_note = {
            "location_only": ", location ID only",
            "product_only": ", product list only",
            "full": "",
        }[print_mode]
        self.status_text.set(
            f"Preparing {label_count(cells)} labels ({height_label} cm, {orientation}{mode_note}) from latest placements...{skip_note}"
        )
        Thread(
            target=self._generate_pdf,
            args=(cells, output, height_cm, orientation, print_mode, limit_to_30_characters),
            daemon=True,
        ).start()
        self.poll_id = self.root.after(100, self._poll)

    def _generate_pdf(
        self, cells, output, height_cm, orientation="landscape", print_mode="full",
        limit_to_30_characters=True,
    ):
        try:
            result = render_labels_pdf(
                cells,
                output,
                label_height_cm=height_cm,
                orientation=orientation,
                print_mode=print_mode,
                limit_to_30_characters=limit_to_30_characters,
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
                self.status_text.set(f"{value.labels} {self.job_noun} / {value.pages} A4 page(s). Press Ctrl+P in the opened PDF. Saved: {value.path.name}")
                self.open_last_pdf()
            return
        if self.busy:
            self.poll_id = self.root.after(100, self._poll)

    def open_last_pdf(self):
        if self.last_pdf is None:
            messagebox.showinfo("No PDF yet", "Print some cell labels or shelf signs first.", parent=self.root)
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(self.last_pdf))
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(self.last_pdf)])
        except OSError as error:
            messagebox.showinfo("PDF saved", f"Open this file manually to print:\n{self.last_pdf}\n\n{error}", parent=self.root)

    def close(self):
        if self.busy:
            messagebox.showinfo("Preparing PDF", "Wait for the PDF to finish before closing.", parent=self.root)
            return
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="Print A4 labels from a warehouse mapper SQLite database.")
    parser.add_argument("--db", type=Path, help="SQLite database (defaults to the active mapper database)")
    args = parser.parse_args()
    root = tk.Tk()
    LabelPrinterApp(root, args.db or default_database_path())
    root.mainloop()


if __name__ == "__main__":
    main()

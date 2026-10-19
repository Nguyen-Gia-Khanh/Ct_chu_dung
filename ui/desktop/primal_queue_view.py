"""Primal queue search and interactive shelf view tab."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from mapper.core.common import MAX_VISIBLE_PRODUCTS, exact_product_search_id, normalize_search, normalize_sku, product_search_text
from mapper.persistence.database import Placement, WarehouseDatabase
from mapper.services.shelf_grid import load_grid
from .shelf_address_lookup import ShelfAddressLookup
from .widgets import ShelfGridCanvas, sync_tree_rows
from utils.barcode_scanner import BarcodeScanner, bind_auto_highlight


class PrimalQueueView(ttk.Frame):
    """Tab 3: Search primal queue (CSV hot sellers) & full catalog with 2D shelf view."""

    def __init__(
        self,
        parent: tk.Misc,
        database: WarehouseDatabase,
        barcode_scanner: BarcodeScanner | None = None,
    ) -> None:
        super().__init__(parent, padding=10)
        self.database = database

        self.products: dict[str, str] = {}
        self.product_brands: dict[str, str] = {}
        self.product_search: dict[str, str] = {}

        self.catalog_products: dict[str, tuple[str, str]] = {}
        self.catalog_search: dict[str, str] = {}

        self.placements: dict[str, Placement] = {}
        self.on_hand_products: dict[str, object] = {}

        self.shelves: list[tuple[int, str, str, str]] = []
        self.shelf_choices: dict[str, int] = {}
        self.current_shelf_id: int | None = None
        self.current_contents: list[tuple[str, str, Placement]] = []

        self.search_after_id: str | None = None

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(
            header,
            text="Primal Product Queue (Hot Sellers from CSV) · Catalog Search · Shelf Viewer",
            style="Heading.TLabel",
        ).pack(side="left")

        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True)

        left_pane = ttk.LabelFrame(
            pane, text="Products (Primal Queue & Full Catalog)", padding=8
        )
        right_pane = ttk.LabelFrame(pane, text="Shelf View", padding=8)
        pane.add(left_pane, weight=5)
        pane.add(right_pane, weight=6)

        self._build_left_pane(left_pane)
        self._build_right_pane(right_pane)

        self.barcode_scanner = barcode_scanner

    def _build_left_pane(self, parent: ttk.LabelFrame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)

        ttk.Label(
            parent, text="Search code, full name, or brand name"
        ).grid(row=0, column=0, sticky="w")

        self.search_var = tk.StringVar(self)
        self.search_entry = ttk.Entry(parent, textvariable=self.search_var)
        self.search_entry.grid(row=1, column=0, sticky="ew", pady=(3, 4))
        self.search_entry.bind("<Return>", self.format_primary_search)
        bind_auto_highlight(self.search_entry)
        self.search_var.trace_add("write", self._schedule_search)

        self.search_status_text = tk.StringVar(
            self, value="Type or scan a product ID to check if it is a hot seller."
        )
        ttk.Label(
            parent,
            textvariable=self.search_status_text,
            foreground="#555555",
            wraplength=450,
        ).grid(row=2, column=0, sticky="w", pady=(0, 6))

        split = ttk.Panedwindow(parent, orient="vertical")
        split.grid(row=3, column=0, sticky="nsew")

        primal_frame = ttk.LabelFrame(
            split, text="Primal Product Queue (Hot Sellers imported from CSV)", padding=6
        )
        catalog_frame = ttk.LabelFrame(
            split, text="Full Product Catalog", padding=6
        )
        split.add(primal_frame, weight=1)
        split.add(catalog_frame, weight=1)

        # 1. Primal queue tree
        primal_frame.columnconfigure(0, weight=1)
        primal_frame.rowconfigure(0, weight=1)
        primal_body = ttk.Frame(primal_frame)
        primal_body.grid(row=0, column=0, sticky="nsew")
        primal_body.columnconfigure(0, weight=1)
        primal_body.rowconfigure(0, weight=1)

        self.primal_tree = ttk.Treeview(
            primal_body,
            columns=("product_id", "product_name", "location", "stock_qty"),
            show="headings",
            selectmode="browse",
            height=8,
        )
        self.primal_tree.heading("product_id", text="Product ID")
        self.primal_tree.heading("product_name", text="Product name")
        self.primal_tree.heading("location", text="Location")
        self.primal_tree.heading("stock_qty", text="Stock")

        self.primal_tree.column("product_id", width=110, minwidth=80, stretch=False)
        self.primal_tree.column("product_name", width=180, minwidth=100)
        self.primal_tree.column("location", width=110, minwidth=85, stretch=False)
        self.primal_tree.column(
            "stock_qty", width=55, minwidth=40, anchor="e", stretch=False
        )

        self.primal_tree.tag_configure("on_hand", background="#e1f5fe")
        self.primal_tree.tag_configure("unassigned", foreground="#888888")

        primal_y_scroll = ttk.Scrollbar(
            primal_body, orient="vertical", command=self.primal_tree.yview
        )
        primal_x_scroll = ttk.Scrollbar(
            primal_body, orient="horizontal", command=self.primal_tree.xview
        )
        self.primal_tree.configure(
            yscrollcommand=primal_y_scroll.set,
            xscrollcommand=primal_x_scroll.set,
        )
        self.primal_tree.grid(row=0, column=0, sticky="nsew")
        primal_y_scroll.grid(row=0, column=1, sticky="ns")
        primal_x_scroll.grid(row=1, column=0, sticky="ew")

        self.primal_tree.bind("<Double-1>", self._on_primal_double_click)
        self.primal_tree.bind("<<TreeviewSelect>>", self._on_primal_select)

        self.primal_count_text = tk.StringVar(self, value="0 hot sellers")
        ttk.Label(primal_frame, textvariable=self.primal_count_text).grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )

        # 2. Catalog tree
        catalog_frame.columnconfigure(0, weight=1)
        catalog_frame.rowconfigure(0, weight=1)
        catalog_body = ttk.Frame(catalog_frame)
        catalog_body.grid(row=0, column=0, sticky="nsew")
        catalog_body.columnconfigure(0, weight=1)
        catalog_body.rowconfigure(0, weight=1)

        self.catalog_tree = ttk.Treeview(
            catalog_body,
            columns=("product_id", "product_name", "brand_name"),
            show="headings",
            selectmode="browse",
            height=8,
        )
        self.catalog_tree.heading("product_id", text="Product ID")
        self.catalog_tree.heading("product_name", text="Product name")
        self.catalog_tree.heading("brand_name", text="Brand name")

        self.catalog_tree.column("product_id", width=110, minwidth=80, stretch=False)
        self.catalog_tree.column("product_name", width=180, minwidth=100)
        self.catalog_tree.column("brand_name", width=120, minwidth=80)

        catalog_y_scroll = ttk.Scrollbar(
            catalog_body, orient="vertical", command=self.catalog_tree.yview
        )
        catalog_x_scroll = ttk.Scrollbar(
            catalog_body, orient="horizontal", command=self.catalog_tree.xview
        )
        self.catalog_tree.configure(
            yscrollcommand=catalog_y_scroll.set,
            xscrollcommand=catalog_x_scroll.set,
        )
        self.catalog_tree.grid(row=0, column=0, sticky="nsew")
        catalog_y_scroll.grid(row=0, column=1, sticky="ns")
        catalog_x_scroll.grid(row=1, column=0, sticky="ew")

        self.catalog_tree.bind("<Double-1>", self._on_catalog_double_click)
        self.catalog_tree.bind("<<TreeviewSelect>>", self._on_catalog_select)

        self.catalog_count_text = tk.StringVar(self, value="0 catalog products")
        ttk.Label(catalog_frame, textvariable=self.catalog_count_text).grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )

    def _build_right_pane(self, parent: ttk.LabelFrame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=3)
        parent.rowconfigure(3, weight=2)

        controls = ttk.Frame(parent)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        chooser = ttk.Frame(controls)
        chooser.pack(fill="x", pady=(0, 5))
        ttk.Label(chooser, text="Shelf:").pack(side="left")
        self.shelf_selector = ttk.Combobox(chooser, state="readonly", width=36)
        self.shelf_selector.pack(side="left", padx=(6, 5))
        self.shelf_selector.bind("<<ComboboxSelected>>", lambda _e: self.load_selected_shelf())
        ttk.Button(chooser, text="Load shelf", command=self.load_selected_shelf).pack(side="left")
        self.shelf_address_lookup = ShelfAddressLookup(
            controls, self.database.list_shelves, self._load_shelf_by_id
        )
        self.shelf_address_lookup.pack(fill="x")

        shelf_frame = ttk.LabelFrame(parent, text="Shelf 2D View — click cell to inspect", padding=4)
        shelf_frame.grid(row=1, column=0, sticky="nsew")
        shelf_frame.columnconfigure(0, weight=1)
        shelf_frame.rowconfigure(0, weight=1)

        self.shelf_grid = ShelfGridCanvas(
            shelf_frame, on_select=lambda cell: self.select_slot(cell.slot_name), min_row_width=340,
            label=lambda cell: f"R{cell.row}-C{cell.cell:02d}")
        self.shelf_grid.grid(row=0, column=0, sticky="nsew")

        self.slot_header_text = tk.StringVar(self, value="No cell selected")
        ttk.Label(
            parent,
            textvariable=self.slot_header_text,
            style="Heading.TLabel",
        ).grid(row=2, column=0, sticky="w", pady=(6, 4))

        contents_frame = ttk.Frame(parent)
        contents_frame.grid(row=3, column=0, sticky="nsew")
        contents_frame.columnconfigure(0, weight=1)
        contents_frame.rowconfigure(0, weight=1)

        self.contents_tree = ttk.Treeview(
            contents_frame,
            columns=("product_id", "product_name", "stock_qty"),
            show="headings",
            height=6,
        )
        self.contents_tree.heading("product_id", text="Product ID")
        self.contents_tree.heading("product_name", text="Product name")
        self.contents_tree.heading("stock_qty", text="Stock")

        self.contents_tree.column("product_id", width=110, minwidth=80, stretch=False)
        self.contents_tree.column("product_name", width=220, minwidth=120)
        self.contents_tree.column(
            "stock_qty", width=65, minwidth=45, anchor="e", stretch=False
        )

        c_y_scroll = ttk.Scrollbar(
            contents_frame, orient="vertical", command=self.contents_tree.yview
        )
        c_x_scroll = ttk.Scrollbar(
            contents_frame, orient="horizontal", command=self.contents_tree.xview
        )
        self.contents_tree.configure(
            yscrollcommand=c_y_scroll.set,
            xscrollcommand=c_x_scroll.set,
        )
        self.contents_tree.grid(row=0, column=0, sticky="nsew")
        c_y_scroll.grid(row=0, column=1, sticky="ns")
        c_x_scroll.grid(row=1, column=0, sticky="ew")

        self.contents_tree.bind("<Double-1>", self._on_contents_double_click)

        self._render_empty_shelf("Choose a shelf above or search a product on the left.")

    def refresh(self) -> None:
        """Reload all data from database and refresh views."""
        product_rows = self.database.get_product_records()
        self.products = {
            product_id: product_name
            for product_id, product_name, _brand_name in product_rows
        }
        self.product_brands = {
            product_id: brand_name
            for product_id, _product_name, brand_name in product_rows
        }
        self.product_search = {
            row[0]: product_search_text(*row) for row in product_rows
        }

        catalog_rows = self.database.get_catalog_products()
        self.catalog_products = {
            product_id: (product_name, brand_name)
            for product_id, product_name, brand_name in catalog_rows
        }
        self.catalog_search = {
            row[0]: product_search_text(*row) for row in catalog_rows
        }

        self.placements = self.database.get_placement_details()
        self.on_hand_products = self.database.get_on_hand_products()

        self.shelves = self.database.list_shelves()
        choices = {
            f"Floor {floor} — Side {side} — Shelf {shelf_code}": shelf_id
            for shelf_id, floor, side, shelf_code in self.shelves
        }
        if choices != self.shelf_choices:
            self.shelf_selector.configure(values=list(choices))
        self.shelf_choices = choices

        if self.current_shelf_id is not None:
            if self.current_shelf_id in self.shelf_choices.values():
                for label, s_id in self.shelf_choices.items():
                    if s_id == self.current_shelf_id:
                        self.shelf_selector.set(label)
                        break
                self._load_shelf_by_id(self.current_shelf_id, select_slot=self.selected_slot_name)
            else:
                self.current_shelf_id = None
                self._render_empty_shelf("Shelf no longer exists.")
        else:
            self._render_empty_shelf("Choose a shelf above or search a product on the left.")

        self.refresh_results(navigate=False)

    def _schedule_search(self, *_args: object) -> None:
        if self.search_after_id:
            self.after_cancel(self.search_after_id)
        self.search_after_id = self.after(180, self.refresh_results)

    def refresh_results(self, *, navigate: bool = True) -> None:
        if self.search_after_id:
            self.after_cancel(self.search_after_id)
            self.search_after_id = None

        raw_query = self.search_var.get().strip()
        query = normalize_search(normalize_sku(raw_query))

        # 1. Primal queue filtering
        primal_matches = [
            product_id
            for product_id in self.products
            if not query or query in self.product_search[product_id]
        ]
        primal_matches.sort(
            key=lambda pid: (
                pid.casefold() != raw_query.casefold(),
                pid not in self.placements,
                pid.casefold(),
            )
        )

        primal_rows = []
        for product_id in primal_matches[:MAX_VISIBLE_PRODUCTS]:
            name = self.products[product_id]
            if product_id in self.placements:
                placement = self.placements[product_id]
                loc = placement.slot_name
                qty = str(placement.stock_qty) if placement.stock_qty is not None else "Unknown"
                tag = "assigned"
            elif product_id in self.on_hand_products:
                item = self.on_hand_products[product_id]
                loc = "On-hand"
                qty = str(item.stock_qty) if getattr(item, "stock_qty", None) is not None else "Unknown"
                tag = "on_hand"
            else:
                loc = "Unassigned"
                qty = ""
                tag = "unassigned"

            primal_rows.append((f"primal::{product_id}", (product_id, name, loc, qty), (tag,)))
        sync_tree_rows(self.primal_tree, primal_rows)

        shown_primal = min(len(primal_matches), MAX_VISIBLE_PRODUCTS)
        self.primal_count_text.set(
            f"{len(primal_matches):,} matching hot seller(s) · showing {shown_primal:,}"
        )

        # 2. Catalog filtering
        catalog_matches = [
            (product_id, product_name, brand_name)
            for product_id, (product_name, brand_name) in self.catalog_products.items()
            if not query or query in self.catalog_search[product_id]
        ]
        catalog_matches.sort(
            key=lambda item: (
                item[0].casefold() != raw_query.casefold(),
                item[0].casefold(),
            )
        )

        catalog_rows = []
        for product_id, product_name, brand_name in catalog_matches[:MAX_VISIBLE_PRODUCTS]:
            catalog_rows.append((
                f"catalog::{product_id}",
                (product_id, product_name, brand_name), (),
            ))
        sync_tree_rows(self.catalog_tree, catalog_rows)

        shown_cat = min(len(catalog_matches), MAX_VISIBLE_PRODUCTS)
        self.catalog_count_text.set(
            f"{len(catalog_matches):,} matching catalog product(s) · showing {shown_cat:,}"
        )

        # 3. Status text & automatic shelf navigation for exact product ID query
        self._update_search_status(raw_query, navigate=navigate)

    def _update_search_status(self, raw_query: str, *, navigate: bool = True) -> None:
        if not raw_query:
            self.search_status_text.set("Type or scan a product ID to check if it is a hot seller.")
            return

        product_id = exact_product_search_id(
            raw_query,
            (
                item_id.partition("::")[2]
                for tree in (self.primal_tree, self.catalog_tree)
                for item_id in tree.get_children()
            ),
        )
        exact_id = product_id if product_id in self.products else None
        if exact_id is not None:
            name = self.products[exact_id]
            if exact_id in self.placements:
                placement = self.placements[exact_id]
                qty = f" · Stock: {placement.stock_qty}" if placement.stock_qty is not None else ""
                self.search_status_text.set(
                    f"✓ HOT SELLER (in Primal Queue): {exact_id} — {name} · Located at {placement.slot_name}{qty}"
                )
                if navigate:
                    self._highlight_product_location(exact_id)
            elif exact_id in self.on_hand_products:
                item = self.on_hand_products[exact_id]
                qty = f" (Stock: {item.stock_qty})" if getattr(item, "stock_qty", None) is not None else ""
                self.search_status_text.set(
                    f"✓ HOT SELLER (in Primal Queue): {exact_id} — {name} · Currently On-hand{qty}"
                )
            else:
                self.search_status_text.set(
                    f"✓ HOT SELLER (in Primal Queue): {exact_id} — {name} · Currently Unassigned in queue"
                )
            return

        cat_id = product_id if product_id in self.catalog_products else None
        if cat_id is not None:
            name, _ = self.catalog_products[cat_id]
            loc_info = ""
            if cat_id in self.placements:
                loc_info = f" · Located at {self.placements[cat_id].slot_name}"
                self._highlight_product_location(cat_id)
            self.search_status_text.set(
                f"✗ NOT a hot seller (Full Catalog only): {cat_id} — {name}{loc_info}"
            )
            return

        self.search_status_text.set(f"No exact match for '{raw_query}'.")

    def _fill_search_bar(self, product_id: str) -> None:
        """Fill product ID into search entry, focus, and select all text."""
        self.search_var.set(product_id)
        self.after_idle(self._select_entry)
        self.refresh_results()

    def _select_entry(self) -> None:
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, tk.END)
        self.search_entry.icursor(tk.END)

    def _on_primal_double_click(self, event: tk.Event) -> str | None:
        row_id = self.primal_tree.identify_row(event.y)
        if not row_id or not row_id.startswith("primal::"):
            return None
        product_id = row_id.removeprefix("primal::")
        self._fill_search_bar(product_id)
        return "break"

    def _on_primal_select(self, _event: tk.Event | None = None) -> None:
        selected = self.primal_tree.selection()
        if not selected:
            return
        product_id = selected[0].removeprefix("primal::")
        self._highlight_product_location(product_id)

    def _on_catalog_double_click(self, event: tk.Event) -> str | None:
        row_id = self.catalog_tree.identify_row(event.y)
        if not row_id or not row_id.startswith("catalog::"):
            return None
        product_id = row_id.removeprefix("catalog::")
        self._fill_search_bar(product_id)
        return "break"

    def _on_catalog_select(self, _event: tk.Event | None = None) -> None:
        selected = self.catalog_tree.selection()
        if not selected:
            return
        product_id = selected[0].removeprefix("catalog::")
        self._highlight_product_location(product_id)

    def _on_contents_double_click(self, event: tk.Event) -> str | None:
        row_id = self.contents_tree.identify_row(event.y)
        if not row_id:
            return None
        values = self.contents_tree.item(row_id, "values")
        if not values:
            return None
        product_id = str(values[0]).strip()
        if product_id:
            self._fill_search_bar(product_id)
            return "break"
        return None

    def _highlight_product_location(self, product_id: str) -> None:
        location = self.database.get_product_location(product_id)
        if location is None:
            return
        if self.current_shelf_id != location.shelf_id:
            for label, s_id in self.shelf_choices.items():
                if s_id == location.shelf_id:
                    self.shelf_selector.set(label)
                    break
            self._load_shelf_by_id(location.shelf_id, select_slot=location.placement.slot_name)
        else:
            self.select_slot(location.placement.slot_name)

    def load_selected_shelf(self) -> None:
        label = self.shelf_selector.get()
        shelf_id = self.shelf_choices.get(label)
        if shelf_id is None:
            messagebox.showinfo("Select shelf", "Please select a shelf from the list first.", parent=self)
            return
        self._load_shelf_by_id(shelf_id)

    def _load_shelf_by_id(self, shelf_id: int, select_slot: str | None = None) -> None:
        try:
            grid, contents = load_grid(self.database, shelf_id)
        except Exception as error:
            messagebox.showerror("Error loading shelf", str(error), parent=self)
            return
        self.current_shelf_id = shelf_id
        self.current_contents = contents
        self.shelf_address_lookup.set_address(*grid.key)
        label = next((label for label, choice_id in self.shelf_choices.items() if choice_id == shelf_id), None)
        if label is not None:
            self.shelf_selector.set(label)
        self.shelf_grid.show(grid, selected=self.selected_slot_name, keep_view=False)
        if select_slot and select_slot != self.selected_slot_name:
            self.select_slot(select_slot)
        else:
            self._refresh_slot_contents()

    @property
    def selected_slot_name(self) -> str | None:
        return self.shelf_grid.selected

    def _render_empty_shelf(self, message: str) -> None:
        self.shelf_grid.show_message(message)
        self._refresh_slot_contents()

    def refresh_cell(self, slot_name: str, contents: list[tuple[str, str, Placement]] | None = None) -> None:
        if slot_name not in self.shelf_grid:
            return
        if contents is not None:
            self.current_contents = [item for item in self.current_contents
                                     if item[2].slot_name != slot_name] + list(contents)
        self.shelf_grid.set_count(slot_name, sum(p.slot_name == slot_name for _, _, p in self.current_contents))
        if slot_name == self.selected_slot_name:
            self._refresh_slot_contents()

    def select_slot(self, slot_name: str) -> None:
        self.shelf_grid.select(slot_name)
        self._refresh_slot_contents()

    def _refresh_slot_contents(self) -> None:
        if self.selected_slot_name is None:
            sync_tree_rows(self.contents_tree, [])
            self.slot_header_text.set("No cell selected")
            return

        slot_products = [
            (p_id, p_name, placement.stock_qty)
            for p_id, p_name, placement in self.current_contents
            if placement.slot_name == self.selected_slot_name
        ]
        self.slot_header_text.set(
            f"{self.selected_slot_name} — {len(slot_products)} product{'s' if len(slot_products) != 1 else ''}"
        )
        sync_tree_rows(
            self.contents_tree,
            [
                (
                    f"content::{p_id}",
                    (
                        p_id,
                        p_name,
                        str(stock_qty) if stock_qty is not None else "Unknown",
                    ),
                    (),
                )
                for p_id, p_name, stock_qty in slot_products
            ],
        )

    def on_barcode_scan(self, barcode: str) -> None:
        self._fill_search_bar(normalize_sku(barcode))

    def format_primary_search(self, _event: tk.Event | None = None) -> str:
        if self.barcode_scanner is not None and self.barcode_scanner.is_scanner():
            code = self.barcode_scanner.pop_scanner_code()
            formatted = normalize_sku(code) if code else ""
        else:
            formatted = normalize_sku(self.search_var.get())
        self._fill_search_bar(formatted)
        return "break"

    def focus_search(self) -> None:
        self._select_entry()

"""View for assigning special exceptions, multi-slot products, and staging CSV updates."""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from mapper.core.common import clean_location_segment, make_slot_name, normalize_search
from mapper.persistence.database import SlotAddress, WarehouseDatabase
from utils.barcode_scanner import (
    BarcodeScanner,
    bind_auto_highlight,
    format_product_id,
    select_all_entry_text,
)


class ExceptionsView(ttk.Frame):
    """Tab 6: Special Exceptions, Multi-Location Storage, and CSV Staging."""

    def __init__(
        self,
        parent: tk.Misc,
        database: WarehouseDatabase,
        *,
        status_text: tk.StringVar | None = None,
        on_refresh_callback=None,
        barcode_scanner: BarcodeScanner | None = None,
    ) -> None:
        super().__init__(parent, padding=10)
        self.database = database
        self.status_text = status_text
        self.on_refresh_callback = on_refresh_callback
        self.barcode_scanner = barcode_scanner

        self.selected_address: SlotAddress | None = None
        self.catalog_records: list[tuple[str, str, str]] = []

        # Variables
        self.product_id_var = tk.StringVar(self)
        self.product_name_var = tk.StringVar(self)
        self.catalog_search_var = tk.StringVar(self)
        self.catalog_count_text = tk.StringVar(self, value="0 products")
        self.qty_var = tk.StringVar(self, value="")
        self.floor_var = tk.StringVar(self, value="1")
        self.side_var = tk.StringVar(self, value="1")
        self.shelf_var = tk.StringVar(self, value="A")
        self.row_var = tk.StringVar(self, value="1")
        self.cell_var = tk.StringVar(self, value="1")

        self.loaded_slot_text = tk.StringVar(self, value="No cell loaded. Enter address and click Load cell.")
        self.found_locations_text = tk.StringVar(self, value="Find an ID to see all its saved locations.")
        self.pending_summary_text = tk.StringVar(self, value="0 staged exceptions")
        self.status_message = tk.StringVar(
            self,
            value="Ready. Enter a product ID and load a cell address to assign.",
        )

        self._build_ui()

    def _build_ui(self) -> None:
        # Header bar
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 8))

        sub_header = ttk.Frame(header)
        sub_header.pack(side="left", fill="x", expand=True)

        ttk.Label(
            sub_header,
            text="Special Exceptions & Multi-Location Products",
            style="Heading.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            sub_header,
            text="Find an existing ID and assign it to another cell to keep multiple locations. Register staged products separately.",
            foreground="#555555",
        ).pack(anchor="w")

        right_actions = ttk.Frame(header)
        right_actions.pack(side="right", padx=(8, 0))

        ttk.Label(
            right_actions,
            textvariable=self.pending_summary_text,
            font=("Segoe UI", 9, "bold"),
            foreground="#0969da",
        ).pack(side="left", padx=(0, 10))

        # Main paned workspace
        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left_frame = ttk.Frame(paned)
        right_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=5)
        paned.add(right_frame, weight=5)

        self._build_left_pane(left_frame)
        self._build_right_pane(right_frame)

    def _build_left_pane(self, parent: ttk.Frame) -> None:
        # Top Box: Input and Address Assignment
        assign_box = ttk.LabelFrame(parent, text="Assign Special Exception / Unregistered Product", padding=8)
        assign_box.pack(fill="x", pady=(0, 8))

        # Product ID entry
        id_frame = ttk.Frame(assign_box)
        id_frame.pack(fill="x", pady=(0, 6))
        ttk.Label(id_frame, text="Product ID / Barcode:").pack(side="left", padx=(0, 6))
        self.product_id_entry = ttk.Entry(id_frame, textvariable=self.product_id_var, width=28)
        self.product_id_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.product_id_entry.bind("<Return>", self._on_product_id_return)
        bind_auto_highlight(self.product_id_entry)
        ttk.Button(id_frame, text="Find ID", command=self.find_product).pack(side="left")
        ttk.Label(
            assign_box, textvariable=self.found_locations_text,
            foreground="#0969da", wraplength=470,
        ).pack(anchor="w", pady=(0, 6))

        name_frame = ttk.Frame(assign_box)
        name_frame.pack(fill="x", pady=(0, 6))
        ttk.Label(name_frame, text="Name:").pack(side="left", padx=(0, 6))
        ttk.Entry(name_frame, textvariable=self.product_name_var, width=32).pack(
            side="left", fill="x", expand=True, padx=(0, 6)
        )
        ttk.Button(name_frame, text="Save name", command=self.save_name).pack(side="left")

        # Address selector
        addr_frame = ttk.Frame(assign_box)
        addr_frame.pack(fill="x", pady=(0, 6))

        for label, variable, width, padding in (
            ("Floor:", self.floor_var, 4, 6),
            ("Side:", self.side_var, 4, 6),
            ("Shelf:", self.shelf_var, 5, 6),
            ("Row:", self.row_var, 4, 6),
            ("Cell:", self.cell_var, 4, 8),
        ):
            ttk.Label(addr_frame, text=label).pack(side="left", padx=(0, 2))
            entry = ttk.Entry(addr_frame, textvariable=variable, width=width)
            entry.pack(side="left", padx=(0, padding))
            entry.bind("<Return>", self._on_address_return)

        ttk.Button(addr_frame, text="Load address", command=self.load_address).pack(side="left")

        # Address status label
        ttk.Label(
            assign_box,
            textvariable=self.loaded_slot_text,
            foreground="#0969da",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        # Quantity and Action
        action_frame = ttk.Frame(assign_box)
        action_frame.pack(fill="x")

        ttk.Label(action_frame, text="Stock Qty (optional):").pack(side="left", padx=(0, 4))
        ttk.Entry(action_frame, textvariable=self.qty_var, width=8).pack(side="left", padx=(0, 12))

        ttk.Button(
            action_frame,
            text="Assign to loaded address",
            command=self.assign_exception,
        ).pack(side="left", fill="x", expand=True)

        # Browse every catalog/queue product and IDs stored in several cells.
        product_tabs = ttk.Notebook(parent)
        product_tabs.pack(fill="both", expand=True)
        catalog_box = ttk.Frame(product_tabs, padding=8)
        multi_box = ttk.Frame(product_tabs, padding=8)
        product_tabs.add(catalog_box, text="Full catalog")
        product_tabs.add(multi_box, text="Multiple locations")

        ttk.Label(catalog_box, text="Search code, full name, or shortened name").pack(anchor="w")
        catalog_search_entry = ttk.Entry(catalog_box, textvariable=self.catalog_search_var)
        catalog_search_entry.pack(fill="x", pady=(3, 6))
        bind_auto_highlight(catalog_search_entry)
        self.catalog_search_var.trace_add("write", self._filter_catalog_tree)

        catalog_tree_frame = ttk.Frame(catalog_box)
        catalog_tree_frame.pack(fill="both", expand=True)

        self.catalog_tree = ttk.Treeview(
            catalog_tree_frame,
            columns=("product_id", "product_name"),
            show="headings",
            selectmode="browse",
        )
        self.catalog_tree.heading("product_id", text="Product ID")
        self.catalog_tree.heading("product_name", text="Product Name")

        self.catalog_tree.column("product_id", width=140, anchor="w", stretch=False)
        self.catalog_tree.column("product_name", width=290, anchor="w")

        catalog_scroll = ttk.Scrollbar(catalog_tree_frame, orient="vertical", command=self.catalog_tree.yview)
        self.catalog_tree.configure(yscrollcommand=catalog_scroll.set)
        self.catalog_tree.pack(side="left", fill="both", expand=True)
        catalog_scroll.pack(side="right", fill="y")

        self.catalog_tree.bind("<Double-1>", self._on_catalog_double_click)
        ttk.Label(catalog_box, textvariable=self.catalog_count_text).pack(anchor="w", pady=(4, 0))
        ttk.Label(catalog_box, text="Double-click a product to fill its ID and name.").pack(anchor="w")

        multi_tree_frame = ttk.Frame(multi_box)
        multi_tree_frame.pack(fill="both", expand=True)
        self.multi_location_tree = ttk.Treeview(
            multi_tree_frame, columns=("product_id", "product_name", "locations"),
            show="headings", selectmode="browse",
        )
        for column, title, width in (
            ("product_id", "Product ID", 120),
            ("product_name", "Product Name", 170),
            ("locations", "Saved Locations", 240),
        ):
            self.multi_location_tree.heading(column, text=title)
            self.multi_location_tree.column(column, width=width, anchor="w")
        multi_scroll = ttk.Scrollbar(
            multi_tree_frame, orient="vertical", command=self.multi_location_tree.yview
        )
        self.multi_location_tree.configure(yscrollcommand=multi_scroll.set)
        self.multi_location_tree.pack(side="left", fill="both", expand=True)
        multi_scroll.pack(side="right", fill="y")
        self.multi_location_tree.bind("<<TreeviewSelect>>", self._on_multi_location_select)

    def _build_right_pane(self, parent: ttk.Frame) -> None:
        # Top: Current Shelf / Slot Contents
        slot_box = ttk.LabelFrame(parent, text="Current Loaded Cell Contents", padding=8)
        slot_box.pack(fill="both", expand=True, pady=(0, 8))

        slot_tree_frame = ttk.Frame(slot_box)
        slot_tree_frame.pack(fill="both", expand=True)

        self.cell_contents_tree = ttk.Treeview(
            slot_tree_frame,
            columns=("product_id", "product_name", "stock_qty", "assigned_at"),
            show="headings",
            selectmode="browse",
        )
        self.cell_contents_tree.heading("product_id", text="Product ID")
        self.cell_contents_tree.heading("product_name", text="Product Name")
        self.cell_contents_tree.heading("stock_qty", text="Stock")
        self.cell_contents_tree.heading("assigned_at", text="Assigned Time")

        self.cell_contents_tree.column("product_id", width=130, anchor="w")
        self.cell_contents_tree.column("product_name", width=190, anchor="w")
        self.cell_contents_tree.column("stock_qty", width=60, anchor="e")
        self.cell_contents_tree.column("assigned_at", width=130, anchor="w")

        slot_scroll = ttk.Scrollbar(slot_tree_frame, orient="vertical", command=self.cell_contents_tree.yview)
        self.cell_contents_tree.configure(yscrollcommand=slot_scroll.set)
        self.cell_contents_tree.pack(side="left", fill="both", expand=True)
        slot_scroll.pack(side="right", fill="y")
        self.cell_contents_tree.bind("<<TreeviewSelect>>", self._on_cell_content_select)

        ttk.Button(
            slot_box,
            text="Remove product exception from this cell",
            command=self.remove_from_loaded_cell,
        ).pack(anchor="w", pady=(6, 0))

        # Bottom: persistent exception staging
        pending_box = ttk.LabelFrame(parent, text="Staged Exceptions", padding=8)
        pending_box.pack(fill="both", expand=True)

        stage_actions = ttk.Frame(pending_box)
        stage_actions.pack(fill="x", pady=(0, 6))
        ttk.Button(stage_actions, text="Append back to CSV", command=self.append_to_csv).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(stage_actions, text="Add to catalog", command=self.add_to_catalog).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(stage_actions, text="Wipe from treeview", command=self.wipe_selected).pack(
            side="left"
        )

        pending_tree_frame = ttk.Frame(pending_box)
        pending_tree_frame.pack(fill="both", expand=True)

        self.pending_tree = ttk.Treeview(
            pending_tree_frame,
            columns=("product_id", "product_name", "slot_name", "staged_status", "created_at"),
            show="headings",
            selectmode="browse",
        )
        self.pending_tree.heading("product_id", text="Product ID")
        self.pending_tree.heading("product_name", text="Product Name")
        self.pending_tree.heading("slot_name", text="Locations")
        self.pending_tree.heading("staged_status", text="Staged Status")
        self.pending_tree.heading("created_at", text="Staged At")

        self.pending_tree.column("product_id", width=130, anchor="w")
        self.pending_tree.column("product_name", width=160, anchor="w")
        self.pending_tree.column("slot_name", width=100, anchor="w")
        self.pending_tree.column("staged_status", width=190, anchor="w")
        self.pending_tree.column("created_at", width=130, anchor="w")

        pending_scroll = ttk.Scrollbar(pending_tree_frame, orient="vertical", command=self.pending_tree.yview)
        pending_horizontal = ttk.Scrollbar(pending_box, orient="horizontal", command=self.pending_tree.xview)
        self.pending_tree.configure(
            yscrollcommand=pending_scroll.set,
            xscrollcommand=pending_horizontal.set,
        )
        self.pending_tree.pack(side="left", fill="both", expand=True)
        pending_scroll.pack(side="right", fill="y")
        pending_horizontal.pack(fill="x")
        self.pending_tree.bind("<<TreeviewSelect>>", self._on_staged_select)

        # Note at bottom
        ttk.Label(
            pending_box,
            text="Select a row to update one product; with no selection, registration buttons process all waiting products.",
            font=("Segoe UI", 8),
            foreground="#666666",
        ).pack(anchor="w", pady=(4, 0))

    def _select_entry(self) -> None:
        select_all_entry_text(self.product_id_entry)

    def focus_search(self) -> None:
        self._select_entry()

    def _on_product_id_return(self, _event: tk.Event | None = None) -> str:
        if self.barcode_scanner is not None and self.barcode_scanner.is_scanner():
            code = self.barcode_scanner.pop_scanner_code()
            value = format_product_id(code) if code else ""
        else:
            value = format_product_id(self.product_id_var.get())
        self.product_id_var.set(value)
        self.after_idle(self._select_entry)
        self.assign_exception()
        return "break"

    def _on_barcode_scan(self, scanned_code: str) -> None:
        self.product_id_var.set(format_product_id(scanned_code))
        self.after_idle(self._select_entry)

    def on_barcode_scan(self, scanned_code: str) -> None:
        self._on_barcode_scan(scanned_code)

    def _on_catalog_double_click(self, event: tk.Event) -> str | None:
        item_id = self.catalog_tree.identify_row(event.y)
        if not item_id:
            return None
        values = self.catalog_tree.item(item_id, "values")
        if len(values) < 2:
            return None
        self.catalog_tree.selection_set(item_id)
        self.catalog_tree.focus(item_id)
        self.product_id_var.set(str(values[0]))
        self.product_name_var.set(str(values[1]))
        self.find_product()
        return "break"

    def _on_multi_location_select(self, _event=None) -> None:
        selection = self.multi_location_tree.selection()
        if selection:
            self.product_id_var.set(str(self.multi_location_tree.item(selection[0], "values")[0]))
            self.find_product()

    def _on_staged_select(self, _event=None) -> None:
        selection = self.pending_tree.selection()
        if not selection:
            return
        values = self.pending_tree.item(selection[0], "values")
        if values:
            self.product_id_var.set(str(values[0]))
            self.product_name_var.set(str(values[1]))
            self.find_product()

    def _on_cell_content_select(self, _event=None) -> None:
        selection = self.cell_contents_tree.selection()
        if selection:
            values = self.cell_contents_tree.item(selection[0], "values")
            self.product_id_var.set(str(values[0]))
            self.product_name_var.set(str(values[1]))

    def find_product(self) -> None:
        product_id = format_product_id(self.product_id_var.get().strip())
        self.product_id_var.set(product_id)
        if not product_id:
            self.found_locations_text.set("Enter a product ID to find its saved locations.")
            return
        found = self.database.find_product_locations(product_id)
        if found is None:
            self.found_locations_text.set(f"{product_id} is not registered or assigned locally.")
            return
        name, locations = found
        self.product_name_var.set(name)
        self.qty_var.set("")
        self._show_found_locations(product_id, locations)

    def _show_found_locations(self, product_id: str, locations: tuple[str, ...]) -> None:
        if locations:
            label = "Multiple locations" if len(locations) > 1 else "Saved location"
            self.found_locations_text.set(f"{label} for {product_id}: {', '.join(locations)}")
        else:
            self.found_locations_text.set(f"{product_id} exists locally but has no saved location.")

    def _selected_staged_ids(self) -> list[str] | None:
        selection = self.pending_tree.selection()
        if not selection:
            return None
        return list({str(self.pending_tree.item(iid, "values")[0]) for iid in selection})

    def _refresh_after_change(self) -> None:
        self.refresh()
        if self.on_refresh_callback:
            self.on_refresh_callback()

    def save_name(self) -> None:
        product_id = format_product_id(self.product_id_var.get().strip())
        name = self.product_name_var.get().strip()
        if not product_id or not name:
            messagebox.showinfo("Name required", "Select a staged product and enter its name.", parent=self)
            return
        try:
            self.database.update_staged_exception_name(product_id, name)
        except Exception as error:
            messagebox.showerror("Name update failed", str(error), parent=self)
            return
        self._refresh_after_change()
        if self.status_text:
            self.status_text.set(f"Saved name for {product_id}.")

    def _on_address_return(self, _event: tk.Event | None = None) -> str:
        self.load_address()
        return "break"

    def load_address(self) -> None:
        floor = clean_location_segment(self.floor_var.get())
        side = clean_location_segment(self.side_var.get())
        shelf = clean_location_segment(self.shelf_var.get())
        try:
            row = int(self.row_var.get())
            col = int(self.cell_var.get())
        except ValueError:
            self.selected_address = None
            self.loaded_slot_text.set("No cell loaded. Enter a valid address.")
            self.cell_contents_tree.delete(*self.cell_contents_tree.get_children())
            messagebox.showinfo("Invalid address", "Row and cell must be positive whole numbers.", parent=self)
            return

        slot = self.database.get_slot_address(floor, side, shelf, row, col)
        if not slot:
            slot_name = make_slot_name(floor, shelf, row, col, side=side)
            self.selected_address = None
            self.loaded_slot_text.set(f"No saved cell at {slot_name}.")
            self.cell_contents_tree.delete(*self.cell_contents_tree.get_children())
            return

        self.selected_address = slot
        self.loaded_slot_text.set(f"Loaded: {slot.slot_name}")
        self.refresh_cell_contents()

    def refresh_cell_contents(self) -> None:
        self.cell_contents_tree.delete(*self.cell_contents_tree.get_children())
        if not self.selected_address:
            return

        contents = self.database.get_slot_contents(self.selected_address.slot_id)
        for pid, pname, pl in contents:
            assigned = pl.assigned_at.replace("T", " ") if pl.assigned_at else "Unknown"
            qty_display = "" if pl.stock_qty is None else str(pl.stock_qty)
            self.cell_contents_tree.insert(
                "",
                "end",
                values=(pid, pname, qty_display, assigned),
            )
        self.loaded_slot_text.set(f"Loaded: {self.selected_address.slot_name} · {len(contents)} product(s)")

    def assign_exception(self) -> None:
        raw_id = self.product_id_var.get().strip()
        if not raw_id:
            messagebox.showinfo("Missing Product ID", "Please enter or scan a product ID.", parent=self)
            return

        clean_pid = format_product_id(raw_id)
        if not self.selected_address:
            # Try to load address first
            self.load_address()
            if not self.selected_address:
                messagebox.showinfo(
                    "No Cell Loaded",
                    "Please enter a valid shelf address and load the cell first.",
                    parent=self,
                )
                return

        raw_qty = self.qty_var.get().strip()
        stock_qty = int(raw_qty) if raw_qty and raw_qty.isdigit() else None

        try:
            slot_name = self.database.assign_exception(
                clean_pid,
                self.selected_address.slot_id,
                stock_qty=stock_qty,
                product_name=self.product_name_var.get().strip() or None,
            )
        except Exception as error:
            messagebox.showerror("Assignment Failed", str(error), parent=self)
            return

        msg = f"Assigned {clean_pid} to {slot_name}."
        if self.status_text:
            self.status_text.set(msg)

        # Refresh UI
        self.pending_tree.selection_remove(self.pending_tree.selection())
        self._refresh_after_change()

        # Keep the ID loaded so another address can be added to the same product.
        self.find_product()
        self.product_id_entry.focus_set()

    def remove_from_loaded_cell(self) -> None:
        product_id = format_product_id(self.product_id_var.get().strip())
        if not product_id:
            messagebox.showinfo(
                "Select a product", "Enter a product ID or select a product in the loaded cell.", parent=self
            )
            return
        # Resolve the current address fields so an edited address cannot remove
        # a placement from the previously loaded cell.
        self.load_address()
        if not self.selected_address:
            return
        slot = self.selected_address
        if not messagebox.askyesno(
            "Remove exception from cell",
            f"Remove {product_id} from {slot.slot_name} only?\n\n"
            "Other saved locations, catalog registration, and CSV file will remain.",
            parent=self,
        ):
            return
        try:
            self.database.remove_exception_from_slot(product_id, slot.slot_id)
        except Exception as error:
            messagebox.showerror("Removal failed", str(error), parent=self)
            return
        self._refresh_after_change()
        self.find_product()
        if self.status_text:
            self.status_text.set(f"Removed {product_id} from {slot.slot_name} only.")

    def append_to_csv(self) -> None:
        selected_ids = self._selected_staged_ids()
        pending = [item for item in self.database.get_pending_csv_updates()
                   if selected_ids is None or item["product_id"] in selected_ids]
        if not pending:
            messagebox.showinfo(
                "No Pending Updates",
                "No staged product has a CSV update waiting." if selected_ids is None
                else "The selected product has no CSV update waiting.",
                parent=self,
            )
            return

        selected = filedialog.askopenfilename(
            title="Select CSV file to append exception products",
            filetypes=(
                ("CSV files", "*.csv"),
                ("Text files", "*.txt"),
                ("All files", "*.*"),
            ),
            parent=self,
        )
        if not selected:
            return

        try:
            count = self.database.append_pending_to_csv(Path(selected), selected_ids)
        except Exception as error:
            messagebox.showerror("Append Failed", str(error), parent=self)
            return

        messagebox.showinfo(
            "CSV Updated",
            f"Registered {count:,} exception product(s) in {Path(selected).name}.",
            parent=self,
        )

        self._refresh_after_change()
        if self.status_text:
            self.status_text.set(f"Registered {count} exception(s) in {Path(selected).name}.")

    def add_to_catalog(self) -> None:
        selected_ids = self._selected_staged_ids()
        try:
            count = self.database.add_staged_to_catalog(selected_ids)
        except Exception as error:
            messagebox.showerror("Catalog update failed", str(error), parent=self)
            return
        if not count:
            messagebox.showinfo(
                "No Pending Updates",
                "No staged product has a catalog update waiting." if selected_ids is None
                else "The selected product has no catalog update waiting.",
                parent=self,
            )
            return
        self._refresh_after_change()
        if self.status_text:
            self.status_text.set(f"Added {count} staged product(s) to the full catalog.")

    def wipe_selected(self) -> None:
        selected_ids = self._selected_staged_ids()
        if not selected_ids:
            messagebox.showinfo("Select a product", "Select a staged product to wipe.", parent=self)
            return
        product_id = selected_ids[0]
        confirmed = messagebox.askyesno(
            "Wipe staged product",
            f"Remove {product_id} from this tree and the full catalog, and delete all its saved shelf placements?\n\n"
            "The working product record and CSV file will remain.",
            parent=self,
        )
        if not confirmed:
            return
        try:
            self.database.wipe_staged_exception(product_id)
        except Exception as error:
            messagebox.showerror("Wipe failed", str(error), parent=self)
            return
        self.product_id_var.set("")
        self.product_name_var.set("")
        self._refresh_after_change()
        if self.status_text:
            self.status_text.set(f"Wiped {product_id} from staging, catalog, and saved shelf placements.")

    def refresh_pending_tree(self) -> None:
        selected = set(self.pending_tree.selection())
        self.pending_tree.delete(*self.pending_tree.get_children())
        staged = self.database.get_exception_staging()
        grouped: dict[str, dict] = {}
        for item in staged:
            product_id = item["product_id"]
            if product_id not in grouped:
                grouped[product_id] = {**item, "locations": []}
            group = grouped[product_id]
            if item["slot_name"] not in group["locations"]:
                group["locations"].append(item["slot_name"])
            group["csv_updated"] = group["csv_updated"] and item["csv_updated"]
            group["catalog_updated"] = group["catalog_updated"] and item["catalog_updated"]
        saved_locations: dict[str, list[str]] = {product_id: [] for product_id in grouped}
        for product_id, slot_name, _qty, _assigned_at in self.database.get_all_placement_items():
            if product_id in saved_locations and slot_name not in saved_locations[product_id]:
                saved_locations[product_id].append(slot_name)
        for item in grouped.values():
            created = item["created_at"].replace("T", " ") if item["created_at"] else ""
            missing = []
            if not item["csv_updated"]:
                missing.append("CSV")
            if not item["catalog_updated"]:
                missing.append("catalog")
            status = "Updated" if not missing else "Hasn't Add to: " + " + ".join(missing)
            iid = f"stage-{item['product_id']}"
            self.pending_tree.insert(
                "",
                "end",
                iid=iid,
                values=(item["product_id"], item["product_name"],
                        ", ".join(saved_locations[item["product_id"]] or item["locations"]),
                        status, created),
            )
            if iid in selected:
                self.pending_tree.selection_add(iid)
        self.pending_summary_text.set(f"{len(grouped):,} staged product(s)")

    def refresh_multi_location_tree(self) -> None:
        selected = set(self.multi_location_tree.selection())
        self.multi_location_tree.delete(*self.multi_location_tree.get_children())
        for product_id, name, locations in self.database.get_multi_location_products():
            self.multi_location_tree.insert(
                "", "end", iid=product_id,
                values=(product_id, name, ", ".join(locations)),
            )
            if product_id in selected:
                self.multi_location_tree.selection_add(product_id)

    def refresh_catalog_tree(self) -> None:
        self.catalog_records = self.database.get_display_catalog_products()
        self._filter_catalog_tree()

    def _filter_catalog_tree(self, *_args) -> None:
        selected = set(self.catalog_tree.selection())
        self.catalog_tree.delete(*self.catalog_tree.get_children())
        query = normalize_search(self.catalog_search_var.get())
        shown = 0
        for product_id, name, shortened_name in self.catalog_records:
            if query and query not in normalize_search(f"{product_id} {name} {shortened_name}"):
                continue
            self.catalog_tree.insert("", "end", iid=product_id, values=(product_id, name))
            if product_id in selected:
                self.catalog_tree.selection_add(product_id)
            shown += 1
        self.catalog_count_text.set(f"{shown:,} of {len(self.catalog_records):,} products")

    def refresh(self) -> None:
        """Called whenever tab becomes active or database state changes."""
        self.refresh_catalog_tree()
        self.refresh_pending_tree()
        self.refresh_multi_location_tree()
        product_id = format_product_id(self.product_id_var.get().strip())
        if product_id:
            found = self.database.find_product_locations(product_id)
            if found is not None:
                self._show_found_locations(product_id, found[1])
        if self.selected_address:
            self.refresh_cell_contents()

"""View for assigning special exceptions, multi-slot products, and staging CSV updates."""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from mapper.common import clean_location_segment, make_slot_name
from mapper.database import SlotAddress, WarehouseDatabase
from utils.barcode_scanner import BarcodeScanner, format_product_id


class ExceptionsView(ttk.Frame):
    """Tab 6: Special Exceptions, Multi-Location Storage, and CSV Staging."""

    def __init__(
        self,
        parent: tk.Misc,
        database: WarehouseDatabase,
        *,
        status_text: tk.StringVar | None = None,
        on_refresh_callback=None,
    ) -> None:
        super().__init__(parent, padding=10)
        self.database = database
        self.status_text = status_text
        self.on_refresh_callback = on_refresh_callback

        self.selected_address: SlotAddress | None = None

        # Variables
        self.product_id_var = tk.StringVar(self)
        self.qty_var = tk.StringVar(self, value="")
        self.floor_var = tk.StringVar(self, value="1")
        self.side_var = tk.StringVar(self, value="1")
        self.shelf_var = tk.StringVar(self, value="A")
        self.row_var = tk.StringVar(self, value="1")
        self.cell_var = tk.StringVar(self, value="1")

        self.loaded_slot_text = tk.StringVar(self, value="No cell loaded. Enter address and click Load cell.")
        self.pending_summary_text = tk.StringVar(self, value="0 staged CSV updates")
        self.status_message = tk.StringVar(
            self,
            value="Ready. Enter a product ID and load a cell address to assign.",
        )

        self._build_ui()
        self.barcode_scanner = BarcodeScanner(self, self._on_barcode_scan)

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
            text="Assign items requiring multiple locations or stage unregistered products safely without corrupting CSVs.",
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

        ttk.Button(
            right_actions,
            text="Append back to CSV",
            command=self.append_to_csv,
        ).pack(side="left")

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
        self.product_id_entry.bind("<Return>", lambda e: self.assign_exception())

        # Address selector
        addr_frame = ttk.Frame(assign_box)
        addr_frame.pack(fill="x", pady=(0, 6))

        ttk.Label(addr_frame, text="Floor:").pack(side="left", padx=(0, 2))
        ttk.Entry(addr_frame, textvariable=self.floor_var, width=4).pack(side="left", padx=(0, 6))

        ttk.Label(addr_frame, text="Side:").pack(side="left", padx=(0, 2))
        ttk.Entry(addr_frame, textvariable=self.side_var, width=4).pack(side="left", padx=(0, 6))

        ttk.Label(addr_frame, text="Shelf:").pack(side="left", padx=(0, 2))
        ttk.Entry(addr_frame, textvariable=self.shelf_var, width=5).pack(side="left", padx=(0, 6))

        ttk.Label(addr_frame, text="Row:").pack(side="left", padx=(0, 2))
        ttk.Entry(addr_frame, textvariable=self.row_var, width=4).pack(side="left", padx=(0, 6))

        ttk.Label(addr_frame, text="Cell:").pack(side="left", padx=(0, 2))
        ttk.Entry(addr_frame, textvariable=self.cell_var, width=4).pack(side="left", padx=(0, 8))

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

        # Bottom Box: Shared On-Hand Queue
        on_hand_box = ttk.LabelFrame(parent, text="Shared On-Hand Products", padding=8)
        on_hand_box.pack(fill="both", expand=True)

        on_hand_tree_frame = ttk.Frame(on_hand_box)
        on_hand_tree_frame.pack(fill="both", expand=True)

        self.on_hand_tree = ttk.Treeview(
            on_hand_tree_frame,
            columns=("product_id", "product_name", "stock_qty"),
            show="headings",
            selectmode="browse",
        )
        self.on_hand_tree.heading("product_id", text="Product ID")
        self.on_hand_tree.heading("product_name", text="Product Name")
        self.on_hand_tree.heading("stock_qty", text="Stock Qty")

        self.on_hand_tree.column("product_id", width=140, anchor="w")
        self.on_hand_tree.column("product_name", width=220, anchor="w")
        self.on_hand_tree.column("stock_qty", width=70, anchor="e")

        on_hand_scroll = ttk.Scrollbar(on_hand_tree_frame, orient="vertical", command=self.on_hand_tree.yview)
        self.on_hand_tree.configure(yscrollcommand=on_hand_scroll.set)
        self.on_hand_tree.pack(side="left", fill="both", expand=True)
        on_hand_scroll.pack(side="right", fill="y")

        self.on_hand_tree.bind("<<TreeviewSelect>>", self._on_hand_select)

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

        # Bottom: Pending CSV Updates (Staging Table)
        pending_box = ttk.LabelFrame(parent, text="Wait to Update Back to CSV (Staged)", padding=8)
        pending_box.pack(fill="both", expand=True)

        pending_tree_frame = ttk.Frame(pending_box)
        pending_tree_frame.pack(fill="both", expand=True)

        self.pending_tree = ttk.Treeview(
            pending_tree_frame,
            columns=("product_id", "product_name", "slot_name", "created_at"),
            show="headings",
            selectmode="browse",
        )
        self.pending_tree.heading("product_id", text="Product ID")
        self.pending_tree.heading("product_name", text="Product Name")
        self.pending_tree.heading("slot_name", text="Target Cell")
        self.pending_tree.heading("created_at", text="Staged At")

        self.pending_tree.column("product_id", width=130, anchor="w")
        self.pending_tree.column("product_name", width=160, anchor="w")
        self.pending_tree.column("slot_name", width=100, anchor="w")
        self.pending_tree.column("created_at", width=130, anchor="w")

        pending_scroll = ttk.Scrollbar(pending_tree_frame, orient="vertical", command=self.pending_tree.yview)
        self.pending_tree.configure(yscrollcommand=pending_scroll.set)
        self.pending_tree.pack(side="left", fill="both", expand=True)
        pending_scroll.pack(side="right", fill="y")

        # Note at bottom
        ttk.Label(
            pending_box,
            text="Items staged here will not alter your active CSV files until you click 'Append back to CSV'.",
            font=("Segoe UI", 8),
            foreground="#666666",
        ).pack(anchor="w", pady=(4, 0))

    def _on_barcode_scan(self, scanned_code: str) -> None:
        self.product_id_var.set(format_product_id(scanned_code))
        self.product_id_entry.focus_set()

    def _on_hand_select(self, _event=None) -> None:
        selection = self.on_hand_tree.selection()
        if not selection:
            return
        item = self.on_hand_tree.item(selection[0])
        values = item.get("values", [])
        if values:
            self.product_id_var.set(str(values[0]))
            if len(values) >= 3 and values[2] not in ("", "Unknown", None):
                self.qty_var.set(str(values[2]))

    def load_address(self) -> None:
        floor = clean_location_segment(self.floor_var.get())
        side = clean_location_segment(self.side_var.get())
        shelf = clean_location_segment(self.shelf_var.get())
        try:
            row = int(self.row_var.get())
            col = int(self.cell_var.get())
        except ValueError:
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
            )
        except Exception as error:
            messagebox.showerror("Assignment Failed", str(error), parent=self)
            return

        msg = f"Assigned {clean_pid} to {slot_name}. Staged for CSV update."
        if self.status_text:
            self.status_text.set(msg)

        # Refresh UI
        self.refresh_cell_contents()
        self.refresh_pending_tree()
        self.refresh_on_hand_tree()

        if self.on_refresh_callback:
            self.on_refresh_callback()

        # Clear product ID input for next entry
        self.product_id_var.set("")
        self.product_id_entry.focus_set()

    def append_to_csv(self) -> None:
        pending = self.database.get_pending_csv_updates()
        if not pending:
            messagebox.showinfo("No Pending Updates", "There are no staged exception products waiting to update.", parent=self)
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
            count = self.database.append_pending_to_csv(Path(selected))
        except Exception as error:
            messagebox.showerror("Append Failed", str(error), parent=self)
            return

        messagebox.showinfo(
            "CSV Updated",
            f"Successfully appended {count:,} exception product(s) to {Path(selected).name}.\n"
            f"All appended records are named 'Exc - added later'.",
            parent=self,
        )

        self.refresh_pending_tree()
        if self.status_text:
            self.status_text.set(f"Appended {count} exception(s) to {Path(selected).name}.")

        if self.on_refresh_callback:
            self.on_refresh_callback()

    def refresh_pending_tree(self) -> None:
        self.pending_tree.delete(*self.pending_tree.get_children())
        pending = self.database.get_pending_csv_updates()
        for item in pending:
            created = item["created_at"].replace("T", " ") if item["created_at"] else ""
            self.pending_tree.insert(
                "",
                "end",
                values=(item["product_id"], item["product_name"], item["slot_name"], created),
            )
        self.pending_summary_text.set(f"{len(pending):,} staged CSV update(s)")

    def refresh_on_hand_tree(self) -> None:
        self.on_hand_tree.delete(*self.on_hand_tree.get_children())
        on_hand = self.database.get_on_hand_products()
        products_map = {p[0]: p[1] for p in self.database.get_products()}
        for cid, cname, _ in self.database.get_catalog_products():
            if cid not in products_map:
                products_map[cid] = cname

        for pid, item in on_hand.items():
            pname = products_map.get(pid, pid)
            qty_display = "" if item.stock_qty is None else str(item.stock_qty)
            self.on_hand_tree.insert(
                "",
                "end",
                values=(pid, pname, qty_display),
            )

    def refresh(self) -> None:
        """Called whenever tab becomes active or database state changes."""
        self.refresh_on_hand_tree()
        self.refresh_pending_tree()
        if self.selected_address:
            self.refresh_cell_contents()

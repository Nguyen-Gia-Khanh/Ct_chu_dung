"""Product queue, clickable shelf front view, and selected-slot contents."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .common import make_slot_name
from .database import validate_stock_quantity
from .widgets import ScrollableFrame

from utils.barcode_scanner import BarcodeScanner

class StockQuantityDialog(tk.Toplevel):
    """Collect a separate manual quantity for every selected product."""

    def __init__(
        self,
        parent: tk.Misc,
        slot_name: str,
        products: list[tuple[str, str]],
        initial_quantities: dict[str, int | None] | None = None,
        *,
        title_text: str | None = None,
        destination_label: str | None = None,
        button_text: str = "Assign products",
    ):
        super().__init__(parent)
        self.result: dict[str, int] | None = None
        self.quantity_inputs: dict[str, tuple[tk.StringVar, ttk.Entry]] = {}
        self.title(title_text or f"Assign products to {slot_name}")
        self.transient(parent)
        self.geometry(f"660x{min(540, 200 + 36 * len(products))}")
        self.minsize(520, 230)

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=destination_label or f"Destination: {slot_name}").pack(anchor="w")
        ttk.Label(
            body, text="Enter each product's stock quantity (whole units, 0 or more).",
            wraplength=590,
        ).pack(anchor="w", pady=(4, 10))
        rows = ScrollableFrame(body)
        rows.pack(fill="both", expand=True)
        rows.inner.columnconfigure(1, weight=1)
        for column, heading in enumerate(("Product ID", "Product name", "Stock qty")):
            ttk.Label(rows.inner, text=heading).grid(row=0, column=column, sticky="w", padx=5, pady=5)
        for row_number, (product_id, product_name) in enumerate(products, start=1):
            ttk.Label(rows.inner, text=product_id, wraplength=140).grid(
                row=row_number, column=0, sticky="w", padx=5, pady=5,
            )
            ttk.Label(rows.inner, text=product_name, wraplength=300).grid(
                row=row_number, column=1, sticky="w", padx=5, pady=5,
            )
            init_val = ""
            if initial_quantities and product_id in initial_quantities:
                qty = initial_quantities[product_id]
                if qty is not None:
                    init_val = str(qty)
            quantity = tk.StringVar(self, value=init_val)
            entry = ttk.Entry(rows.inner, textvariable=quantity, width=12)
            entry.grid(row=row_number, column=2, sticky="e", padx=5, pady=5)
            self.quantity_inputs[product_id] = (quantity, entry)

        ttk.Label(
            body, text="Press Commit on the main window to save staged changes.",
            wraplength=590,
        ).pack(anchor="w", pady=(10, 8))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        ttk.Button(buttons, text=button_text, command=self.confirm).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(0, 8))
        self.bind("<Return>", self.confirm)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_visibility()
        self.grab_set()
        if self.quantity_inputs:
            next(iter(self.quantity_inputs.values()))[1].focus_set()

    def confirm(self, _event=None) -> None:
        quantities = {}
        for product_id, (variable, entry) in self.quantity_inputs.items():
            try:
                text = variable.get().strip()
                if not text.isascii() or not text.isdecimal():
                    raise ValueError("Enter a whole number of units (0 or more).")
                quantity = int(text)
                validate_stock_quantity(quantity)
            except ValueError as error:
                messagebox.showerror("Invalid stock quantity", f"{product_id}: {error}", parent=self)
                entry.focus_set()
                entry.selection_range(0, "end")
                return
            quantities[product_id] = quantity
        self.result = quantities
        self.destroy()


class AssignmentView(ttk.Frame):
    def __init__(
        self,
        parent,
        on_search,
        on_assign,
        on_return,
        on_select,
        *,
        read_only=False,
        on_upload=None,
        on_modify_stock=None,
        on_transfer=None,
        on_preassign_stock=None,
    ):
        super().__init__(parent, padding=10)
        self.read_only = read_only
        self.on_select = on_select
        self.selected_slot = None
        self.slot_buttons: dict[str, tk.Button] = {}
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 8))
        self.active_shelf_text = tk.StringVar(value="No shelf built yet")
        ttk.Label(header, textvariable=self.active_shelf_text, style="Heading.TLabel").pack(side="left")
        self.change_summary_text = tk.StringVar(value="0 staged changes")
        ttk.Label(header, textvariable=self.change_summary_text).pack(side="right")

        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True)

        queue_panel = ttk.LabelFrame(
            pane, text="All imported products" if read_only else "Unassigned product queue", padding=8,
        )
        shelf_panel = ttk.LabelFrame(
            pane, text="Saved shelf — click a slot to view" if read_only else "2D shelf — click a slot", padding=8,
        )
        details_panel = ttk.LabelFrame(pane, text="Selected slot contents", padding=8, width=360, height=450)
        # Wide timestamp columns scroll inside this pane instead of squeezing
        # the shelf drawing out of the window.
        details_panel.grid_propagate(False)
        pane.add(queue_panel, weight=3)
        pane.add(shelf_panel, weight=6)
        pane.add(details_panel, weight=3)

        queue_panel.rowconfigure(2, weight=1)
        queue_panel.columnconfigure(0, weight=1)
        
        ttk.Label(queue_panel, text="Search ID or product name").grid(
            row=0, column=0, sticky="w"
        )

        self.search_var = tk.StringVar()

        self.search_entry = ttk.Entry(
            queue_panel,
            textvariable=self.search_var
        )
        self.search_entry.grid(
            row=1, column=0, sticky="ew", pady=(3, 6)
        )

        self.search_var.trace_add("write", on_search)

        self.barcode_scanner = BarcodeScanner(
            self,
            self.on_barcode_scan
        )

        queue_body = ttk.Frame(queue_panel)
        queue_body.grid(row=2, column=0, sticky="nsew")
        queue_body.rowconfigure(0, weight=1)
        queue_body.columnconfigure(0, weight=1)

        self.queue_tree = ttk.Treeview(
            queue_body,
            columns=("product_id", "product_name", "stock_qty"),
            show="headings",
            selectmode="browse" if read_only else "extended",
            height=18,
        )
        self.queue_tree.heading("product_id", text="Product ID")
        self.queue_tree.heading("product_name", text="Product name")
        self.queue_tree.heading("stock_qty", text="Stock")
        self.queue_tree.column("product_id", width=105, minwidth=75, stretch=False)
        self.queue_tree.column("product_name", width=195, minwidth=110)
        self.queue_tree.column("stock_qty", width=65, minwidth=45, anchor="e", stretch=False)
        self.queue_tree.tag_configure("transferred", background="#fff2a8")
        if not read_only and on_preassign_stock is not None:
            self.queue_tree.bind("<Double-1>", lambda _e: on_preassign_stock())
        queue_scroll = ttk.Scrollbar(queue_body, orient="vertical", command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=queue_scroll.set)
        self.queue_tree.grid(row=0, column=0, sticky="nsew")
        queue_scroll.grid(row=0, column=1, sticky="ns")

        queue_footer = ttk.Frame(queue_panel)
        queue_footer.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.queue_count_text = tk.StringVar(value="0 products")
        ttk.Label(queue_footer, textvariable=self.queue_count_text).pack(anchor="w")
        if not read_only and on_preassign_stock is not None:
            self.preassign_stock_button = ttk.Button(
                queue_footer,
                text="Pre-assign selected stock",
                command=on_preassign_stock,
            )
            self.preassign_stock_button.pack(fill="x", pady=(5, 0))
        ttk.Button(
            queue_footer,
            text="Find saved location →" if read_only else "Assign selected to clicked slot →",
            command=on_assign,
        ).pack(fill="x", pady=(5, 0))

        self.shelf_scroll = ScrollableFrame(shelf_panel, horizontal=True, vertical=True)
        self.shelf_scroll.pack(fill="both", expand=True)

        self.selected_slot_text = tk.StringVar(value="No slot selected")
        details_panel.rowconfigure(1, weight=1)
        details_panel.columnconfigure(0, weight=1)
        ttk.Label(details_panel, textvariable=self.selected_slot_text, style="Heading.TLabel", wraplength=230).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        details_body = ttk.Frame(details_panel)
        details_body.grid(row=1, column=0, sticky="nsew")
        details_body.rowconfigure(0, weight=1)
        details_body.columnconfigure(0, weight=1)
        self.contents_tree = ttk.Treeview(
            details_body,
            columns=("product_id", "product_name", "stock_qty", "assigned_at", "state"),
            show="headings",
            selectmode="extended",
            height=18,
        )
        self.contents_tree.heading("product_id", text="Product ID")
        self.contents_tree.heading("product_name", text="Product name")
        self.contents_tree.heading("stock_qty", text="Stock qty")
        self.contents_tree.heading("assigned_at", text="Added to shelf")
        self.contents_tree.heading("state", text="State")
        self.contents_tree.column("product_id", width=95, minwidth=70, stretch=False)
        self.contents_tree.column("product_name", width=160, minwidth=100)
        self.contents_tree.column("stock_qty", width=80, minwidth=70, anchor="e", stretch=False)
        self.contents_tree.column("assigned_at", width=240, minwidth=200, stretch=False)
        self.contents_tree.column("state", width=58, minwidth=50, stretch=False)
        contents_scroll = ttk.Scrollbar(details_body, orient="vertical", command=self.contents_tree.yview)
        contents_x_scroll = ttk.Scrollbar(details_body, orient="horizontal", command=self.contents_tree.xview)
        self.contents_tree.configure(yscrollcommand=contents_scroll.set, xscrollcommand=contents_x_scroll.set)
        self.contents_tree.grid(row=0, column=0, sticky="nsew")
        contents_scroll.grid(row=0, column=1, sticky="ns")
        contents_x_scroll.grid(row=1, column=0, sticky="ew")

        details_footer = ttk.Frame(details_panel)
        details_footer.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        if not read_only:
            stock_buttons = ttk.Frame(details_footer)
            stock_buttons.pack(fill="x")
            stock_buttons.columnconfigure(0, weight=1)
            stock_buttons.columnconfigure(1, weight=1)

            self.modify_stock_button = ttk.Button(
                stock_buttons,
                text="Modify selected stock",
                command=on_modify_stock,
                state="normal" if on_modify_stock is not None else "disabled",
            )
            self.modify_stock_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))

            self.transfer_button = ttk.Button(
                stock_buttons,
                text="Transfer product",
                command=on_transfer,
                state="normal" if on_transfer is not None else "disabled",
            )
            self.transfer_button.grid(row=0, column=1, sticky="ew")

            ttk.Button(
                details_footer,
                text="Return selected products to queue",
                command=on_return,
            ).pack(fill="x", pady=(6, 0))
            self.upload_button = ttk.Button(
                details_footer, text="Upload to web", command=on_upload,
                state="normal" if on_upload is not None else "disabled",
            )
            self.upload_button.pack(fill="x", pady=(6, 0))

            self.upload_status_text = tk.StringVar(value="")
            ttk.Label(
                details_footer, textvariable=self.upload_status_text, wraplength=300,
            ).pack(anchor="w", pady=(5, 0))
        ttk.Label(
            details_footer,
            text="Blue = searched product's slot; green = occupied" if read_only else "Yellow = staged; green = already saved",
            foreground="#555555",
        ).pack(anchor="w", pady=(6, 0))

    def on_barcode_scan(self, barcode):
        self.search_var.set(barcode)

    def render_shelf(
        self, floor: str, shelf_code: str, layout: list[int],
        slot_counts: dict[str, tuple[int, int]], selected_slot: str | None,
        *, side: str = "1",
    ) -> None:
        self.selected_slot = selected_slot
        self.selected_slot_text.set(selected_slot or "No slot selected")
        for child in self.shelf_scroll.inner.winfo_children():
            child.destroy()
        self.slot_buttons.clear()

        if not layout:
            ttk.Label(
                self.shelf_scroll.inner,
                text="Choose a product with a saved location." if getattr(self, "read_only", False)
                else "Build or load a shelf from the Shelf Designer tab.",
            ).pack(padx=30, pady=30)
            return

        row_width = max(400, max(layout) * 88)

        title = ttk.Label(
            self.shelf_scroll.inner,
            text=f"FLOOR {floor.upper()}  —  SIDE {side.upper()}  —  SHELF {shelf_code.upper()}",
            style="Title.TLabel",
        )
        title.grid(row=0, column=0, columnspan=2, pady=(10, 14))

        ttk.Label(self.shelf_scroll.inner, text="CELLS — numbered across each row", style="Heading.TLabel").grid(
            row=1, column=1, pady=(0, 5)
        )

        for row_number, count in enumerate(layout, start=1):
            screen_row = len(layout) - row_number + 2
            ttk.Label(self.shelf_scroll.inner, text=f"Row {row_number}" + (" — ground" if row_number == 1 else ""), style="Heading.TLabel").grid(
                row=screen_row, column=0, padx=(8, 10), sticky="e"
            )

            row_frame = tk.Frame(
                self.shelf_scroll.inner,
                width=row_width,
                height=72,
                background="#d0d0d0",
                borderwidth=1,
                relief="solid",
            )
            row_frame.grid(row=screen_row, column=1, sticky="nsew", pady=2)
            row_frame.grid_propagate(False)
            row_frame.rowconfigure(0, weight=1)
            for slot_index in range(1, count + 1):
                row_frame.columnconfigure(slot_index - 1, weight=1, uniform=f"r{row_number}")
                slot_name = make_slot_name(floor, shelf_code, row_number, slot_index, side=side)
                saved_count, staged_count = slot_counts.get(slot_name, (0, 0))
                total_count = saved_count + staged_count
                if staged_count:
                    background = "#fff2b2"
                elif saved_count:
                    background = "#d9ead3"
                else:
                    background = "#f7f7f7"
                selected = slot_name == self.selected_slot
                button = tk.Button(
                    row_frame,
                    text=f"R{row_number}-C{slot_index:02d}\n{total_count} product{'s' if total_count != 1 else ''}",
                    command=lambda name=slot_name: self.on_select(name),
                    background=background,
                    activebackground="#cfe8ff",
                    relief="solid",
                    borderwidth=3 if selected else 1,
                    highlightthickness=0,
                    font=("Segoe UI", 9, "bold" if selected else "normal"),
                )
                button.grid(row=0, column=slot_index - 1, sticky="nsew", padx=1, pady=1)
                self.slot_buttons[slot_name] = button

        ttk.Separator(self.shelf_scroll.inner).grid(
            row=len(layout) + 2, column=0, columnspan=2, sticky="ew", pady=(10, 2)
        )
        ttk.Label(self.shelf_scroll.inner, text="Ground", foreground="#555555").grid(
            row=len(layout) + 3, column=0, columnspan=2, sticky="w", padx=8
        )
        self.shelf_scroll.inner.update_idletasks()
        self.shelf_scroll.canvas.configure(scrollregion=self.shelf_scroll.canvas.bbox("all"))

    def mark_selected(self, slot_name: str) -> None:
        old_slot = self.selected_slot
        self.selected_slot = slot_name
        for name in (old_slot, slot_name):
            if name and name in self.slot_buttons:
                selected = name == slot_name
                self.slot_buttons[name].configure(
                    borderwidth=3 if selected else 1,
                    font=("Segoe UI", 9, "bold" if selected else "normal"),
                )
        self.selected_slot_text.set(slot_name)

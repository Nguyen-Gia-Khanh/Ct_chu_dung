"""Address-first product assignment UI with a persistent on-hand batch."""

from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import ttk

from utils.barcode_scanner import BarcodeScanner, format_product_id


class LocationAssignmentView(ttk.Frame):
    """Tab 2: search products, prepare a batch, then move it by address."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_search: Callable[..., object],
        on_queue_to_hand: Callable[[], object],
        on_catalog_to_queue: Callable[[], object],
        on_catalog_activate: Callable[[tk.Event], object],
        on_load_address: Callable[[], object],
        on_assign_address: Callable[[], object],
        on_dequeue_hand: Callable[[], object],
        on_selected_to_hand: Callable[[], object],
        on_slot_to_hand: Callable[[], object],
        on_modify_hand_stock: Callable[[], object],
        on_modify_stock: Callable[[], object],
        on_upload: Callable[[], object],
        on_modify_location: Callable[[], object],
        on_connect_chrome: Callable[[], object],
    ):
        super().__init__(parent, padding=10)

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(
            header,
            text="Build a persistent on-hand batch, then assign it to one exact shelf address.",
            style="Heading.TLabel",
        ).pack(side="left")
        self.connect_chrome_button = ttk.Button(
            header,
            text="Connect Chrome",
            command=on_connect_chrome,
        )
        self.connect_chrome_button.pack(side="right")

        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True)

        products_panel = ttk.LabelFrame(pane, text="Products", padding=8)
        hand_panel = ttk.LabelFrame(
            pane, text="On-hand queue and shelf address", padding=8
        )
        contents_panel = ttk.LabelFrame(pane, text="Loaded address contents", padding=8)
        pane.add(products_panel, weight=4)
        pane.add(hand_panel, weight=3)
        pane.add(contents_panel, weight=3)

        self._build_products_panel(
            products_panel,
            on_search,
            on_queue_to_hand,
            on_catalog_to_queue,
            on_catalog_activate,
        )
        self._build_hand_panel(
            hand_panel,
            on_load_address,
            on_assign_address,
            on_dequeue_hand,
            on_modify_hand_stock,
        )
        self._build_contents_panel(
            contents_panel,
            on_selected_to_hand,
            on_slot_to_hand,
            on_modify_stock,
            on_upload,
            on_modify_location,
        )
        self.barcode_scanner = BarcodeScanner(self, self.on_barcode_scan)

    def _build_products_panel(
        self,
        parent: ttk.LabelFrame,
        on_search: Callable[..., object],
        on_queue_to_hand: Callable[[], object],
        on_catalog_to_queue: Callable[[], object],
        on_catalog_activate: Callable[[tk.Event], object],
    ) -> None:
        split = ttk.Panedwindow(parent, orient="vertical")
        split.pack(fill="both", expand=True)
        queue = ttk.LabelFrame(split, text="Total unassigned product queue", padding=6)
        catalog = ttk.LabelFrame(split, text="Full product catalog", padding=6)
        split.add(queue, weight=1)
        split.add(catalog, weight=1)

        queue.rowconfigure(3, weight=1)
        queue.columnconfigure(0, weight=1)
        ttk.Label(queue, text="Search code, full name, or shortened name").grid(
            row=0, column=0, sticky="w"
        )
        self.search_var = tk.StringVar(self)
        self.search_entry = ttk.Entry(queue, textvariable=self.search_var)
        self.search_entry.grid(row=1, column=0, sticky="ew", pady=(3, 4))
        self.search_entry.bind("<Return>", self.format_primary_search)
        self.search_var.trace_add("write", on_search)
        self.search_location_text = tk.StringVar(self, value="")
        self.search_location_label = ttk.Label(
            queue,
            textvariable=self.search_location_text,
            foreground="#555555",
            wraplength=430,
        )
        self.search_location_label.grid(row=2, column=0, sticky="w", pady=(0, 5))

        queue_body = ttk.Frame(queue)
        queue_body.grid(row=3, column=0, sticky="nsew")
        queue_body.rowconfigure(0, weight=1)
        queue_body.columnconfigure(0, weight=1)
        self.queue_tree = ttk.Treeview(
            queue_body,
            columns=("product_id", "product_name", "stock_qty"),
            show="headings",
            selectmode="extended",
            height=8,
        )
        self._configure_queue_tree(self.queue_tree)
        self.queue_tree.tag_configure(
            "returned",
            background="#fff2a8",
            font=("Segoe UI", 9, "bold"),
        )
        queue_scroll = ttk.Scrollbar(
            queue_body, orient="vertical", command=self.queue_tree.yview
        )
        queue_x_scroll = ttk.Scrollbar(
            queue_body, orient="horizontal", command=self.queue_tree.xview
        )
        self.queue_tree.configure(
            yscrollcommand=queue_scroll.set,
            xscrollcommand=queue_x_scroll.set,
        )
        self.queue_tree.grid(row=0, column=0, sticky="nsew")
        queue_scroll.grid(row=0, column=1, sticky="ns")
        queue_x_scroll.grid(row=1, column=0, sticky="ew")
        self.queue_count_text = tk.StringVar(self, value="0 products")
        ttk.Label(queue, textvariable=self.queue_count_text).grid(
            row=4, column=0, sticky="w", pady=(5, 0)
        )
        ttk.Button(
            queue,
            text="Move selected → on-hand",
            command=on_queue_to_hand,
        ).grid(row=5, column=0, sticky="ew", pady=(5, 0))

        catalog.rowconfigure(0, weight=1)
        catalog.columnconfigure(0, weight=1)
        catalog_body = ttk.Frame(catalog)
        catalog_body.grid(row=0, column=0, sticky="nsew")
        catalog_body.rowconfigure(0, weight=1)
        catalog_body.columnconfigure(0, weight=1)
        self.catalog_tree = ttk.Treeview(
            catalog_body,
            columns=("product_id", "product_name", "shortened_name"),
            show="headings",
            selectmode="extended",
            height=8,
        )
        self._configure_product_tree(self.catalog_tree)
        catalog_scroll = ttk.Scrollbar(
            catalog_body, orient="vertical", command=self.catalog_tree.yview
        )
        catalog_x_scroll = ttk.Scrollbar(
            catalog_body, orient="horizontal", command=self.catalog_tree.xview
        )
        self.catalog_tree.configure(
            yscrollcommand=catalog_scroll.set,
            xscrollcommand=catalog_x_scroll.set,
        )
        self.catalog_tree.grid(row=0, column=0, sticky="nsew")
        catalog_scroll.grid(row=0, column=1, sticky="ns")
        catalog_x_scroll.grid(row=1, column=0, sticky="ew")
        self.catalog_tree.bind("<Double-1>", on_catalog_activate)
        self.catalog_count_text = tk.StringVar(self, value="0 products")
        ttk.Label(catalog, textvariable=self.catalog_count_text).grid(
            row=1, column=0, sticky="w", pady=(5, 0)
        )
        ttk.Button(
            catalog,
            text="Transfer selected to total queue",
            command=on_catalog_to_queue,
        ).grid(row=2, column=0, sticky="ew", pady=(5, 0))

    @staticmethod
    def _configure_product_tree(tree: ttk.Treeview) -> None:
        tree.heading("product_id", text="Product ID")
        tree.heading("product_name", text="Product name")
        tree.heading("shortened_name", text="Shortened name")
        tree.column("product_id", width=110, minwidth=80, stretch=False)
        tree.column("product_name", width=190, minwidth=110)
        tree.column("shortened_name", width=145, minwidth=95)

    @staticmethod
    def _configure_queue_tree(tree: ttk.Treeview) -> None:
        tree.heading("product_id", text="Product ID")
        tree.heading("product_name", text="Product name")
        tree.heading("stock_qty", text="Stock")
        tree.column("product_id", width=110, minwidth=80, stretch=False)
        tree.column("product_name", width=190, minwidth=110)
        tree.column("stock_qty", width=65, minwidth=50, anchor="e", stretch=False)

    def _build_hand_panel(
        self,
        parent: ttk.LabelFrame,
        on_load_address: Callable[[], object],
        on_assign_address: Callable[[], object],
        on_dequeue_hand: Callable[[], object],
        on_modify_hand_stock: Callable[[], object],
    ) -> None:
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        body = ttk.Frame(parent)
        body.grid(row=0, column=0, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self.on_hand_tree = ttk.Treeview(
            body,
            columns=("product_id", "product_name", "stock_qty"),
            show="headings",
            selectmode="extended",
            height=13,
        )
        self.on_hand_tree.heading("product_id", text="Product ID")
        self.on_hand_tree.heading("product_name", text="Product name")
        self.on_hand_tree.heading("stock_qty", text="Stock")
        self.on_hand_tree.column("product_id", width=110, minwidth=80, stretch=False)
        self.on_hand_tree.column("product_name", width=180, minwidth=100)
        self.on_hand_tree.column(
            "stock_qty", width=65, minwidth=50, anchor="e", stretch=False
        )
        hand_scroll = ttk.Scrollbar(
            body, orient="vertical", command=self.on_hand_tree.yview
        )
        hand_x_scroll = ttk.Scrollbar(
            body, orient="horizontal", command=self.on_hand_tree.xview
        )
        self.on_hand_tree.configure(
            yscrollcommand=hand_scroll.set,
            xscrollcommand=hand_x_scroll.set,
        )
        self.on_hand_tree.grid(row=0, column=0, sticky="nsew")
        hand_scroll.grid(row=0, column=1, sticky="ns")
        hand_x_scroll.grid(row=1, column=0, sticky="ew")

        self.on_hand_count_text = tk.StringVar(self, value="0 products ready to assign")
        ttk.Label(parent, textvariable=self.on_hand_count_text).grid(
            row=1, column=0, sticky="w", pady=(5, 0)
        )
        hand_actions = ttk.Frame(parent)
        hand_actions.grid(row=2, column=0, sticky="ew", pady=(5, 8))
        hand_actions.columnconfigure(0, weight=1)
        hand_actions.columnconfigure(1, weight=1)
        ttk.Button(
            hand_actions,
            text="Edit selected quantity",
            command=on_modify_hand_stock,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(
            hand_actions,
            text="Dequeue selected → total queue",
            command=on_dequeue_hand,
        ).grid(row=0, column=1, sticky="ew", padx=(3, 0))

        address = ttk.LabelFrame(parent, text="Shelf address", padding=8)
        address.grid(row=3, column=0, sticky="ew")
        labels = ("Floor", "Side", "Shelf", "Row", "Col / cell")
        self.floor_var = tk.StringVar(self)
        self.side_var = tk.StringVar(self, value="1")
        self.shelf_var = tk.StringVar(self)
        self.row_var = tk.StringVar(self)
        self.cell_var = tk.StringVar(self)
        variables = (
            self.floor_var,
            self.side_var,
            self.shelf_var,
            self.row_var,
            self.cell_var,
        )
        for column, (label, variable) in enumerate(zip(labels, variables)):
            address.columnconfigure(column, weight=1)
            ttk.Label(address, text=label).grid(
                row=0, column=column, sticky="w", padx=2
            )
            entry = ttk.Entry(address, textvariable=variable, width=7)
            entry.grid(row=1, column=column, sticky="ew", padx=2, pady=(2, 6))
            entry.bind("<Return>", lambda _event: on_load_address())
        ttk.Button(address, text="Load address →", command=on_load_address).grid(
            row=2, column=0, columnspan=5, sticky="ew", padx=2
        )
        ttk.Button(
            address,
            text="Assign selected on-hand → loaded address",
            command=on_assign_address,
            style="Commit.TButton",
        ).grid(row=3, column=0, columnspan=5, sticky="ew", padx=2, pady=(6, 0))
        self.address_status_text = tk.StringVar(
            self, value="Enter an existing shelf address and load it."
        )
        ttk.Label(
            address,
            textvariable=self.address_status_text,
            wraplength=370,
            foreground="#555555",
        ).grid(row=4, column=0, columnspan=5, sticky="w", padx=2, pady=(6, 0))

    def _build_contents_panel(
        self,
        parent: ttk.LabelFrame,
        on_selected_to_hand: Callable[[], object],
        on_slot_to_hand: Callable[[], object],
        on_modify_stock: Callable[[], object],
        on_upload: Callable[[], object],
        on_modify_location: Callable[[], object],
    ) -> None:
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)
        self.selected_slot_text = tk.StringVar(self, value="No address loaded")
        ttk.Label(
            parent,
            textvariable=self.selected_slot_text,
            style="Heading.TLabel",
            wraplength=390,
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        body = ttk.Frame(parent)
        body.grid(row=1, column=0, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self.contents_tree = ttk.Treeview(
            body,
            columns=("product_id", "product_name", "stock_qty", "assigned_at"),
            show="headings",
            selectmode="extended",
            height=18,
        )
        self.contents_tree.heading("product_id", text="Product ID")
        self.contents_tree.heading("product_name", text="Product name")
        self.contents_tree.heading("stock_qty", text="Stock")
        self.contents_tree.heading("assigned_at", text="Added to shelf")
        self.contents_tree.column("product_id", width=110, minwidth=80, stretch=False)
        self.contents_tree.column("product_name", width=180, minwidth=100)
        self.contents_tree.column(
            "stock_qty", width=60, minwidth=45, anchor="e", stretch=False
        )
        self.contents_tree.column("assigned_at", width=205, minwidth=160, stretch=False)
        contents_scroll = ttk.Scrollbar(
            body, orient="vertical", command=self.contents_tree.yview
        )
        contents_x_scroll = ttk.Scrollbar(
            body, orient="horizontal", command=self.contents_tree.xview
        )
        self.contents_tree.configure(
            yscrollcommand=contents_scroll.set,
            xscrollcommand=contents_x_scroll.set,
        )
        self.contents_tree.grid(row=0, column=0, sticky="nsew")
        contents_scroll.grid(row=0, column=1, sticky="ns")
        contents_x_scroll.grid(row=1, column=0, sticky="ew")
        self.contents_tree.bind("<Double-1>", self.copy_product_id)

        footer = ttk.Frame(parent)
        footer.grid(row=2, column=0, sticky="ew", pady=(7, 0))
        footer.columnconfigure(0, weight=1)
        footer.columnconfigure(1, weight=1)
        ttk.Button(
            footer,
            text="Modify selected stock",
            command=on_modify_stock,
        ).grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Button(
            footer,
            text="Selected product(s) → on-hand",
            command=on_selected_to_hand,
        ).grid(row=1, column=0, sticky="ew", padx=(0, 3), pady=(6, 0))
        ttk.Button(
            footer,
            text="Shelf → on-hand (all)",
            command=on_slot_to_hand,
        ).grid(row=1, column=1, sticky="ew", padx=(3, 0), pady=(6, 0))

        self.web_batch_mode_var = tk.BooleanVar(self, value=False)
        self.web_batch_mode_check = ttk.Checkbutton(
            footer,
            text="Process and save all products in loaded address",
            variable=self.web_batch_mode_var,
            command=self._refresh_web_action_labels,
        )
        self.web_batch_mode_check.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(7, 0),
        )
        web_buttons = ttk.Frame(footer)
        web_buttons.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        web_buttons.columnconfigure(0, weight=1)
        web_buttons.columnconfigure(1, weight=1)
        self.modify_location_button = ttk.Button(
            web_buttons,
            command=on_modify_location,
        )
        self.modify_location_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.upload_button = ttk.Button(
            web_buttons,
            command=on_upload,
        )
        self.upload_button.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        self._refresh_web_action_labels()
        # Preserve the current temporary behavior: location-only web updates are enabled.
        self.upload_button.grid_remove()
        self.modify_location_button.grid_configure(columnspan=2, padx=0)
        self.upload_status_text = tk.StringVar(self, value="")
        ttk.Label(footer, textvariable=self.upload_status_text, wraplength=390).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(5, 0)
        )
        self.copy_status_text = tk.StringVar(
            self, value="Double-click a row to copy its Product ID."
        )
        ttk.Label(
            footer,
            textvariable=self.copy_status_text,
            foreground="#555555",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(5, 0))

    def _refresh_web_action_labels(self) -> None:
        """Make the active single/all-products scope visible on both web buttons."""
        if self.web_batch_mode_var.get():
            self.modify_location_button.configure(
                text="Modify all products' web location"
            )
            self.upload_button.configure(text="Upload all products to web")
        else:
            self.modify_location_button.configure(
                text="Modify selected product's web location"
            )
            self.upload_button.configure(text="Upload selected product to web")

    def on_barcode_scan(self, barcode: str) -> None:
        self._set_and_select_search(self.search_var, self.search_entry, barcode)

    def format_primary_search(self, _event=None) -> str:
        self._set_and_select_search(
            self.search_var,
            self.search_entry,
            format_product_id(self.search_var.get()),
        )
        return "break"

    def _set_and_select_search(
        self,
        variable: tk.StringVar,
        entry: ttk.Entry,
        value: str,
    ) -> None:
        variable.set(value)
        self.after_idle(lambda: self._select_search_entry(entry))

    @staticmethod
    def _select_search_entry(entry: ttk.Entry) -> None:
        entry.focus_set()
        entry.selection_range(0, tk.END)
        entry.icursor(tk.END)

    def copy_product_id(self, event: tk.Event) -> str | None:
        row_id = self.contents_tree.identify_row(event.y)
        if not row_id:
            return None
        values = self.contents_tree.item(row_id, "values")
        if not values:
            return None
        product_id = str(values[0]).strip()
        if not product_id:
            return None
        self.contents_tree.selection_set(row_id)
        self.contents_tree.focus(row_id)
        self.clipboard_clear()
        self.clipboard_append(product_id)
        self.update_idletasks()
        self.copy_status_text.set(f"Copied {product_id}")
        return "break"

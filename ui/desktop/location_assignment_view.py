"""Address-first product assignment UI with a persistent on-hand batch."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
import tkinter as tk
from tkinter import ttk

from mapper.core.common import make_slot_name
from mapper.persistence.database import Placement
from utils.barcode_scanner import (
    BarcodeScanner,
    bind_auto_highlight,
    format_product_id,
    select_all_entry_text,
)
from .widgets import ScrollableFrame


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
        on_preview_shelf: Callable[[], object],
        on_revert_shift: Callable[[], object] | None = None,
        on_whole_mode_change: Callable[[bool], object] | None = None,
        barcode_scanner: BarcodeScanner | None = None,
    ):
        super().__init__(parent, padding=10)
        self.on_preview_shelf = on_preview_shelf
        self.on_load_address = on_load_address

        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True)

        products_panel = ttk.Frame(pane, padding=8)
        hand_panel = ttk.Frame(pane, padding=8)
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
            on_revert_shift,
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
        self.barcode_scanner = barcode_scanner
        self.whole_mode = False
        self._shift_clicked = False
        self.on_assign_address = on_assign_address
        self.on_catalog_to_queue = on_catalog_to_queue
        self.on_queue_to_hand = on_queue_to_hand
        self.on_whole_mode_change = on_whole_mode_change

        style = ttk.Style(self)
        style.configure(
            "WholeMode.Commit.TButton",
            font=("Segoe UI", 10, "bold italic"),
            foreground="#b45309",
            padding=(14, 7),
        )
        style.map(
            "WholeMode.Commit.TButton",
            foreground=[("disabled", "#a0a0a0"), ("active", "#92400e"), ("!disabled", "#b45309")],
        )
        style.configure(
            "WholeMode.TButton",
            font=("Segoe UI", 9, "bold italic"),
            foreground="#b45309",
        )
        style.map(
            "WholeMode.TButton",
            foreground=[("disabled", "#a0a0a0"), ("active", "#92400e"), ("!disabled", "#b45309")],
        )

        self.bind_all("<KeyPress-Shift_L>", self._on_shift_press, add="+")
        self.bind_all("<KeyPress-Shift_R>", self._on_shift_press, add="+")
        self.bind_all("<KeyRelease-Shift_L>", self._on_shift_release, add="+")
        self.bind_all("<KeyRelease-Shift_R>", self._on_shift_release, add="+")

    def _is_active_tab(self) -> bool:
        try:
            return bool(self.winfo_ismapped())
        except Exception:
            return False

    def _on_shift_press(self, event: tk.Event | None = None) -> None:
        if not self._is_active_tab():
            if self.whole_mode:
                self.set_whole_mode(False)
            return
        self.set_whole_mode(True)

    def _on_shift_release(self, event: tk.Event | None = None) -> None:
        if self.whole_mode:
            self.set_whole_mode(False)

    def set_whole_mode(self, enabled: bool) -> None:
        if self.whole_mode == enabled:
            return
        self.whole_mode = enabled
        if getattr(self, "on_whole_mode_change", None) is not None:
            try:
                self.on_whole_mode_change(enabled)
            except Exception:
                pass
        if hasattr(self, "assign_button"):
            if enabled:
                self.assign_button.configure(
                    text="Transfer ALL on-hand → shelf (Whole mode)",
                    style="WholeMode.Commit.TButton",
                )
            else:
                self.assign_button.configure(
                    text="Assign selected on-hand → loaded address",
                    style="Commit.TButton",
                )

        if hasattr(self, "catalog_transfer_button"):
            if enabled:
                self.catalog_transfer_button.configure(
                    text="Transfer selected → shelf (stock 999)",
                    style="WholeMode.TButton",
                )
            else:
                self.catalog_transfer_button.configure(
                    text="Transfer selected to total queue",
                    style="TButton",
                )

        if hasattr(self, "queue_move_button"):
            if enabled:
                self.queue_move_button.configure(
                    text="Transfer queue → shelf (stock 999)",
                    style="WholeMode.TButton",
                )
            else:
                self.queue_move_button.configure(
                    text="Move selected → on-hand",
                    style="TButton",
                )

    def set_queue_button_clicks(self, remaining_clicks: int | None = None) -> None:
        if not hasattr(self, "queue_move_button"):
            return
        if remaining_clicks is None or remaining_clicks <= 0:
            if self.whole_mode:
                self.queue_move_button.configure(
                    text="Transfer queue → shelf (stock 999)",
                    style="WholeMode.TButton",
                )
            else:
                self.queue_move_button.configure(
                    text="Move selected → on-hand",
                    style="TButton",
                )
        else:
            plural = "time" if remaining_clicks == 1 else "times"
            self.queue_move_button.configure(
                text=f"Click {remaining_clicks} more {plural} to transfer → shelf",
                style="WholeMode.TButton",
            )

    def _on_assign_button_press(self, event: tk.Event) -> None:
        if bool(event.state & 0x0001):
            self._shift_clicked = True

    def _handle_assign_click(self) -> None:
        whole = self.whole_mode or getattr(self, "_shift_clicked", False)
        self._shift_clicked = False
        try:
            self.on_assign_address(whole_mode=whole)
        except TypeError:
            self.on_assign_address()

    def _on_catalog_transfer_button_press(self, event: tk.Event) -> None:
        if bool(event.state & 0x0001):
            self._shift_clicked = True

    def _handle_catalog_transfer_click(self) -> None:
        to_shelf = self.whole_mode or getattr(self, "_shift_clicked", False)
        self._shift_clicked = False
        try:
            self.on_catalog_to_queue(to_shelf=to_shelf)
        except TypeError:
            self.on_catalog_to_queue()

    def _on_queue_move_button_press(self, event: tk.Event) -> None:
        if bool(event.state & 0x0001):
            self._shift_clicked = True

    def _handle_queue_move_click(self) -> None:
        to_shelf = self.whole_mode or getattr(self, "_shift_clicked", False)
        self._shift_clicked = False
        try:
            self.on_queue_to_hand(to_shelf=to_shelf)
        except TypeError:
            self.on_queue_to_hand()

    def _build_products_panel(
        self,
        parent: ttk.Frame,
        on_search: Callable[..., object],
        on_queue_to_hand: Callable[[], object],
        on_catalog_to_queue: Callable[[], object],
        on_catalog_activate: Callable[[tk.Event], object],
        on_revert_shift: Callable[[], object] | None,
    ) -> None:
        self.revert_button = ttk.Button(
            parent,
            text="Revert shift transfer",
            command=on_revert_shift,
            state="disabled",
        )
        self.revert_button.pack(side="bottom", fill="x", pady=(6, 0))

        split = ttk.Panedwindow(parent, orient="vertical")
        split.pack(fill="both", expand=True)
        queue = ttk.LabelFrame(split, text="Product queue · gray = on-hand / assigned", padding=6)
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
        bind_auto_highlight(self.search_entry)
        self.search_var.trace_add("write", on_search)
        self.search_location_text = tk.StringVar(self, value="")
        self.search_location_label = ttk.Label(
            queue,
            textvariable=self.search_location_text,
            foreground="#555555",
            width=1,
        )
        self.search_location_label.grid(row=2, column=0, sticky="ew", pady=(0, 5))

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
        self.queue_tree.tag_configure("assigned", foreground="#999999", background="#eeeeee")
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
        self.queue_tree.bind("<Double-1>", self._on_queue_double_click)
        self.queue_count_text = tk.StringVar(self, value="0 products")
        ttk.Label(queue, textvariable=self.queue_count_text).grid(
            row=4, column=0, sticky="w", pady=(5, 0)
        )
        self.queue_move_button = ttk.Button(
            queue,
            text="Move selected → on-hand",
            command=self._handle_queue_move_click,
        )
        self.queue_move_button.grid(row=5, column=0, sticky="ew", pady=(5, 0))
        self.queue_move_button.bind("<Button-1>", self._on_queue_move_button_press)

        catalog.rowconfigure(0, weight=1)
        catalog.columnconfigure(0, weight=1)
        catalog_body = ttk.Frame(catalog)
        catalog_body.grid(row=0, column=0, sticky="nsew")
        catalog_body.rowconfigure(0, weight=1)
        catalog_body.columnconfigure(0, weight=1)
        self.catalog_tree = ttk.Treeview(
            catalog_body,
            columns=("product_id", "product_name", "location_id"),
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
        self.catalog_transfer_button = ttk.Button(
            catalog,
            text="Transfer selected to total queue",
            command=self._handle_catalog_transfer_click,
        )
        self.catalog_transfer_button.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        self.catalog_transfer_button.bind("<Button-1>", self._on_catalog_transfer_button_press)

    @staticmethod
    def _configure_product_tree(tree: ttk.Treeview) -> None:
        tree.heading("product_id", text="Product ID")
        tree.heading("product_name", text="Product name")
        tree.heading("location_id", text="Location ID")
        tree.column("product_id", width=110, minwidth=80, stretch=False)
        tree.column("product_name", width=190, minwidth=110)
        tree.column("location_id", width=120, minwidth=85, stretch=False)

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
        parent: ttk.Frame,
        on_load_address: Callable[[], object],
        on_assign_address: Callable[[], object],
        on_dequeue_hand: Callable[[], object],
        on_modify_hand_stock: Callable[[], object],
    ) -> None:
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        tabs = ttk.Frame(parent)
        tabs.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tabs.columnconfigure((0, 1), weight=1)
        self.hand_view = tk.StringVar(self, value="queue")
        ttk.Radiobutton(
            tabs,
            text="On-hand queue",
            variable=self.hand_view,
            value="queue",
            style="Toolbutton",
            command=self._show_hand_view,
        ).grid(row=0, column=0, sticky="ew")
        ttk.Radiobutton(
            tabs,
            text="Shelf Selection Pane",
            variable=self.hand_view,
            value="shelf",
            style="Toolbutton",
            command=self._show_hand_view,
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self.hand_queue_page = ttk.Frame(parent)
        self.hand_shelf_page = ttk.Frame(parent)
        for page in (self.hand_queue_page, self.hand_shelf_page):
            page.grid(row=1, column=0, sticky="nsew")
            page.columnconfigure(0, weight=1)
        queue_page = self.hand_queue_page
        queue_page.rowconfigure(0, weight=1)
        self.hand_shelf_page.rowconfigure(1, weight=1)
        self.shelf_preview_text = tk.StringVar(
            self, value="Enter Floor, Side, and Shelf below."
        )
        ttk.Label(
            self.hand_shelf_page,
            textvariable=self.shelf_preview_text,
            width=1,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.shelf_scroll = ScrollableFrame(
            self.hand_shelf_page, horizontal=True, vertical=True
        )
        self.shelf_scroll.grid(row=1, column=0, sticky="nsew")
        self.shelf_slot_buttons: dict[tuple[int, int], tk.Button] = {}
        self.shelf_slot_names: dict[str, tuple[int, int]] = {}
        self._selected_shelf_cell: tuple[int, int] | None = None
        body = ttk.Frame(queue_page)
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
        ttk.Label(queue_page, textvariable=self.on_hand_count_text).grid(
            row=1, column=0, sticky="w", pady=(5, 0)
        )
        hand_actions = ttk.Frame(queue_page)
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
            text="Dequeue selected → source",
            command=on_dequeue_hand,
        ).grid(row=0, column=1, sticky="ew", padx=(3, 0))

        address = ttk.LabelFrame(parent, text="Shelf address", padding=8)
        self.address_panel = address
        address.grid(row=2, column=0, sticky="ew", pady=(6, 0))
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
        self.assign_button = ttk.Button(
            address,
            text="Assign selected on-hand → loaded address",
            command=self._handle_assign_click,
            style="Commit.TButton",
        )
        self.assign_button.grid(row=3, column=0, columnspan=5, sticky="ew", padx=2, pady=(6, 0))
        self.assign_button.bind("<Button-1>", self._on_assign_button_press)

        self.address_status_text = tk.StringVar(
            self, value="Enter an existing shelf address and load it."
        )
        ttk.Label(
            address,
            textvariable=self.address_status_text,
            width=1,
            foreground="#555555",
        ).grid(row=4, column=0, columnspan=5, sticky="ew", padx=2, pady=(6, 0))

        for variable in (self.floor_var, self.side_var, self.shelf_var):
            variable.trace_add("write", self._on_shelf_address_changed)
        self.clear_shelf_preview("Enter Floor, Side, and Shelf below.")
        self._show_hand_view()

    def _show_hand_view(self) -> None:
        if self.hand_view.get() == "shelf":
            self.hand_queue_page.grid_remove()
            self.hand_shelf_page.grid()
            self.on_preview_shelf()
        else:
            self.hand_shelf_page.grid_remove()
            self.hand_queue_page.grid()

    def _on_shelf_address_changed(self, *_args: object) -> None:
        self.row_var.set("")
        self.cell_var.set("")
        self.refresh_shelf_preview()

    def refresh_shelf_preview(self) -> None:
        if self.hand_view.get() == "shelf":
            self.on_preview_shelf()

    def clear_shelf_preview(self, message: str) -> None:
        for child in self.shelf_scroll.inner.winfo_children():
            child.destroy()
        self.shelf_slot_buttons.clear()
        self.shelf_slot_names.clear()
        self.shelf_cell_colors = {}
        self._selected_shelf_cell = None
        self._shelf_preview_key = None
        self.shelf_preview_text.set(message)
        self.shelf_scroll.canvas.xview_moveto(0)
        self.shelf_scroll.canvas.yview_moveto(0)

    def render_shelf_preview(
        self,
        floor: str,
        side: str,
        shelf_code: str,
        layout: list[int],
        contents: list[tuple[str, str, Placement]],
    ) -> None:
        key = (floor, side, shelf_code)
        same_shelf = getattr(self, "_shelf_preview_key", None) == key
        x_position = self.shelf_scroll.canvas.xview()[0] if same_shelf else 0.0
        y_position = self.shelf_scroll.canvas.yview()[0] if same_shelf else 0.0
        self.clear_shelf_preview(
            f"Floor {floor} · Side {side} · Shelf {shelf_code}"
        )
        self._shelf_preview_key = key
        counts = Counter(placement.slot_name for _, _, placement in contents)
        row_width = max(240, max(layout, default=1) * 70)
        even_side = side.isdigit() and int(side) % 2 == 0
        for row_number, count in enumerate(layout, start=1):
            screen_row = len(layout) - row_number + 1
            row_frame = tk.Frame(
                self.shelf_scroll.inner,
                width=row_width,
                height=44,
                background="#d0d0d0",
                borderwidth=1,
                relief="solid",
            )
            row_frame.grid(row=screen_row, column=0, sticky="nsew", pady=1)
            row_frame.grid_propagate(False)
            row_frame.rowconfigure(0, weight=1)
            cells = range(count, 0, -1) if even_side else range(1, count + 1)
            for display_column, cell in enumerate(cells):
                row_frame.columnconfigure(
                    display_column, weight=1, uniform=f"assign-r{row_number}"
                )
                slot_name = make_slot_name(
                    floor, shelf_code, row_number, cell, side=side
                )
                product_count = counts.get(slot_name, 0)
                color = "#d9ead3" if product_count else "#f7f7f7"
                button = tk.Button(
                    row_frame,
                    text=f"{row_number}-{cell:02d}\n{product_count}",
                    command=lambda row=row_number, col=cell: self._select_shelf_cell(
                        row, col
                    ),
                    background=color,
                    activebackground="#cfe8ff",
                    relief="solid",
                    borderwidth=1,
                    highlightthickness=0,
                    font=("Segoe UI", 8, "bold"),
                    padx=0,
                    pady=0,
                )
                button.grid(row=0, column=display_column, sticky="nsew", padx=1, pady=1)
                self.shelf_slot_buttons[(row_number, cell)] = button
                self.shelf_slot_names[slot_name] = (row_number, cell)
                self.shelf_cell_colors[(row_number, cell)] = color
        self.shelf_scroll.inner.update_idletasks()
        self.shelf_scroll.canvas.configure(
            scrollregion=self.shelf_scroll.canvas.bbox("all")
        )
        self.shelf_scroll.canvas.xview_moveto(x_position)
        self.shelf_scroll.canvas.yview_moveto(y_position)
        self.shelf_scroll.bind_wheel_events()
        try:
            self.highlight_shelf_cell(int(self.row_var.get()), int(self.cell_var.get()))
        except ValueError:
            pass

    def refresh_shelf_cell(self, slot_name: str, count: int) -> None:
        cell = self.shelf_slot_names.get(slot_name)
        if cell is None:
            return
        color = "#d9ead3" if count else "#f7f7f7"
        self.shelf_cell_colors[cell] = color
        selected = cell == self._selected_shelf_cell
        button = self.shelf_slot_buttons[cell]
        count_label = str(count)
        if "product" in button.cget("text").split("\n", 1)[-1]:
            count_label += f" product{'s' if count != 1 else ''}"
        button.configure(
            text=f"{cell[0]}-{cell[1]:02d}\n{count_label}",
            background="#cfe8ff" if selected else color,
            borderwidth=2 if selected else 1,
        )

    def highlight_shelf_cell(self, row: int, col: int) -> None:
        previous = self._selected_shelf_cell
        if previous is not None and previous in self.shelf_slot_buttons:
            self.shelf_slot_buttons[previous].configure(
                background=self.shelf_cell_colors[previous], borderwidth=1
            )
        cell = (row, col)
        self._selected_shelf_cell = cell if cell in self.shelf_slot_buttons else None
        if self._selected_shelf_cell is not None:
            self.shelf_slot_buttons[cell].configure(
                background="#cfe8ff", borderwidth=2
            )

    def _select_shelf_cell(self, row: int, col: int) -> None:
        self.row_var.set(str(row))
        self.cell_var.set(str(col))
        self.highlight_shelf_cell(row, col)
        self.on_load_address()

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
            width=1,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))
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
        ttk.Label(footer, textvariable=self.upload_status_text, width=1).grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(5, 0)
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
        self._set_and_select_search(
            self.search_var, self.search_entry, format_product_id(barcode)
        )

    def format_primary_search(self, _event=None) -> str:
        if self.barcode_scanner is not None and self.barcode_scanner.is_scanner():
            code = self.barcode_scanner.pop_scanner_code()
            value = format_product_id(code) if code else ""
        else:
            value = format_product_id(self.search_var.get())
        self._set_and_select_search(
            self.search_var,
            self.search_entry,
            value,
        )
        return "break"

    def focus_search(self) -> None:
        self._select_search_entry(self.search_entry)

    def _on_queue_double_click(self, event: tk.Event) -> str | None:
        item_id = self.queue_tree.identify_row(event.y)
        if not item_id:
            return None
        values = self.queue_tree.item(item_id, "values")
        if not values:
            return None
        self.queue_tree.selection_set(item_id)
        self.queue_tree.focus(item_id)
        self._set_and_select_search(self.search_var, self.search_entry, str(values[0]))
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

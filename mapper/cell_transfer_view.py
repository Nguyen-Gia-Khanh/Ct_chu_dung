"""Two-shelf workspace for switching or combining committed cell contents."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
import tkinter as tk
from tkinter import messagebox, ttk

from .common import clean_location_segment, make_slot_name, normalize_search
from .database import Placement, SlotAddress, WarehouseDatabase
from .widgets import ScrollableFrame
from utils.barcode_scanner import format_product_id


class CellTransferPane(ttk.LabelFrame):
    """One independently searchable shelf and selected-cell view."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        database: WarehouseDatabase,
    ) -> None:
        super().__init__(parent, text=title, padding=8)
        self.database = database
        self.shelves: list[tuple[int, str, str, str]] = []
        self.current_shelf_id: int | None = None
        self.current_layout: list[int] = []
        self.current_contents: list[tuple[str, str, Placement]] = []
        self.selected_address: SlotAddress | None = None
        self.slot_buttons: dict[str, tk.Button] = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=3)
        self.rowconfigure(5, weight=2)

        ttk.Label(self, text="Find product ID or location ID").grid(
            row=0, column=0, sticky="w"
        )
        search = ttk.Frame(self)
        search.grid(row=1, column=0, sticky="ew", pady=(3, 7))
        search.columnconfigure(0, weight=1)
        self.search_var = tk.StringVar(self)
        self.search_entry = ttk.Entry(search, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.search_entry.bind("<Return>", self.find)
        ttk.Button(search, text="Find", command=self.find).grid(
            row=0, column=1, padx=(5, 0)
        )

        selectors = ttk.Frame(self)
        selectors.grid(row=2, column=0, sticky="ew", pady=(0, 7))
        selector_specs = (
            ("Floor", "floor_var", "floor_selector", 8),
            ("Side", "side_var", "side_selector", 8),
            ("Shelf", "shelf_var", "shelf_selector", 10),
            ("Row", "row_var", "row_selector", 6),
            ("Cell", "cell_var", "cell_selector", 6),
        )
        for column, (label, var_name, widget_name, width) in enumerate(
            selector_specs
        ):
            selectors.columnconfigure(column, weight=1)
            ttk.Label(selectors, text=label).grid(
                row=0, column=column, sticky="w", padx=(0, 4)
            )
            variable = tk.StringVar(self)
            selector = ttk.Combobox(
                selectors,
                textvariable=variable,
                state="readonly",
                width=width,
            )
            selector.grid(row=1, column=column, sticky="ew", padx=(0, 4))
            setattr(self, var_name, variable)
            setattr(self, widget_name, selector)

        self.floor_selector.bind("<<ComboboxSelected>>", self._floor_changed)
        self.side_selector.bind("<<ComboboxSelected>>", self._side_changed)
        self.shelf_selector.bind("<<ComboboxSelected>>", self._shelf_changed)
        self.row_selector.bind("<<ComboboxSelected>>", self._row_changed)
        self.cell_selector.bind("<<ComboboxSelected>>", self._cell_changed)

        shelf_frame = ttk.LabelFrame(self, text="Shelf — click a cell", padding=5)
        shelf_frame.grid(row=3, column=0, sticky="nsew")
        shelf_frame.rowconfigure(0, weight=1)
        shelf_frame.columnconfigure(0, weight=1)
        self.shelf_scroll = ScrollableFrame(
            shelf_frame,
            horizontal=True,
            vertical=True,
            smooth=True,
        )
        self.shelf_scroll.grid(row=0, column=0, sticky="nsew")

        self.selection_text = tk.StringVar(self, value="No cell selected")
        ttk.Label(
            self,
            textvariable=self.selection_text,
            style="Heading.TLabel",
        ).grid(row=4, column=0, sticky="w", pady=(7, 4))

        contents_frame = ttk.Frame(self)
        contents_frame.grid(row=5, column=0, sticky="nsew")
        contents_frame.rowconfigure(0, weight=1)
        contents_frame.columnconfigure(0, weight=1)
        self.contents_tree = ttk.Treeview(
            contents_frame,
            columns=("product_id", "product_name", "stock_qty"),
            show="headings",
            height=6,
        )
        self.contents_tree.heading("product_id", text="Product ID")
        self.contents_tree.heading("product_name", text="Product name")
        self.contents_tree.heading("stock_qty", text="Stock")
        self.contents_tree.column(
            "product_id", width=110, minwidth=80, stretch=False
        )
        self.contents_tree.column("product_name", width=190, minwidth=100)
        self.contents_tree.column(
            "stock_qty", width=65, minwidth=50, anchor="e", stretch=False
        )
        y_scroll = ttk.Scrollbar(
            contents_frame,
            orient="vertical",
            command=self.contents_tree.yview,
        )
        x_scroll = ttk.Scrollbar(
            contents_frame,
            orient="horizontal",
            command=self.contents_tree.xview,
        )
        self.contents_tree.configure(
            yscrollcommand=y_scroll.set,
            xscrollcommand=x_scroll.set,
        )
        self.contents_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        self._render_empty("Choose a shelf or find a product/location above.")

    @property
    def selected_product_count(self) -> int:
        if self.selected_address is None:
            return 0
        return sum(
            placement.slot_name == self.selected_address.slot_name
            for _product_id, _product_name, placement in self.current_contents
        )

    def refresh(self) -> None:
        """Reload selector choices while keeping the current shelf/cell if possible."""
        selected_slot_id = (
            self.selected_address.slot_id if self.selected_address is not None else None
        )
        self.shelves = self.database.list_shelves()
        floors = sorted({floor for _id, floor, _side, _code in self.shelves})
        self.floor_selector.configure(values=floors)
        if self.current_shelf_id is None:
            if self.floor_var.get() not in floors:
                self._clear_all_selectors()
                if len(floors) == 1:
                    self.floor_var.set(floors[0])
                    self._floor_changed()
            return
        try:
            self.load_shelf(self.current_shelf_id, select_slot_id=selected_slot_id)
        except KeyError:
            self.current_shelf_id = None
            self.selected_address = None
            self.current_layout = []
            self.current_contents = []
            self._clear_all_selectors()
            self._render_empty("The previously selected shelf no longer exists.")

    def find(self, _event: tk.Event | None = None) -> str:
        raw_query = self.search_var.get().strip()
        if not raw_query:
            return "break"

        query = format_product_id(raw_query)
        address = self.database.get_slot_by_name(query)
        if address is None:
            product_location = self.database.get_product_location(query)
            if product_location is not None:
                floor, side, shelf_code, _layout = self.database.get_shelf(
                    product_location.shelf_id
                )
                address = self.database.get_slot_address(
                    floor,
                    side,
                    shelf_code,
                    product_location.row_number,
                    product_location.slot_number,
                )
        if address is not None:
            self.load_shelf(address.shelf_id, select_slot_id=address.slot_id)
            self.search_var.set(query)
            self.search_entry.selection_range(0, tk.END)
            return "break"

        normalized = normalize_search(raw_query)
        shelf_matches = [
            shelf
            for shelf in self.shelves
            if normalized
            in normalize_search(
                f"{shelf[1]} {shelf[2]} {shelf[3]} "
                f"floor {shelf[1]} side {shelf[2]} shelf {shelf[3]}"
            )
        ]
        if len(shelf_matches) == 1:
            self.load_shelf(shelf_matches[0][0])
        elif len(shelf_matches) > 1:
            messagebox.showinfo(
                "More than one shelf found",
                "Use the Floor, Side, and Shelf selectors to choose the exact shelf.",
                parent=self,
            )
        else:
            messagebox.showinfo(
                "Nothing found",
                "Enter an exact product ID, location ID, or a unique shelf search.",
                parent=self,
            )
        return "break"

    def load_shelf(
        self,
        shelf_id: int,
        *,
        select_slot_id: int | None = None,
    ) -> None:
        floor, side, shelf_code, layout = self.database.get_shelf(shelf_id)
        contents = self.database.get_shelf_contents(shelf_id)
        self.current_shelf_id = shelf_id
        self.current_layout = layout
        self.current_contents = contents
        self.selected_address = None
        self._set_shelf_selectors(floor, side, shelf_code, layout)
        self._render_shelf(floor, side, shelf_code, layout, contents)

        if select_slot_id is not None:
            address = self.database.get_slot_by_id(select_slot_id)
            if address is not None and address.shelf_id == shelf_id:
                self.select_address(address)

    def select_address(self, address: SlotAddress) -> None:
        old_name = (
            self.selected_address.slot_name
            if self.selected_address is not None
            else None
        )
        self.selected_address = address
        for slot_name in (old_name, address.slot_name):
            button = self.slot_buttons.get(slot_name or "")
            if button is not None:
                selected = slot_name == address.slot_name
                button.configure(
                    borderwidth=3 if selected else 1,
                    font=("Segoe UI", 9, "bold" if selected else "normal"),
                )
        self.row_var.set(str(address.row_number))
        self._set_cell_choices(address.row_number)
        self.cell_var.set(str(address.slot_number))
        self._refresh_contents()

    def _floor_changed(self, _event: tk.Event | None = None) -> None:
        floor = self.floor_var.get()
        self._clear_loaded_shelf("Complete the selectors to load a shelf.")
        sides = sorted(
            {
                side
                for _id, shelf_floor, side, _code in self.shelves
                if shelf_floor == floor
            }
        )
        self.side_selector.configure(values=sides)
        self.side_var.set(sides[0] if len(sides) == 1 else "")
        self.shelf_var.set("")
        self.row_var.set("")
        self.cell_var.set("")
        if self.side_var.get():
            self._side_changed()

    def _side_changed(self, _event: tk.Event | None = None) -> None:
        floor = self.floor_var.get()
        side = self.side_var.get()
        self._clear_loaded_shelf("Choose a shelf to continue.")
        shelf_codes = sorted(
            {
                code
                for _id, shelf_floor, shelf_side, code in self.shelves
                if shelf_floor == floor and shelf_side == side
            }
        )
        self.shelf_selector.configure(values=shelf_codes)
        self.shelf_var.set(shelf_codes[0] if len(shelf_codes) == 1 else "")
        self.row_var.set("")
        self.cell_var.set("")
        if self.shelf_var.get():
            self._shelf_changed()

    def _shelf_changed(self, _event: tk.Event | None = None) -> None:
        key = (self.floor_var.get(), self.side_var.get(), self.shelf_var.get())
        shelf_id = next(
            (
                shelf_id
                for shelf_id, floor, side, shelf_code in self.shelves
                if (floor, side, shelf_code) == key
            ),
            None,
        )
        if shelf_id is not None and shelf_id != self.current_shelf_id:
            self.load_shelf(shelf_id)

    def _row_changed(self, _event: tk.Event | None = None) -> None:
        self._clear_cell_selection()
        try:
            row_number = int(self.row_var.get())
        except ValueError:
            self.cell_selector.configure(values=())
            self.cell_var.set("")
            return
        self._set_cell_choices(row_number)
        self.cell_var.set("")

    def _cell_changed(self, _event: tk.Event | None = None) -> None:
        try:
            row_number = int(self.row_var.get())
            slot_number = int(self.cell_var.get())
        except ValueError:
            return
        self._select_coordinates(row_number, slot_number)

    def _select_coordinates(self, row_number: int, slot_number: int) -> None:
        if self.current_shelf_id is None:
            return
        floor, side, shelf_code, _layout = self.database.get_shelf(
            self.current_shelf_id
        )
        address = self.database.get_slot_address(
            floor,
            side,
            shelf_code,
            row_number,
            slot_number,
        )
        if address is not None:
            self.select_address(address)

    def _set_shelf_selectors(
        self,
        floor: str,
        side: str,
        shelf_code: str,
        layout: list[int],
    ) -> None:
        floors = sorted({item[1] for item in self.shelves})
        sides = sorted({item[2] for item in self.shelves if item[1] == floor})
        shelf_codes = sorted(
            {
                item[3]
                for item in self.shelves
                if item[1] == floor and item[2] == side
            }
        )
        self.floor_selector.configure(values=floors)
        self.side_selector.configure(values=sides)
        self.shelf_selector.configure(values=shelf_codes)
        self.row_selector.configure(values=[str(row) for row in range(1, len(layout) + 1)])
        self.cell_selector.configure(values=())
        self.floor_var.set(floor)
        self.side_var.set(side)
        self.shelf_var.set(shelf_code)
        self.row_var.set("")
        self.cell_var.set("")

    def _set_cell_choices(self, row_number: int) -> None:
        count = (
            self.current_layout[row_number - 1]
            if 1 <= row_number <= len(self.current_layout)
            else 0
        )
        self.cell_selector.configure(values=[str(cell) for cell in range(1, count + 1)])

    def _clear_all_selectors(self) -> None:
        for variable in (
            self.floor_var,
            self.side_var,
            self.shelf_var,
            self.row_var,
            self.cell_var,
        ):
            variable.set("")
        self.side_selector.configure(values=())
        self.shelf_selector.configure(values=())
        self.row_selector.configure(values=())
        self.cell_selector.configure(values=())

    def _clear_loaded_shelf(self, message: str) -> None:
        self.current_shelf_id = None
        self.current_layout = []
        self.current_contents = []
        self.selected_address = None
        self._render_empty(message)

    def _clear_cell_selection(self) -> None:
        if self.selected_address is not None:
            button = self.slot_buttons.get(self.selected_address.slot_name)
            if button is not None:
                button.configure(
                    borderwidth=1,
                    font=("Segoe UI", 9, "normal"),
                )
        self.selected_address = None
        self.selection_text.set("No cell selected")
        self.contents_tree.delete(*self.contents_tree.get_children())

    def _render_empty(self, message: str) -> None:
        for child in self.shelf_scroll.inner.winfo_children():
            child.destroy()
        self.slot_buttons.clear()
        ttk.Label(
            self.shelf_scroll.inner,
            text=message,
            wraplength=360,
        ).pack(padx=25, pady=25)
        self.selection_text.set("No cell selected")
        self.contents_tree.delete(*self.contents_tree.get_children())
        self.shelf_scroll.bind_wheel_events()

    def _render_shelf(
        self,
        floor: str,
        side: str,
        shelf_code: str,
        layout: list[int],
        contents: list[tuple[str, str, Placement]],
    ) -> None:
        for child in self.shelf_scroll.inner.winfo_children():
            child.destroy()
        self.slot_buttons.clear()
        counts = Counter(placement.slot_name for _id, _name, placement in contents)
        row_width = max(320, max(layout, default=1) * 78)
        shelf_label = clean_location_segment(shelf_code)

        ttk.Label(
            self.shelf_scroll.inner,
            text=f"FLOOR {floor.upper()} · SIDE {side.upper()} · SHELF {shelf_code.upper()}",
            style="Heading.TLabel",
        ).grid(row=0, column=0, columnspan=2, pady=(7, 10))
        for row_number, count in enumerate(layout, start=1):
            screen_row = len(layout) - row_number + 1
            ttk.Label(
                self.shelf_scroll.inner,
                text=f"R{row_number}" + (" · ground" if row_number == 1 else ""),
            ).grid(row=screen_row, column=0, padx=(5, 7), sticky="e")
            row_frame = tk.Frame(
                self.shelf_scroll.inner,
                width=row_width,
                height=62,
                background="#d0d0d0",
                borderwidth=1,
                relief="solid",
            )
            row_frame.grid(row=screen_row, column=1, sticky="nsew", pady=2)
            row_frame.grid_propagate(False)
            row_frame.rowconfigure(0, weight=1)
            for slot_number in range(1, count + 1):
                row_frame.columnconfigure(
                    slot_number - 1,
                    weight=1,
                    uniform=f"transfer-r{row_number}",
                )
                slot_name = make_slot_name(
                    floor,
                    shelf_code,
                    row_number,
                    slot_number,
                    side=side,
                )
                product_count = counts.get(slot_name, 0)
                button = tk.Button(
                    row_frame,
                    text=f"{shelf_label}{row_number}-{slot_number}\n{product_count} product{'s' if product_count != 1 else ''}",
                    command=lambda row=row_number, cell=slot_number: self._select_coordinates(
                        row, cell
                    ),
                    background="#d9ead3" if product_count else "#f7f7f7",
                    activebackground="#cfe8ff",
                    relief="solid",
                    borderwidth=1,
                    highlightthickness=0,
                    font=("Segoe UI", 9),
                )
                button.grid(
                    row=0,
                    column=slot_number - 1,
                    sticky="nsew",
                    padx=1,
                    pady=1,
                )
                self.slot_buttons[slot_name] = button
        self.selection_text.set("No cell selected")
        self.contents_tree.delete(*self.contents_tree.get_children())
        self.shelf_scroll.inner.update_idletasks()
        self.shelf_scroll.canvas.configure(
            scrollregion=self.shelf_scroll.canvas.bbox("all")
        )
        self.shelf_scroll.bind_wheel_events()

    def _refresh_contents(self) -> None:
        tree = self.contents_tree
        tree.delete(*tree.get_children())
        if self.selected_address is None:
            self.selection_text.set("No cell selected")
            return
        visible = [
            (product_id, product_name, placement)
            for product_id, product_name, placement in self.current_contents
            if placement.slot_name == self.selected_address.slot_name
        ]
        for product_id, product_name, placement in visible:
            tree.insert(
                "",
                "end",
                iid=f"product::{product_id}",
                values=(
                    product_id,
                    product_name,
                    placement.stock_qty
                    if placement.stock_qty is not None
                    else "Unknown",
                ),
            )
        count = len(visible)
        self.selection_text.set(
            f"{self.selected_address.slot_name} · {count} product{'s' if count != 1 else ''}"
        )


class CellTransferView(ttk.Frame):
    """Fifth tab: select two committed cells and switch or combine them."""

    def __init__(
        self,
        parent: tk.Misc,
        database: WarehouseDatabase,
        on_changed: Callable[[str], object],
        can_change: Callable[[], bool],
    ) -> None:
        super().__init__(parent, padding=10)
        self.database = database
        self.on_changed = on_changed
        self.can_change = can_change

        ttk.Label(
            self,
            text="Select one cell on each side, then switch or combine their committed products.",
            style="Heading.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            self,
            text="Local SQLite locations are updated immediately; KiotViet is not changed by this tab.",
            foreground="#8a6d1d",
        ).pack(anchor="w", pady=(0, 8))

        workspace = ttk.Frame(self)
        workspace.pack(fill="both", expand=True)
        workspace.rowconfigure(0, weight=1)
        workspace.columnconfigure(0, weight=1, uniform="transfer-side")
        workspace.columnconfigure(2, weight=1, uniform="transfer-side")

        self.left = CellTransferPane(workspace, "Left cell", database)
        self.left.grid(row=0, column=0, sticky="nsew")

        actions = ttk.LabelFrame(workspace, text="Cell actions", padding=10)
        actions.grid(row=0, column=1, sticky="ns", padx=8)
        ttk.Button(
            actions,
            text="Switch cells ↔",
            command=self.swap_cells,
        ).pack(fill="x", pady=(2, 8))
        ttk.Button(
            actions,
            text="Combine left → right",
            command=lambda: self.combine_cells(self.left, self.right),
        ).pack(fill="x", pady=2)
        ttk.Button(
            actions,
            text="Combine right → left",
            command=lambda: self.combine_cells(self.right, self.left),
        ).pack(fill="x", pady=2)
        ttk.Separator(actions).pack(fill="x", pady=10)
        ttk.Button(actions, text="Refresh both", command=self.refresh).pack(fill="x")
        ttk.Label(
            actions,
            text="Switch exchanges both cells.\n\nCombine empties the source into the target and keeps the target's current products.",
            foreground="#555555",
            wraplength=170,
            justify="left",
        ).pack(anchor="w", pady=(12, 0))
        self.status_text = tk.StringVar(self, value="Choose two cells.")
        ttk.Label(
            actions,
            textvariable=self.status_text,
            wraplength=170,
            justify="left",
        ).pack(anchor="w", pady=(14, 0))

        self.right = CellTransferPane(workspace, "Right cell", database)
        self.right.grid(row=0, column=2, sticky="nsew")
        self.refresh()

    def refresh(self) -> None:
        self.left.refresh()
        self.right.refresh()

    def _selected_pair(self) -> tuple[SlotAddress, SlotAddress] | None:
        left = self.left.selected_address
        right = self.right.selected_address
        if left is None or right is None:
            messagebox.showinfo(
                "Choose two cells",
                "Select one shelf cell on the left and one on the right first.",
                parent=self,
            )
            return None
        if left.slot_id == right.slot_id:
            messagebox.showinfo(
                "Choose different cells",
                "The left and right selections point to the same shelf cell.",
                parent=self,
            )
            return None
        return left, right

    def swap_cells(self) -> None:
        if not self.can_change():
            return
        pair = self._selected_pair()
        if pair is None:
            return
        left, right = pair
        if not messagebox.askyesno(
            "Switch complete cell contents?",
            f"Exchange all products in {left.slot_name} and {right.slot_name}?\n\n"
            f"{left.slot_name}: {self.left.selected_product_count} product(s)\n"
            f"{right.slot_name}: {self.right.selected_product_count} product(s)",
            parent=self,
        ):
            return
        try:
            left_count, right_count = self.database.swap_slot_contents(
                left.slot_id,
                right.slot_id,
            )
        except Exception as error:
            messagebox.showerror("Cells could not be switched", str(error), parent=self)
            return
        message = (
            f"Switched {left.slot_name} ({left_count}) with "
            f"{right.slot_name} ({right_count})."
        )
        self.on_changed(message)
        self.refresh()
        self.status_text.set(message)

    def combine_cells(
        self,
        source: CellTransferPane,
        target: CellTransferPane,
    ) -> None:
        if not self.can_change():
            return
        pair = self._selected_pair()
        if pair is None:
            return
        source_address = source.selected_address
        target_address = target.selected_address
        if source_address is None or target_address is None:
            return
        source_count = source.selected_product_count
        if source_count == 0:
            self.status_text.set(f"{source_address.slot_name} is already empty.")
            return
        if not messagebox.askyesno(
            "Combine complete cell contents?",
            f"Move all {source_count} product(s) from {source_address.slot_name} "
            f"into {target_address.slot_name}?\n\n"
            f"The target's {target.selected_product_count} current product(s) will remain.",
            parent=self,
        ):
            return
        try:
            moved = self.database.combine_slot_contents(
                source_address.slot_id,
                target_address.slot_id,
            )
        except Exception as error:
            messagebox.showerror("Cells could not be combined", str(error), parent=self)
            return
        message = (
            f"Combined {moved} product(s) from {source_address.slot_name} "
            f"into {target_address.slot_name}."
        )
        self.on_changed(message)
        self.refresh()
        self.status_text.set(message)

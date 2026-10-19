"""Two-shelf workspace for switching or combining committed cell contents."""

from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from mapper.core.common import clean_location_segment, normalize_sku
from mapper.persistence.database import Placement, SlotAddress, WarehouseDatabase
from mapper.features.web_upload import LocationUpdate
from mapper.services.cell_lookup import find_cell
from mapper.services.shelf_grid import load_grid
from .shelf_address_lookup import ShelfAddressLookup
from .widgets import ShelfGridCanvas, sync_tree_rows
from utils.barcode_scanner import BarcodeScanner


class DuplicateCellMergeDialog(simpledialog.Dialog):
    """Choose whether to merge overlapping products or discard the cell move."""

    def __init__(self, parent, product_ids, target_name):
        self.product_ids = product_ids
        self.target_name = target_name
        self.result = False
        super().__init__(parent, title="Products already in both cells")

    def body(self, master):
        ttk.Label(
            master, text=f"{len(self.product_ids)} product(s) are already in both cells.\n"
            f"Keep their shared stock and combine locations in {self.target_name} and move the other products?",
            wraplength=460,
        ).pack(anchor="w", padx=8, pady=8)
        products = tk.Text(master, width=55, height=min(8, len(self.product_ids)), wrap="word")
        products.insert("1.0", ", ".join(self.product_ids))
        products.configure(state="disabled")
        products.pack(fill="x", padx=8)
        ttk.Label(master, text="Each SKU keeps its single stock count.\n"
                  "Discard move keeps both cells unchanged.", wraplength=460).pack(
                      anchor="w", padx=8, pady=8)

    def buttonbox(self):
        buttons = ttk.Frame(self)
        discard = ttk.Button(buttons, text="Discard move", command=self.cancel)
        discard.pack(side="left", padx=5)
        ttk.Button(buttons, text="Combine locations", command=self.ok).pack(side="left", padx=5)
        buttons.pack(pady=8)
        discard.focus_set()
        self.bind("<Escape>", self.cancel)

    def apply(self):
        self.result = True


class CellTransferPane(ttk.LabelFrame):
    """One independently searchable shelf and selected-cell view."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        database: WarehouseDatabase,
        barcode_scanner: BarcodeScanner | None = None,
    ) -> None:
        super().__init__(parent, text=title, padding=8)
        self.database = database
        self.barcode_scanner = barcode_scanner
        self.shelves: list[tuple[int, str, str, str]] = []
        self.current_shelf_id: int | None = None
        self.current_layout: list[int] = []
        self.current_contents: list[tuple[str, str, Placement]] = []
        self.selected_address: SlotAddress | None = None
        self.on_focus_callback: Callable[[CellTransferPane], object] | None = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=3)
        self.rowconfigure(5, weight=2)

        cascade_frame = ttk.Frame(self)
        cascade_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        cascade_frame.columnconfigure(1, weight=1)

        ttk.Label(cascade_frame, text="Shelf:").grid(
            row=0, column=0, sticky="w", padx=(0, 4)
        )
        self.shelf_choices: dict[str, int] = {}
        self.shelf_id_to_label: dict[int, str] = {}
        self.shelf_var = tk.StringVar(self)
        self.shelf_selector = ttk.Combobox(
            cascade_frame,
            textvariable=self.shelf_var,
            state="readonly",
            width=26,
        )
        self.shelf_selector.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.shelf_selector.bind("<<ComboboxSelected>>", self._shelf_changed)

        ttk.Label(cascade_frame, text="Row:").grid(
            row=0, column=2, sticky="w", padx=(0, 3)
        )
        self.row_var = tk.StringVar(self)
        self.row_selector = ttk.Combobox(
            cascade_frame,
            textvariable=self.row_var,
            state="readonly",
            width=4,
        )
        self.row_selector.grid(row=0, column=3, sticky="w", padx=(0, 8))
        self.row_selector.bind("<<ComboboxSelected>>", self._row_changed)

        ttk.Label(cascade_frame, text="Cell:").grid(
            row=0, column=4, sticky="w", padx=(0, 3)
        )
        self.cell_var = tk.StringVar(self)
        self.cell_selector = ttk.Combobox(
            cascade_frame,
            textvariable=self.cell_var,
            state="readonly",
            width=4,
        )
        self.cell_selector.grid(row=0, column=5, sticky="w")
        self.cell_selector.bind("<<ComboboxSelected>>", self._cell_changed)

        self.floor_var = tk.StringVar(self)
        self.side_var = tk.StringVar(self)

        self.shelf_address_lookup = ShelfAddressLookup(
            self, self.database.list_shelves, self.load_shelf
        )
        self.shelf_address_lookup.grid(row=1, column=0, sticky="ew", pady=(0, 5))

        search = ttk.Frame(self)
        search.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        search.columnconfigure(1, weight=1)
        ttk.Label(search, text="Find product ID:").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.search_var = tk.StringVar(self)
        self.search_entry = ttk.Entry(search, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=1, sticky="ew")
        self.search_entry.bind("<Return>", self.find)
        self.search_entry.bind(
            "<FocusIn>",
            self._on_search_focus,
            add="+",
        )
        self.search_entry.bind(
            "<Button-1>",
            self._on_search_click,
            add="+",
        )
        ttk.Button(search, text="Find", command=self.find).grid(
            row=0, column=2, padx=(5, 0)
        )

        shelf_frame = ttk.LabelFrame(self, text="Shelf — click a cell", padding=5)
        shelf_frame.grid(row=3, column=0, sticky="nsew")
        shelf_frame.rowconfigure(0, weight=1)
        shelf_frame.columnconfigure(0, weight=1)
        self.shelf_grid = ShelfGridCanvas(
            shelf_frame, on_select=lambda cell: self._select_coordinates(cell.row, cell.cell),
            label=lambda cell: f"{self.side_var.get()}{self._shelf_code()}{cell.row}-{cell.cell}", cell_width=78)
        self.shelf_grid.grid(row=0, column=0, sticky="nsew")

        self.selection_text = tk.StringVar(self, value="No cell selected")
        ttk.Label(
            self,
            textvariable=self.selection_text,
            style="Heading.TLabel",
        ).grid(row=4, column=0, sticky="w", pady=(6, 4))

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
        self.contents_tree.bind("<Double-1>", self._on_contents_double_click)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        self._render_empty("Select a shelf above or enter a product ID to find.")

    @property
    def selected_product_count(self) -> int:
        if self.selected_address is None:
            return 0
        return sum(
            placement.slot_name == self.selected_address.slot_name
            for _product_id, _product_name, placement in self.current_contents
        )

    def _shelf_code(self) -> str:
        model = self.shelf_grid.model
        return clean_location_segment(model.shelf_code) if model is not None else ""

    def refresh(self) -> None:
        """Reload selector choices while keeping the current shelf/cell if possible."""
        selected_slot_id = (
            self.selected_address.slot_id if self.selected_address is not None else None
        )
        self.shelves = self.database.list_shelves()
        choices = {
            f"Floor {floor} — Side {side} — Shelf {shelf_code}": shelf_id
            for shelf_id, floor, side, shelf_code in self.shelves
        }
        if choices != self.shelf_choices:
            self.shelf_selector.configure(values=list(choices.keys()))
        self.shelf_choices = choices
        self.shelf_id_to_label = {
            shelf_id: label
            for label, shelf_id in self.shelf_choices.items()
        }

        if self.current_shelf_id is None:
            if self.shelves:
                self.load_shelf(self.shelves[0][0])
            else:
                self._clear_all_selectors()
            return
        if self.current_shelf_id not in self.shelf_id_to_label:
            if self.shelves:
                self.load_shelf(self.shelves[0][0])
            else:
                self.current_shelf_id = None
                self.selected_address = None
                self.current_layout = []
                self.current_contents = []
                self._clear_all_selectors()
                self._render_empty("The previously selected shelf no longer exists.")
            return
        try:
            self.load_shelf(self.current_shelf_id, select_slot_id=selected_slot_id)
        except KeyError:
            if self.shelves:
                self.load_shelf(self.shelves[0][0])
            else:
                self.current_shelf_id = None
                self.selected_address = None
                self.current_layout = []
                self.current_contents = []
                self._clear_all_selectors()
                self._render_empty("The previously selected shelf no longer exists.")

    @staticmethod
    def _select_search_entry(entry: ttk.Entry) -> None:
        entry.focus_set()
        entry.selection_range(0, tk.END)
        entry.icursor(tk.END)

    def _set_and_select_search(self, value: str) -> None:
        self.search_var.set(value)
        self.after_idle(lambda: self._select_search_entry(self.search_entry))

    def _on_search_focus(self, _event: tk.Event | None = None) -> None:
        if self.on_focus_callback is not None:
            self.on_focus_callback(self)
        self.after_idle(lambda: self._select_search_entry(self.search_entry))

    def _on_search_click(self, _event: tk.Event | None = None) -> None:
        if self.on_focus_callback is not None:
            self.on_focus_callback(self)
        self.after_idle(lambda: self._select_search_entry(self.search_entry))

    def _on_contents_double_click(self, _event: tk.Event | None = None) -> None:
        selection = self.contents_tree.selection()
        if not selection:
            return
        item_id = selection[0]
        if item_id.startswith("product::"):
            product_id = item_id.removeprefix("product::")
            self._set_and_select_search(product_id)
            self.find()

    def find(self, _event: tk.Event | None = None) -> str:
        if self.barcode_scanner is not None and self.barcode_scanner.is_scanner():
            raw_query = (self.barcode_scanner.pop_scanner_code() or "").strip()
        else:
            raw_query = self.search_var.get().strip()
        if not raw_query:
            return "break"
        query = normalize_sku(raw_query)
        found = find_cell(self.database, raw_query, self.shelves or None)
        if found.address is not None:
            if not self.shelf_choices:
                self.refresh()
            self.load_shelf(found.address.shelf_id, select_slot_id=found.address.slot_id)
        elif len(found.shelves) == 1:
            self.load_shelf(found.shelves[0][0])
        elif found.shelves:
            messagebox.showinfo("More than one shelf found",
                                "Use the Shelf dropdown above to select the exact shelf.", parent=self)
        else:
            messagebox.showinfo("Product not found",
                                f"Product ID or location '{raw_query}' was not found on any shelf.", parent=self)
        self._set_and_select_search(query)
        return "break"

    def load_shelf(self, shelf_id: int, *, select_slot_id: int | None = None) -> None:
        grid, contents = load_grid(self.database, shelf_id)
        floor, side, shelf_code = grid.key
        same_layout = self.shelf_grid.key == (*grid.key, grid.layout)
        self.current_shelf_id = shelf_id
        self.current_layout = list(grid.layout)
        self.current_contents = contents
        if not same_layout:
            self.selected_address = None
        self.floor_var.set(floor)
        self.side_var.set(side)
        self.shelf_address_lookup.set_address(floor, side, shelf_code)
        self.shelf_var.set(self.shelf_id_to_label.get(shelf_id, f"Floor {floor} — Side {side} — Shelf {shelf_code}"))
        self.row_selector.configure(values=[str(row) for row in range(1, len(grid.layout) + 1)])
        if not same_layout:
            self.row_var.set("")
            self.cell_selector.configure(values=())
            self.cell_var.set("")
        selected = self.selected_address.slot_name if self.selected_address is not None else None
        self.shelf_grid.show(grid, selected=selected, keep_view=same_layout)
        self._refresh_contents()
        if select_slot_id is not None and (
            self.selected_address is None or self.selected_address.slot_id != select_slot_id
        ):
            address = self.database.get_slot_by_id(select_slot_id)
            if address is not None and address.shelf_id == shelf_id:
                self.select_address(address)

    def select_address(self, address: SlotAddress) -> None:
        self.selected_address = address
        self.shelf_grid.select(address.slot_name)
        label = self.shelf_id_to_label.get(address.shelf_id)
        if label:
            self.shelf_var.set(label)
        self.row_var.set(str(address.row_number))
        self._set_cell_choices(address.row_number)
        self.cell_var.set(str(address.slot_number))
        self._refresh_contents()

    def _shelf_changed(self, _event: tk.Event | None = None) -> None:
        shelf_id = self.shelf_choices.get(self.shelf_var.get())
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
            self._select_coordinates(int(self.row_var.get()), int(self.cell_var.get()))
        except ValueError:
            return

    def _select_coordinates(self, row_number: int, slot_number: int) -> None:
        if self.current_shelf_id is not None:
            address = self.database.get_slot_in_shelf(self.current_shelf_id, row_number, slot_number)
            if address is not None:
                self.select_address(address)

    def _set_cell_choices(self, row_number: int) -> None:
        count = self.current_layout[row_number - 1] if 1 <= row_number <= len(self.current_layout) else 0
        self.cell_selector.configure(values=[str(cell) for cell in range(1, count + 1)])

    def _clear_all_selectors(self) -> None:
        for variable in (self.shelf_var, self.row_var, self.cell_var, self.floor_var, self.side_var):
            variable.set("")
        self.shelf_address_lookup.set_address("", "", "")
        self.row_selector.configure(values=())
        self.cell_selector.configure(values=())

    def _clear_loaded_shelf(self, message: str) -> None:
        self.current_shelf_id = None
        self.current_layout = []
        self.current_contents = []
        self.selected_address = None
        self._render_empty(message)

    def _clear_cell_selection(self) -> None:
        self.selected_address = None
        self.shelf_grid.select(None)
        self._refresh_contents()

    def _render_empty(self, message: str) -> None:
        self.shelf_grid.show_message(message)
        self._refresh_contents()

    def refresh_cell(self, slot_name: str, contents: list[tuple[str, str, Placement]] | None = None) -> None:
        if slot_name not in self.shelf_grid:
            return
        if contents is not None:
            self.current_contents = [item for item in self.current_contents
                                     if item[2].slot_name != slot_name] + list(contents)
        self.shelf_grid.set_count(slot_name, sum(p.slot_name == slot_name for _, _, p in self.current_contents))
        if self.selected_address is not None and self.selected_address.slot_name == slot_name:
            self._refresh_contents()

    def _refresh_contents(self) -> None:
        tree = self.contents_tree
        if self.selected_address is None:
            sync_tree_rows(tree, [])
            self.selection_text.set("No cell selected")
            return
        visible = [
            (product_id, product_name, placement)
            for product_id, product_name, placement in self.current_contents
            if placement.slot_name == self.selected_address.slot_name
        ]
        searched_query = normalize_sku(self.search_var.get().strip())
        target_item = None
        rows = []
        for product_id, product_name, placement in visible:
            item_id = f"product::{product_id}"
            rows.append((
                item_id,
                (
                    product_id,
                    product_name,
                    placement.stock_qty
                    if placement.stock_qty is not None
                    else "Unknown",
                ),
                (),
            ))
            if searched_query and product_id == searched_query:
                target_item = item_id

        sync_tree_rows(tree, rows)
        if target_item:
            tree.selection_set(target_item)
            tree.see(target_item)

        count = len(visible)
        address = self.selected_address
        short_address = (
            f"{address.side}{address.shelf_code}"
            f"{address.row_number}-{address.slot_number}"
        )
        self.selection_text.set(
            f"{short_address} · {count} product{'s' if count != 1 else ''}"
        )


class CellTransferView(ttk.Frame):
    """Fifth tab: select two committed cells and switch or combine them."""

    def __init__(
        self,
        parent: tk.Misc,
        database: WarehouseDatabase,
        on_changed: Callable[[str, list[LocationUpdate], tuple[str, str]], object],
        can_change: Callable[[], bool],
        on_modify_web: Callable[[list[LocationUpdate]], object] | None = None,
        barcode_scanner: BarcodeScanner | None = None,
    ) -> None:
        super().__init__(parent, padding=10)
        self.database = database
        self.on_changed = on_changed
        self.can_change = can_change
        self.on_modify_web = on_modify_web
        self.last_changed_updates: list[LocationUpdate] = []

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

        self.left = CellTransferPane(
            workspace, "Left cell", database, barcode_scanner=barcode_scanner
        )
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
        ttk.Separator(actions).pack(fill="x", pady=8)
        self.modify_location_button = ttk.Button(
            actions,
            text="Modify location ID on web",
            command=self.modify_location_on_web,
        )
        self.modify_location_button.pack(fill="x", pady=2)
        ttk.Separator(actions).pack(fill="x", pady=8)
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

        self.right = CellTransferPane(
            workspace, "Right cell", database, barcode_scanner=barcode_scanner
        )
        self.right.grid(row=0, column=2, sticky="nsew")

        self.last_active_pane: CellTransferPane = self.left
        self.left.on_focus_callback = self._set_active_pane
        self.right.on_focus_callback = self._set_active_pane
        self.barcode_scanner = barcode_scanner

    def _set_active_pane(self, pane: CellTransferPane) -> None:
        self.last_active_pane = pane

    def on_barcode_scan(self, barcode: str) -> None:
        target = self.last_active_pane if self.last_active_pane is not None else self.left
        target._set_and_select_search(normalize_sku(barcode))
        target.find()

    def focus_search(self) -> None:
        target = self.last_active_pane if self.last_active_pane is not None else self.left
        target._select_search_entry(target.search_entry)

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
        left_products: list[str] = []
        right_products: list[str] = []
        try:
            raw_left = self.database.get_slot_contents(left.slot_id)
            if isinstance(raw_left, (list, tuple)):
                left_products = [pid for pid, _, _ in raw_left]
        except Exception:
            pass
        try:
            raw_right = self.database.get_slot_contents(right.slot_id)
            if isinstance(raw_right, (list, tuple)):
                right_products = [pid for pid, _, _ in raw_right]
        except Exception:
            pass

        try:
            left_count, right_count = self.database.swap_slot_contents(
                left.slot_id,
                right.slot_id,
            )
            self.last_changed_updates = (
                [LocationUpdate(pid, right.slot_name) for pid in left_products] +
                [LocationUpdate(pid, left.slot_name) for pid in right_products]
            )
        except Exception as error:
            messagebox.showerror("Cells could not be switched", str(error), parent=self)
            return
        message = (
            f"Switched {left.slot_name} ({left_count}) with "
            f"{right.slot_name} ({right_count})."
        )
        self.on_changed(message, self.last_changed_updates, (left.slot_name, right.slot_name))
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
        source_products: list[str] = []
        target_products: list[str] = []
        try:
            raw_source = self.database.get_slot_contents(source_address.slot_id)
            raw_target = self.database.get_slot_contents(target_address.slot_id)
            if isinstance(raw_source, (list, tuple)):
                source_products = [pid for pid, _, _ in raw_source]
            if isinstance(raw_target, (list, tuple)):
                target_products = [pid for pid, _, _ in raw_target]
        except Exception as error:
            messagebox.showerror("Cells could not be loaded", str(error), parent=self)
            return
        overlaps = sorted(set(source_products) & set(target_products))
        if overlaps:
            dialog = DuplicateCellMergeDialog(self, overlaps, target_address.slot_name)
            if not dialog.result:
                self.status_text.set("Discarded cell move. Both cells are unchanged.")
                return
        elif not messagebox.askyesno(
            "Combine complete cell contents?",
            f"Move all {source_count} product(s) from {source_address.slot_name} "
            f"into {target_address.slot_name}?\n\n"
            f"The target's {target.selected_product_count} current product(s) will remain.",
            parent=self,
        ):
            return
        try:
            if overlaps:
                moved = self.database.combine_slot_contents(
                    source_address.slot_id, target_address.slot_id, merge_duplicates=True,
                )
            else:
                moved = self.database.combine_slot_contents(
                    source_address.slot_id, target_address.slot_id,
                )
            self.last_changed_updates = [
                LocationUpdate(pid, target_address.slot_name) for pid in source_products
            ]
        except Exception as error:
            messagebox.showerror("Cells could not be combined", str(error), parent=self)
            return
        message = (
            f"Combined {moved} product(s) from {source_address.slot_name} "
            f"into {target_address.slot_name}."
        )
        self.on_changed(
            message, self.last_changed_updates,
            (source_address.slot_name, target_address.slot_name),
        )
        self.status_text.set(message)

    def modify_location_on_web(self) -> None:
        if not self.last_changed_updates:
            messagebox.showinfo(
                "No changed products",
                "No recent cell changes to modify on web. Please switch or combine cells first.",
                parent=self,
            )
            return
        if self.on_modify_web is not None:
            self.on_modify_web(self.last_changed_updates)
        else:
            messagebox.showinfo(
                "Web sync unavailable",
                "Web modification handler is not configured.",
                parent=self,
            )


"""Application controller for shelf design, persistent queues, and web updates.

Layout lists remain ordered from the ground upward; views alone translate them
to screen coordinates. Address assignments are committed immediately, while
shelf-structure edits still use the explicit Commit action on tab 1.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .assignment_view import StockQuantityDialog
from .cell_transfer_view import CellTransferView
from mapper.common import (
    APP_TITLE,
    MAX_VISIBLE_PRODUCTS,
    application_directory,
    clean_location_segment,
    make_slot_name,
    normalize_search,
)
from mapper.csv_import import read_csv
from .csv_dialog import ColumnMappingDialog
from mapper.database import (
    LayoutConflictError,
    OnHandProduct,
    Placement,
    ReturnedQueueProduct,
    SlotAddress,
    WarehouseDatabase,
    validate_stock_quantity,
)
from .designer import ShelfDesigner
from .location_assignment_view import LocationAssignmentView
from .lookup_view import ProductLookupView
from .primal_queue_view import PrimalQueueView
from .shelf_browser import ShelfBrowserView
from mapper.web_upload import LocationUpdate, UploadProduct, WebsiteUploader


class WarehouseMapperApp:
    def __init__(self, root: tk.Tk, database_path: Path | None = None):
        self.root = root
        self.database = WarehouseDatabase(
            database_path or application_directory() / "warehouse_locations.db"
        )
        self.products: dict[str, str] = {}
        self.product_shortened_names: dict[str, str] = {}
        self.product_search: dict[str, str] = {}
        self.catalog_products: dict[str, tuple[str, str]] = {}
        self.catalog_search: dict[str, str] = {}
        self.committed_locations: dict[str, str] = {}
        self.committed_placements: dict[str, Placement] = {}
        self.on_hand_products: dict[str, OnHandProduct] = {}
        self.returned_queue_products: dict[str, ReturnedQueueProduct] = {}
        self.selected_address: SlotAddress | None = None
        self.staged_assignments: dict[str, Placement] = {}
        self.pending_unassignments: set[str] = set()
        # Presence means the product is intentionally back in the working
        # queue. None preserves that intent for legacy products with unknown stock.
        self.transferred_stock: dict[str, int | None] = {}
        self.current_layout: list[int] = []
        self.preview_key: tuple[str, str, str] | None = None
        self.current_shelf_id: int | None = None
        self.selected_slot: str | None = None
        self.shelf_choices: dict[str, int] = {}
        self.search_after_id: str | None = None
        self.website_uploader = WebsiteUploader()
        self.chrome_connected = False
        self.chrome_connect_busy = False
        self.chrome_connect_after_id: str | None = None
        self.chrome_connect_events: Queue = Queue()
        self.web_upload_busy = False
        self.web_upload_action = "upload"
        self.web_upload_after_id: str | None = None
        self.web_upload_events: Queue = Queue()

        self._configure_window()
        self._build_ui()
        self.reload_database_state(reload_catalog=True)
        self.saved_editor_state = self._editor_state()

    def _configure_window(self) -> None:
        self.root.title(APP_TITLE)
        self.root.geometry("1320x820")
        self.root.minsize(1050, 650)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")

            def fixed_map(option: str) -> list:
                return [
                    elm
                    for elm in style.map("Treeview", query_opt=option)
                    if elm[:2] != ("!disabled", "!selected")
                ]

            style.map(
                "Treeview",
                foreground=fixed_map("foreground"),
                background=fixed_map("background"),
            )
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Heading.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure(
            "Commit.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 7)
        )

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(12, 10))
        self.toolbar = toolbar
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text=APP_TITLE, style="Title.TLabel").pack(side="left")
        ttk.Label(
            toolbar,
            text="Shelf design · address assignment · primal queue · shelf browser · cell moves",
            foreground="#555555",
        ).pack(side="left", padx=(16, 0))

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self.designer_tab = ttk.Frame(self.notebook)
        designer_controls = ttk.Frame(self.designer_tab, padding=(12, 8))
        designer_controls.pack(fill="x")
        ttk.Button(
            designer_controls,
            text="Import working products CSV",
            command=self.import_csv,
        ).pack(side="left")
        ttk.Button(
            designer_controls,
            text="Import full catalog CSV",
            command=self.import_catalog_csv,
        ).pack(side="left", padx=(6, 14))
        ttk.Button(designer_controls, text="New shelf", command=self.new_shelf).pack(
            side="left"
        )
        ttk.Label(designer_controls, text="Edit existing shelf:").pack(
            side="left", padx=(14, 5)
        )
        self.shelf_selector = ttk.Combobox(
            designer_controls,
            state="readonly",
            width=30,
        )
        self.shelf_selector.pack(side="left")
        ttk.Button(
            designer_controls,
            text="Load for editing",
            command=self.load_selected_shelf,
        ).pack(side="left", padx=(5, 0))
        ttk.Button(
            designer_controls,
            text="Commit shelf design",
            style="Commit.TButton",
            command=self.commit_changes,
        ).pack(side="right")

        self.designer = ShelfDesigner(
            self.designer_tab,
            self.build_shelf_preview,
            self.can_resize_rows,
            self.on_rows_changed,
        )
        self.designer.pack(fill="both", expand=True)
        self.assignments = LocationAssignmentView(
            self.notebook,
            on_search=self.schedule_queue_refresh,
            on_queue_to_hand=self.move_selected_to_on_hand,
            on_catalog_to_queue=self.transfer_catalog_selection_to_queue,
            on_catalog_activate=self.activate_catalog_product,
            on_load_address=self.load_assignment_address,
            on_assign_address=self.assign_on_hand_to_address,
            on_dequeue_hand=self.dequeue_selected_on_hand,
            on_selected_to_hand=self.move_selected_address_to_on_hand,
            on_slot_to_hand=self.move_address_to_on_hand,
            on_modify_hand_stock=self.modify_on_hand_stock,
            on_modify_stock=self.modify_selected_stock,
            on_upload=self.upload_selected_product,
            on_modify_location=self.modify_selected_location,
            on_connect_chrome=self.connect_chrome,
        )
        self.connect_chrome_button = self.assignments.connect_chrome_button
        self.notebook.add(self.designer_tab, text="1. Shelf Designer")
        self.notebook.add(self.assignments, text="2. Assign Locations")
        self.primal_view = PrimalQueueView(self.notebook, self.database)
        self.lookup = self.primal_view
        self.notebook.add(self.primal_view, text="3. Primal Queue / Shelves")
        self.shelf_browser = ShelfBrowserView(self.notebook, self.database)
        self.notebook.add(self.shelf_browser, text="4. Browse Shelves")
        self.cell_transfer = CellTransferView(
            self.notebook,
            self.database,
            self.on_cell_transfer_changed,
            self.can_change_cells,
            on_modify_web=self.modify_cell_transfer_locations,
        )
        self.notebook.add(self.cell_transfer, text="5. Switch / Combine Cells")
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        self.status_text = tk.StringVar(value="Ready")
        ttk.Label(
            self.root,
            textvariable=self.status_text,
            relief="sunken",
            anchor="w",
            padding=(8, 3),
        ).pack(fill="x", side="bottom")

    def on_tab_changed(self, _event=None) -> None:
        if hasattr(self, "primal_view") and self.notebook.select() == str(self.primal_view):
            self.primal_view.refresh()
        elif self.notebook.select() == str(self.shelf_browser):
            if self.shelf_browser.current_shelf_id is None:
                self.shelf_browser.refresh()
            else:
                self.shelf_browser.show_saved_shelf(self.shelf_browser.current_shelf_id)
        elif self.notebook.select() == str(self.cell_transfer):
            self.cell_transfer.refresh()

    def on_cell_transfer_changed(self, message: str) -> None:
        """Synchronize every other tab after an immediate cell operation."""
        self.reload_database_state()
        self.status_text.set(message)

    def can_change_cells(self) -> bool:
        if not self.has_pending_changes():
            return True
        messagebox.showinfo(
            "Finish pending shelf changes",
            "Commit or discard the pending Shelf Designer changes before switching "
            "or combining saved cells.",
            parent=self.root,
        )
        return False

    def _editor_state(self) -> tuple:
        return (
            self.designer.floor_var.get(),
            self.designer.side_var.get(),
            self.designer.shelf_code_var.get(),
            self.designer.row_count_var.get(),
            tuple(count.get() for count in self.designer.row_inputs),
        )

    def _slots_are_empty(self, removed_slots: set[str]) -> bool:
        """Check the working placements before removing any rows or cells."""
        locations = {
            product_id: slot
            for product_id, slot in self.committed_locations.items()
            if product_id not in self.pending_unassignments
        }
        locations.update(
            {
                product_id: placement.slot_name
                for product_id, placement in self.staged_assignments.items()
            }
        )
        occupied = sorted(
            {slot for slot in locations.values() if slot in removed_slots}
        )
        if occupied:
            messagebox.showerror(
                "Rows or cells still contain products",
                f"Return or move the products in {occupied[0]} before removing this row or cell.",
            )
            return False
        return True

    def can_resize_rows(self, row_count: int) -> bool:
        if not self.preview_key:
            return True
        floor, side, shelf_code = self.preview_key
        removed_slots = {
            make_slot_name(floor, shelf_code, row_number, cell, side=side)
            for row_number, count in enumerate(self.current_layout, start=1)
            if row_number > row_count
            for cell in range(1, count + 1)
        }
        return self._slots_are_empty(removed_slots)

    def on_rows_changed(self) -> None:
        if self.preview_key:
            self.build_shelf_preview(switch_tab=False)

    def build_shelf_preview(self, *, switch_tab: bool = True) -> bool:
        validated = self.designer.validated_layout()
        if validated is None:
            return False
        floor, side, shelf_code, layout = validated
        new_key = (floor, side, shelf_code)
        existing_id = self.database.get_shelf_id(floor, shelf_code, side=side)
        if existing_id is not None and existing_id != self.current_shelf_id:
            messagebox.showerror(
                "Shelf already exists",
                f"Floor {floor} / Side {side} / Shelf {shelf_code} already exists. "
                "Select it under Existing shelf and press Load.",
            )
            return False
        new_slots = {
            (row_number, cell): make_slot_name(
                floor, shelf_code, row_number, cell, side=side
            )
            for row_number, count in enumerate(layout, start=1)
            for cell in range(1, count + 1)
        }
        valid_slots = set(new_slots.values())
        if len(valid_slots) != len(new_slots):
            messagebox.showerror(
                "Duplicate location IDs",
                "Use a shelf code that gives each cell a distinct ID.",
            )
            return False
        if self.preview_key:
            old_floor, old_side, old_code = self.preview_key
            old_slots = {
                (row_number, cell): make_slot_name(
                    old_floor, old_code, row_number, cell, side=old_side
                )
                for row_number, count in enumerate(self.current_layout, start=1)
                for cell in range(1, count + 1)
            }
            removed = {
                name
                for coordinate, name in old_slots.items()
                if coordinate not in new_slots
            }
            if not self._slots_are_empty(removed):
                return False
            if new_key != self.preview_key:
                renamed = {
                    name: new_slots[coordinate]
                    for coordinate, name in old_slots.items()
                    if coordinate in new_slots
                }
                self.staged_assignments = {
                    product_id: Placement(
                        renamed.get(item.slot_name, item.slot_name),
                        item.stock_qty,
                        item.assigned_at,
                    )
                    for product_id, item in self.staged_assignments.items()
                }
                if self.current_shelf_id is not None:
                    # These are working display caches. Tab 3 reads the database
                    # independently and keeps showing saved metadata until Commit.
                    self.committed_placements = {
                        product_id: Placement(
                            renamed.get(item.slot_name, item.slot_name),
                            item.stock_qty,
                            item.assigned_at,
                        )
                        for product_id, item in self.committed_placements.items()
                    }
                    self.committed_locations = {
                        product_id: item.slot_name
                        for product_id, item in self.committed_placements.items()
                    }
                self.selected_slot = renamed.get(self.selected_slot, self.selected_slot)

        self.current_layout = layout
        self.preview_key = new_key
        if self.selected_slot not in valid_slots:
            self.selected_slot = None
        self.refresh_all_views()
        self.render_shelf()
        if switch_tab:
            self.notebook.select(self.shelf_browser)
        self.status_text.set(
            "Shelf preview updated. Commit on tab 1 to save its design."
        )
        return True

    def render_shelf(self) -> None:
        floor, side, shelf_code = self.preview_key or ("", "", "")
        if not hasattr(self, "shelf_browser"):
            return
        valid_slots = {
            make_slot_name(floor, shelf_code, row_number, cell, side=side)
            for row_number, count in enumerate(self.current_layout, start=1)
            for cell in range(1, count + 1)
        }
        contents = [
            (product_id, self.products.get(product_id, ""), placement)
            for product_id, placement in self.committed_placements.items()
            if placement.slot_name in valid_slots
            and product_id not in self.pending_unassignments
        ]
        contents.extend(
            (product_id, self.products.get(product_id, ""), placement)
            for product_id, placement in self.staged_assignments.items()
            if placement.slot_name in valid_slots
        )
        self.shelf_browser.show_preview(
            floor,
            side,
            shelf_code,
            self.current_layout,
            contents,
        )

    def select_slot(self, slot_name: str) -> None:
        self.selected_slot = slot_name
        if hasattr(self.assignments, "mark_selected"):
            self.assignments.mark_selected(slot_name)
            self.refresh_slot_contents()

    def visible_slot_counts(self) -> dict[str, tuple[int, int]]:
        saved: dict[str, int] = {}
        staged: dict[str, int] = {}
        for product_id, slot_name in self.committed_locations.items():
            if (
                product_id not in self.pending_unassignments
                and product_id not in self.staged_assignments
            ):
                saved[slot_name] = saved.get(slot_name, 0) + 1
        for placement in self.staged_assignments.values():
            slot_name = placement.slot_name
            staged[slot_name] = staged.get(slot_name, 0) + 1
        return {
            slot_name: (saved.get(slot_name, 0), staged.get(slot_name, 0))
            for slot_name in set(saved) | set(staged)
        }

    def move_selected_to_on_hand(self) -> None:
        selected_items = self.assignments.queue_tree.selection()
        product_ids = [
            item_id.removeprefix("product::")
            for item_id in selected_items
            if item_id.startswith("product::")
            and item_id.removeprefix("product::") in self.products
        ]
        if not product_ids:
            messagebox.showinfo(
                "Choose products",
                "Select one or more products from the total queue first.",
                parent=self.root,
            )
            return

        dialog = StockQuantityDialog(
            self.root,
            "On-hand queue",
            [(product_id, self.products[product_id]) for product_id in product_ids],
            initial_quantities={
                product_id: self.returned_queue_products[product_id].stock_qty
                for product_id in product_ids
                if product_id in self.returned_queue_products
            },
            title_text="Move products to on-hand",
            destination_label="Persistent on-hand batch",
            button_text="Move to on-hand",
            footer_text="This move is saved to SQLite immediately.",
        )
        self.root.wait_window(dialog)
        if dialog.result is None:
            return

        queued_at = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            self.database.add_to_on_hand(dialog.result, queued_at)
        except Exception as error:
            messagebox.showerror(
                "Could not update on-hand", str(error), parent=self.root
            )
            return
        self.reload_database_state()
        self.refresh_all_views()
        self.status_text.set(
            f"Moved {len(dialog.result)} product(s) to on-hand. Saved immediately."
        )

    def refresh_on_hand_queue(self) -> None:
        if not hasattr(self.assignments, "on_hand_tree"):
            return
        tree = self.assignments.on_hand_tree
        tree.delete(*tree.get_children())
        for product_id, item in self.on_hand_products.items():
            tree.insert(
                "",
                "end",
                iid=f"hand::{product_id}",
                values=(
                    product_id,
                    self.products.get(product_id, ""),
                    item.stock_qty if item.stock_qty is not None else "Unknown",
                ),
            )
        self.assignments.on_hand_count_text.set(
            f"{len(self.on_hand_products):,} product(s) ready to assign"
        )

    def modify_on_hand_stock(self) -> None:
        selected = self.assignments.on_hand_tree.selection()
        if len(selected) != 1 or not selected[0].startswith("hand::"):
            messagebox.showinfo(
                "Choose one product",
                "Select exactly one product in the on-hand queue.",
                parent=self.root,
            )
            return
        product_id = selected[0].removeprefix("hand::")
        item = self.on_hand_products.get(product_id)
        if item is None:
            self.reload_database_state()
            self.refresh_all_views()
            return
        quantity = simpledialog.askinteger(
            "Modify on-hand stock",
            f"Product: {product_id}\nCurrent stock: "
            f"{item.stock_qty if item.stock_qty is not None else 'Unknown'}\n\n"
            "Enter the new whole-number quantity:",
            parent=self.root,
            initialvalue=item.stock_qty if item.stock_qty is not None else 0,
            minvalue=0,
            maxvalue=9_223_372_036_854_775_807,
        )
        if quantity is None:
            return
        try:
            self.database.update_on_hand_stock(product_id, quantity)
        except Exception as error:
            messagebox.showerror(
                "Stock could not be updated", str(error), parent=self.root
            )
            return
        self.reload_database_state()
        self.refresh_all_views()
        self.status_text.set(f"Updated on-hand stock for {product_id} to {quantity}.")

    def _read_address_inputs(self) -> tuple[str, str, str, int, int] | None:
        floor = clean_location_segment(self.assignments.floor_var.get())
        side = clean_location_segment(self.assignments.side_var.get())
        shelf_code = clean_location_segment(self.assignments.shelf_var.get())
        if not floor or not side or not shelf_code:
            messagebox.showinfo(
                "Incomplete address",
                "Enter floor, side, and shelf code.",
                parent=self.root,
            )
            return None
        try:
            row_number = int(self.assignments.row_var.get())
            slot_number = int(self.assignments.cell_var.get())
        except ValueError:
            messagebox.showinfo(
                "Invalid address",
                "Row and cell must be positive whole numbers.",
                parent=self.root,
            )
            return None
        if row_number < 1 or slot_number < 1:
            messagebox.showinfo(
                "Invalid address",
                "Row and cell must be positive whole numbers.",
                parent=self.root,
            )
            return None
        return floor, side, shelf_code, row_number, slot_number

    def load_assignment_address(self) -> None:
        address_parts = self._read_address_inputs()
        if address_parts is None:
            return
        address = self.database.get_slot_address(*address_parts)
        if address is None:
            floor, side, shelf_code, row_number, slot_number = address_parts
            self.selected_address = None
            self.assignments.selected_slot_text.set("No valid address loaded")
            self.assignments.address_status_text.set(
                f"No saved cell at Floor {floor} / Side {side} / Shelf {shelf_code} / "
                f"Row {row_number} / Cell {slot_number}."
            )
            self.assignments.contents_tree.delete(
                *self.assignments.contents_tree.get_children()
            )
            return
        self.selected_address = address
        self.refresh_address_contents()
        self.status_text.set(f"Loaded {address.slot_name}.")

    def refresh_address_contents(self) -> None:
        if not hasattr(self.assignments, "contents_tree") or not hasattr(
            self.assignments, "address_status_text"
        ):
            return
        tree = self.assignments.contents_tree
        tree.delete(*tree.get_children())
        if self.selected_address is None:
            self.assignments.selected_slot_text.set("No address loaded")
            return
        address = self.selected_address
        current_address = self.database.get_slot_address(
            address.floor,
            address.side,
            address.shelf_code,
            address.row_number,
            address.slot_number,
        )
        if current_address is None or current_address.slot_id != address.slot_id:
            self.selected_address = None
            self.assignments.selected_slot_text.set("No address loaded")
            self.assignments.address_status_text.set(
                "The loaded address changed or was removed. Enter and load it again."
            )
            return
        address = current_address
        self.selected_address = current_address
        contents = self.database.get_slot_contents(address.slot_id)
        self.assignments.selected_slot_text.set(address.slot_name)
        self.assignments.address_status_text.set(
            f"Loaded {address.slot_name} · {len(contents)} product(s)"
        )
        for product_id, product_name, placement in contents:
            tree.insert(
                "",
                "end",
                iid=f"saved::{product_id}",
                values=(
                    product_id,
                    product_name,
                    placement.stock_qty
                    if placement.stock_qty is not None
                    else "Unknown",
                    placement.assigned_at.replace("T", " ")
                    if placement.assigned_at
                    else "Unknown",
                ),
            )

    def assign_on_hand_to_address(self) -> None:
        if self.selected_address is None:
            messagebox.showinfo(
                "Load an address",
                "Enter the shelf address and press Load address first.",
                parent=self.root,
            )
            return
        selected_items = self.assignments.on_hand_tree.selection()
        product_ids = [
            item_id.removeprefix("hand::")
            for item_id in selected_items
            if item_id.startswith("hand::")
            and item_id.removeprefix("hand::") in self.on_hand_products
        ]
        if not product_ids:
            messagebox.showinfo(
                "Choose on-hand products",
                "Select one or more on-hand products with Ctrl-click first.",
                parent=self.root,
            )
            return
        address = self.selected_address
        assigned_at = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            moved = self.database.assign_on_hand_to_slot(
                address.slot_id,
                assigned_at,
                product_ids,
            )
        except Exception as error:
            messagebox.showerror("Assignment failed", str(error), parent=self.root)
            return
        self.reload_database_state()
        self.refresh_all_views()
        if hasattr(self, "shelf_browser"):
            self.shelf_browser.refresh()
        self.status_text.set(
            f"Assigned {moved} product(s) to {address.slot_name}. Saved immediately."
        )

    def dequeue_selected_on_hand(self) -> None:
        selected_items = self.assignments.on_hand_tree.selection()
        product_ids = [
            item_id.removeprefix("hand::")
            for item_id in selected_items
            if item_id.startswith("hand::")
            and item_id.removeprefix("hand::") in self.on_hand_products
        ]
        if not product_ids:
            messagebox.showinfo(
                "Choose on-hand products",
                "Select one or more on-hand products with Ctrl-click first.",
                parent=self.root,
            )
            return
        returned_at = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            moved = self.database.dequeue_on_hand(product_ids, returned_at)
        except Exception as error:
            messagebox.showerror(
                "Could not dequeue products", str(error), parent=self.root
            )
            return
        self.reload_database_state()
        self.refresh_all_views()
        self.status_text.set(
            f"Returned {moved} selected product(s) to the total queue with stock retained."
        )

    def move_address_to_on_hand(self) -> None:
        if self.selected_address is None:
            messagebox.showinfo(
                "Load an address",
                "Enter the shelf address and press Load address first.",
                parent=self.root,
            )
            return
        address = self.selected_address
        contents = self.database.get_slot_contents(address.slot_id)
        if not contents:
            self.status_text.set(f"{address.slot_name} is already empty.")
            return
        if not messagebox.askyesno(
            "Move shelf contents to on-hand?",
            f"Move all {len(contents)} product(s) from {address.slot_name} to on-hand?",
            parent=self.root,
        ):
            return
        queued_at = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            moved = self.database.move_slot_to_on_hand(address.slot_id, queued_at)
        except Exception as error:
            messagebox.showerror("Transfer failed", str(error), parent=self.root)
            return
        self.reload_database_state()
        self.refresh_all_views()
        if hasattr(self, "shelf_browser"):
            self.shelf_browser.refresh()
        self.status_text.set(
            f"Moved {moved} product(s) from {address.slot_name} to on-hand."
        )

    def move_selected_address_to_on_hand(self) -> None:
        if self.selected_address is None:
            messagebox.showinfo(
                "Load an address",
                "Enter the shelf address and press Load address first.",
                parent=self.root,
            )
            return
        selected_items = self.assignments.contents_tree.selection()
        product_ids = [
            item_id.removeprefix("saved::")
            for item_id in selected_items
            if item_id.startswith("saved::")
        ]
        if not product_ids:
            messagebox.showinfo(
                "Choose shelf products",
                "Select one or more products in the loaded address with Ctrl-click first.",
                parent=self.root,
            )
            return

        address = self.selected_address
        queued_at = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            moved = self.database.move_slot_to_on_hand(
                address.slot_id,
                queued_at,
                product_ids,
            )
        except Exception as error:
            messagebox.showerror("Transfer failed", str(error), parent=self.root)
            return
        self.reload_database_state()
        self.refresh_all_views()
        if hasattr(self, "shelf_browser"):
            self.shelf_browser.refresh()
        self.status_text.set(
            f"Moved {moved} selected product(s) from {address.slot_name} to on-hand."
        )

    def assign_selected_products(self) -> None:
        if not self.selected_slot:
            messagebox.showinfo("Choose a slot", "Click a shelf slot first.")
            return
        selected_items = self.assignments.queue_tree.selection()
        if not selected_items:
            messagebox.showinfo(
                "Choose products", "Select one or more products from the queue."
            )
            return

        slot_name = self.selected_slot
        product_ids = [item_id.removeprefix("product::") for item_id in selected_items]
        initial_quantities = {
            product_id: self.transferred_stock.get(product_id)
            for product_id in product_ids
        }
        dialog = StockQuantityDialog(
            self.root,
            slot_name,
            [
                (product_id, self.products.get(product_id, ""))
                for product_id in product_ids
            ],
            initial_quantities=initial_quantities,
        )
        self.root.wait_window(dialog)
        if dialog.result is None:
            return

        # Confirming quantities is the assignment action. Commit must persist
        # this captured value, even if the shelf is saved much later.
        assigned_at = datetime.now().astimezone().isoformat(timespec="seconds")
        for product_id, quantity in dialog.result.items():
            self.staged_assignments[product_id] = Placement(
                slot_name, quantity, assigned_at
            )
            self.transferred_stock.pop(product_id, None)

        self.refresh_all_views()
        self.status_text.set(
            f"Staged {len(selected_items)} product(s) in {self.selected_slot}. Press Commit to save."
        )

    def refresh_slot_contents(self) -> None:
        self.assignments.contents_tree.delete(
            *self.assignments.contents_tree.get_children()
        )
        if not self.selected_slot:
            self.assignments.selected_slot_text.set("No slot selected")
            return

        saved_products = [
            product_id
            for product_id, slot_name in self.committed_locations.items()
            if slot_name == self.selected_slot
            and product_id not in self.pending_unassignments
            and product_id not in self.staged_assignments
        ]
        staged_products = [
            product_id
            for product_id, placement in self.staged_assignments.items()
            if placement.slot_name == self.selected_slot
        ]
        visible_products = [
            ("Saved", product_id, self.committed_placements[product_id])
            for product_id in saved_products
        ] + [
            ("Staged", product_id, self.staged_assignments[product_id])
            for product_id in staged_products
        ]

        def oldest_first(item):
            assigned_at = item[2].assigned_at
            try:
                timestamp = (
                    datetime.fromisoformat(assigned_at).timestamp()
                    if assigned_at
                    else float("-inf")
                )
            except (TypeError, ValueError, OverflowError, OSError):
                timestamp = float("-inf")
            return timestamp, item[1].casefold()

        for state, product_id, placement in sorted(visible_products, key=oldest_first):
            self.assignments.contents_tree.insert(
                "",
                "end",
                iid=f"{state.lower()}::{product_id}",
                values=(
                    product_id,
                    self.products.get(product_id, ""),
                    placement.stock_qty
                    if placement.stock_qty is not None
                    else "Unknown",
                    placement.assigned_at.replace("T", " ")
                    if placement.assigned_at
                    else "Unknown",
                    state,
                ),
            )

    def modify_selected_stock(self) -> None:
        if getattr(self, "selected_address", None) is not None and hasattr(
            self.assignments, "on_hand_tree"
        ):
            self._modify_loaded_address_stock()
            return

        selected = self.assignments.contents_tree.selection()
        if len(selected) != 1:
            messagebox.showinfo(
                "Choose one product",
                "Select exactly one product in Selected slot contents, then press Modify selected stock.",
                parent=self.root,
            )
            return

        state, separator, product_id = selected[0].partition("::")
        if (
            not separator
            or state not in {"staged", "saved"}
            or product_id not in self.products
        ):
            messagebox.showinfo(
                "Choose one product",
                "Select a current product from the slot contents list.",
                parent=self.root,
            )
            return

        placements = (
            self.staged_assignments if state == "staged" else self.committed_placements
        )
        placement = placements.get(product_id)
        stale_saved = state == "saved" and (
            product_id in self.pending_unassignments
            or product_id in self.staged_assignments
        )
        if (
            placement is None
            or placement.slot_name != self.selected_slot
            or stale_saved
        ):
            messagebox.showinfo(
                "Selection changed",
                "That product is no longer in the selected slot. Select it again.",
                parent=self.root,
            )
            self.refresh_slot_contents()
            return
        if not placement.assigned_at:
            messagebox.showinfo(
                "Added time is unknown",
                "This older record has no added-to-shelf time. Return it to the queue and assign it again.",
                parent=self.root,
            )
            return

        current_text = (
            placement.stock_qty if placement.stock_qty is not None else "Unknown"
        )
        quantity = simpledialog.askinteger(
            "Modify stock quantity",
            f"Product: {product_id}\nLocation: {placement.slot_name}\n"
            f"Current stock: {current_text}\n\nEnter the new whole-number quantity:",
            parent=self.root,
            initialvalue=placement.stock_qty if placement.stock_qty is not None else 0,
            minvalue=0,
            maxvalue=9_223_372_036_854_775_807,
        )
        if quantity is None:
            return
        validate_stock_quantity(quantity)
        if quantity == placement.stock_qty:
            self.status_text.set(f"{product_id} already has stock quantity {quantity}.")
            return

        self.pending_unassignments.discard(product_id)
        self.staged_assignments[product_id] = Placement(
            placement.slot_name,
            quantity,
            placement.assigned_at,
        )
        self.refresh_all_views()
        self.status_text.set(
            f"Staged stock change for {product_id}: {current_text} → {quantity}. Press Commit to save."
        )

    def _modify_loaded_address_stock(self) -> None:
        selected = self.assignments.contents_tree.selection()
        if len(selected) != 1 or not selected[0].startswith("saved::"):
            messagebox.showinfo(
                "Choose one product",
                "Select exactly one product in the loaded address contents.",
                parent=self.root,
            )
            return
        product_id = selected[0].removeprefix("saved::")
        address = self.selected_address
        contents = {
            item_id: placement
            for item_id, _name, placement in self.database.get_slot_contents(
                address.slot_id
            )
        }
        placement = contents.get(product_id)
        if placement is None:
            self.refresh_address_contents()
            messagebox.showinfo(
                "Selection changed",
                "That product is no longer in the loaded address.",
                parent=self.root,
            )
            return
        current_text = (
            placement.stock_qty if placement.stock_qty is not None else "Unknown"
        )
        quantity = simpledialog.askinteger(
            "Modify stock quantity",
            f"Product: {product_id}\nLocation: {address.slot_name}\n"
            f"Current stock: {current_text}\n\nEnter the new whole-number quantity:",
            parent=self.root,
            initialvalue=placement.stock_qty if placement.stock_qty is not None else 0,
            minvalue=0,
            maxvalue=9_223_372_036_854_775_807,
        )
        if quantity is None or quantity == placement.stock_qty:
            return
        try:
            self.database.update_placement_stock(
                product_id,
                quantity,
                expected_slot_id=address.slot_id,
            )
        except Exception as error:
            messagebox.showerror(
                "Stock could not be updated", str(error), parent=self.root
            )
            return
        self.reload_database_state()
        self.refresh_all_views()
        self.status_text.set(
            f"Updated {product_id} stock at {address.slot_name}: {current_text} → {quantity}."
        )

    def transfer_selected_products(self) -> None:
        selected_items = self.assignments.contents_tree.selection()
        if not selected_items:
            messagebox.showinfo(
                "Choose products",
                "Select one or more products in Selected slot contents, then press Transfer product.",
                parent=self.root,
            )
            return

        transferred_count = 0
        for item_id in selected_items:
            state, separator, product_id = item_id.partition("::")
            if (
                not separator
                or state not in {"staged", "saved"}
                or product_id not in self.products
            ):
                continue

            placements = (
                self.staged_assignments
                if state == "staged"
                else self.committed_placements
            )
            placement = placements.get(product_id)
            if placement is not None:
                self.transferred_stock[product_id] = placement.stock_qty

            if state == "staged":
                self.staged_assignments.pop(product_id, None)
            if product_id in self.committed_placements:
                self.pending_unassignments.add(product_id)
            transferred_count += 1

        if not transferred_count:
            messagebox.showinfo(
                "Choose products",
                "Select valid products from the slot contents list.",
                parent=self.root,
            )
            return

        self.refresh_all_views()
        self.status_text.set(
            f"Transferred {transferred_count} product(s) to queue with stock retained. Select a new slot to assign."
        )

    def activate_catalog_product(self, event) -> str | None:
        tree = self.assignments.catalog_tree
        item_id = tree.identify_row(event.y)
        if not item_id.startswith("catalog::"):
            return None

        product_id = item_id.removeprefix("catalog::")
        if product_id not in self.catalog_products:
            return None

        tree.selection_set(item_id)
        tree.focus(item_id)
        placement = self.staged_assignments.get(
            product_id
        ) or self.committed_placements.get(product_id)
        self.assignments._set_and_select_search(
            self.assignments.search_var,
            self.assignments.search_entry,
            product_id,
        )
        self.refresh_product_lists()
        if placement is not None:
            self.status_text.set(
                f"{product_id} is already at {placement.slot_name}. No queue transfer was staged."
            )
        else:
            self.status_text.set(
                f"Searched for {product_id}. It has no assigned location; no queue transfer was staged."
            )
        return "break"

    def transfer_catalog_selection_to_queue(self) -> None:
        selected_items = self.assignments.catalog_tree.selection()
        product_ids = [
            item_id.removeprefix("catalog::")
            for item_id in selected_items
            if item_id.startswith("catalog::")
            and item_id.removeprefix("catalog::") in self.catalog_products
        ]
        if not product_ids:
            messagebox.showinfo(
                "Choose catalog products",
                "Select one or more products from the full catalog first.",
                parent=self.root,
            )
            return

        existing_products = set(self.products)
        records = {
            product_id: self.catalog_products[product_id] for product_id in product_ids
        }
        try:
            self.database.import_products(records)
        except Exception as error:
            messagebox.showerror("Transfer failed", str(error), parent=self.root)
            return

        if hasattr(self.assignments, "on_hand_tree"):
            staged_stock: dict[str, int | None] = {}
            for product_id in product_ids:
                staged = self.staged_assignments.pop(product_id, None)
                if staged is not None:
                    staged_stock[product_id] = staged.stock_qty
                    if staged.stock_qty is not None:
                        self.transferred_stock[product_id] = staged.stock_qty
                self.pending_unassignments.discard(product_id)

            # Sync transferred_stock for any products currently placed on a shelf
            for product_id in product_ids:
                saved = self.committed_placements.get(product_id)
                if saved is not None and saved.stock_qty is not None:
                    self.transferred_stock[product_id] = saved.stock_qty

            returned_at = datetime.now().astimezone().isoformat(timespec="seconds")
            try:
                pulled_placements, pulled_on_hand = self.database.force_pull_to_queue(
                    product_ids,
                    returned_at,
                    extra_stock=staged_stock,
                )
            except Exception as error:
                messagebox.showerror("Transfer failed", str(error), parent=self.root)
                return

            new_products = sum(
                product_id not in existing_products for product_id in product_ids
            )
            already_waiting = (
                len(product_ids)
                - new_products
                - pulled_placements
                - pulled_on_hand
                - len(staged_stock)
            )
            if already_waiting < 0:
                already_waiting = 0

            self.reload_database_state(reload_catalog=True)
            self.refresh_all_views()
            if hasattr(self, "shelf_browser"):
                self.shelf_browser.refresh()

            summary: list[str] = []
            if new_products:
                summary.append(f"{new_products} added to queue")
            if pulled_placements:
                summary.append(f"{pulled_placements} pulled from shelf")
            if pulled_on_hand:
                summary.append(f"{pulled_on_hand} pulled from on-hand")
            if staged_stock:
                summary.append(f"{len(staged_stock)} pulled from staged slot")
            if already_waiting:
                summary.append(f"{already_waiting} already in queue")

            self.status_text.set(
                f"Catalog transfer: {', '.join(summary) if summary else 'Done'}. Product(s) ready in total queue."
            )
            return

        new_products = 0
        moved_assignments = 0
        already_waiting = 0
        for product_id in product_ids:
            if product_id not in existing_products:
                new_products += 1
            staged = self.staged_assignments.pop(product_id, None)
            saved = self.committed_placements.get(product_id)
            was_pending = product_id in self.pending_unassignments
            if staged is not None:
                self.transferred_stock[product_id] = staged.stock_qty
            elif saved is not None:
                self.transferred_stock[product_id] = saved.stock_qty

            if saved is not None:
                self.pending_unassignments.add(product_id)
            if staged is not None or (saved is not None and not was_pending):
                moved_assignments += 1
            elif product_id in existing_products:
                already_waiting += 1

        self.reload_database_state()
        self.refresh_all_views()

        summary = [f"{new_products} added"]
        if moved_assignments:
            summary.append(f"{moved_assignments} moved from a slot")
        if already_waiting:
            summary.append(f"{already_waiting} already in queue")
        self.status_text.set(
            "Catalog transfer: "
            + ", ".join(summary)
            + ". Catalog entries were kept. Press Commit to save slot removals."
        )

    def preassign_queue_stock(self) -> None:
        selected_items = self.assignments.queue_tree.selection()
        if not selected_items:
            messagebox.showinfo(
                "Choose products",
                "Select one or more products from the queue to pre-assign their stock.",
                parent=self.root,
            )
            return

        product_ids = [item_id.removeprefix("product::") for item_id in selected_items]
        initial_quantities = {
            product_id: self.transferred_stock.get(product_id)
            for product_id in product_ids
        }
        dialog = StockQuantityDialog(
            self.root,
            "Queue",
            [
                (product_id, self.products.get(product_id, ""))
                for product_id in product_ids
            ],
            initial_quantities=initial_quantities,
            title_text="Pre-assign stock quantity",
            destination_label="Pre-assign stock for products before choosing location",
            button_text="Save quantities",
        )
        self.root.wait_window(dialog)
        if dialog.result is None:
            return

        for product_id, quantity in dialog.result.items():
            self.transferred_stock[product_id] = quantity

        self.refresh_product_queue()
        self.status_text.set(
            f"Pre-assigned stock for {len(dialog.result)} product(s) in queue."
        )

    def connect_chrome(self) -> None:
        if self.chrome_connect_busy:
            return
        if self.web_upload_busy:
            messagebox.showinfo(
                "Upload in progress",
                "Wait for the current upload before reconnecting Chrome.",
                parent=self.root,
            )
            return

        self.chrome_connect_busy = True
        self.connect_chrome_button.configure(text="Connecting…", state="disabled")
        self.status_text.set("Connecting to the debugging Chrome session on port 9222…")
        self.chrome_connect_events = Queue()
        Thread(
            target=self._run_chrome_connect,
            args=(self.chrome_connect_events,),
            daemon=True,
        ).start()
        self.chrome_connect_after_id = self.root.after(100, self._poll_chrome_connect)

    def _run_chrome_connect(self, events: Queue) -> None:
        # This worker never calls Tkinter.
        try:
            result = self.website_uploader.connect(
                lambda text: events.put(("progress", text))
            )
        except Exception as error:
            events.put(("error", str(error)))
        else:
            events.put(("done", result))

    def _poll_chrome_connect(self) -> None:
        self.chrome_connect_after_id = None
        while True:
            try:
                event, text = self.chrome_connect_events.get_nowait()
            except Empty:
                break
            if event == "progress":
                self.status_text.set(text)
                continue

            self.chrome_connect_busy = False
            self.connect_chrome_button.configure(state="normal")
            if event == "error":
                self.chrome_connected = False
                self.connect_chrome_button.configure(text="Connect Chrome")
                self.status_text.set("Chrome connection needs attention.")
                messagebox.showerror("Connect Chrome", text, parent=self.root)
            else:
                self.chrome_connected = True
                self.connect_chrome_button.configure(text="Reconnect Chrome")
                self.assignments.upload_status_text.set(text)
                self.status_text.set(text)
            return
        if self.chrome_connect_busy:
            self.chrome_connect_after_id = self.root.after(
                100, self._poll_chrome_connect
            )

    def _selected_web_placement(self, action_name: str) -> tuple[str, Placement]:
        selected = self.assignments.contents_tree.selection()
        if len(selected) != 1:
            raise ValueError(
                f"Select exactly one product in Selected slot contents, then press {action_name}."
            )
        if getattr(self, "selected_address", None) is not None and hasattr(
            self.assignments, "on_hand_tree"
        ):
            item_id = selected[0]
            if not item_id.startswith("saved::"):
                raise ValueError(
                    "Select a current product from the loaded address contents."
                )
            product_id = item_id.removeprefix("saved::")
            address = self.selected_address
            for saved_id, _name, placement in self.database.get_slot_contents(
                address.slot_id
            ):
                if saved_id == product_id:
                    return product_id, placement
            raise ValueError(
                "That selection changed. Reload the address and select it again."
            )
        state, separator, product_id = selected[0].partition("::")
        if (
            not separator
            or state not in {"staged", "saved"}
            or product_id not in self.products
        ):
            raise ValueError("Select a current product from the slot contents list.")
        placements = (
            self.staged_assignments if state == "staged" else self.committed_placements
        )
        placement = placements.get(product_id)
        if (
            placement is None
            or placement.slot_name != self.selected_slot
            or (
                state == "saved"
                and (
                    product_id in self.pending_unassignments
                    or product_id in self.staged_assignments
                )
            )
        ):
            raise ValueError(
                "That selection changed. Select the product in its current slot again."
            )
        return product_id, placement

    def _web_batch_mode_enabled(self) -> bool:
        mode = getattr(self.assignments, "web_batch_mode_var", None)
        return bool(mode is not None and mode.get())

    def _web_placements(self, action_name: str) -> list[tuple[str, Placement]]:
        """Capture either the selected row or every row in the loaded address."""
        if not self._web_batch_mode_enabled():
            return [self._selected_web_placement(action_name)]

        address = self.selected_address
        if address is None:
            raise ValueError(
                "Load a shelf address first. All-products mode uses every product "
                "currently saved in that loaded address."
            )
        contents = self.database.get_slot_contents(address.slot_id)
        if not contents:
            raise ValueError(f"{address.slot_name} does not contain any products.")
        return [(product_id, placement) for product_id, _name, placement in contents]

    def _upload_products(self) -> list[UploadProduct]:
        placements = self._web_placements("Upload to web")
        missing_quantities = [
            product_id
            for product_id, placement in placements
            if placement.stock_qty is None
        ]
        if missing_quantities:
            preview = ", ".join(missing_quantities[:3])
            more = (
                f" and {len(missing_quantities) - 3} more"
                if len(missing_quantities) > 3
                else ""
            )
            raise ValueError(
                f"Cannot upload because {preview}{more} has no recorded quantity. "
                "Return the product to on-hand and assign it again with a quantity."
            )
        return [
            UploadProduct(product_id, placement.stock_qty, placement.slot_name)
            for product_id, placement in placements
        ]

    def _location_updates(self) -> list[LocationUpdate]:
        return [
            LocationUpdate(product_id, placement.slot_name)
            for product_id, placement in self._web_placements("Modify location")
        ]

    def _can_start_web_update(self) -> bool:
        if self.web_upload_busy or self.chrome_connect_busy:
            return False
        if self.chrome_connected:
            return True
        messagebox.showinfo(
            "Connect Chrome first",
            "Press Connect Chrome at the top-right of tab 2, then try again.",
            parent=self.root,
        )
        return False

    def upload_selected_product(self) -> None:
        if not self._can_start_web_update():
            return
        try:
            products = self._upload_products()
        except ValueError as error:
            messagebox.showinfo(
                "Choose products to upload", str(error), parent=self.root
            )
            return
        self._start_web_update(products, location_only=False)

    def modify_selected_location(self) -> None:
        if not self._can_start_web_update():
            return
        try:
            products = self._location_updates()
        except ValueError as error:
            messagebox.showinfo("Choose products", str(error), parent=self.root)
            return
        self._start_web_update(products, location_only=True)

    def modify_cell_transfer_locations(self, updates: list[LocationUpdate]) -> None:
        if not self._can_start_web_update():
            return
        if not updates:
            messagebox.showinfo(
                "No changed products",
                "No recent cell changes to modify on web. Please switch or combine cells first.",
                parent=self.root,
            )
            return
        self._start_web_update(updates, location_only=True)

    def _start_web_update(
        self,
        products: list[UploadProduct] | list[LocationUpdate],
        *,
        location_only: bool,
    ) -> None:
        # The complete product list was captured before starting this worker.
        # Later row selections and address changes cannot alter the running task.
        products = list(products)
        if not products:
            return
        save_each_product = self._web_batch_mode_enabled()
        self.web_upload_busy = True
        self.web_upload_action = "location" if location_only else "upload"
        self.assignments.upload_button.configure(state="disabled")
        self.assignments.modify_location_button.configure(state="disabled")
        self.assignments.web_batch_mode_check.configure(state="disabled")
        if hasattr(self, "cell_transfer") and hasattr(self.cell_transfer, "modify_location_button"):
            self.cell_transfer.modify_location_button.configure(state="disabled")
        if len(products) == 1:
            product = products[0]
            action = "Updating location" if location_only else "Uploading"
            status = f"{action} {product.product_id} → {product.location_id}…"
        else:
            action = "Updating locations for" if location_only else "Uploading"
            status = (
                f"{action} {len(products)} products → {products[0].location_id}…"
            )
        self.assignments.upload_status_text.set(status)
        if hasattr(self, "cell_transfer") and hasattr(self.cell_transfer, "status_text"):
            self.cell_transfer.status_text.set(status)
        self.status_text.set(
            f"{status} Leave the website tab untouched until it finishes."
        )
        self.web_upload_events = Queue()
        Thread(
            target=self._run_web_upload,
            args=(
                products,
                self.web_upload_events,
                location_only,
                save_each_product,
            ),
            daemon=True,
        ).start()
        self.web_upload_after_id = self.root.after(100, self._poll_web_upload)

    def _run_web_upload(
        self,
        products: list[UploadProduct] | list[LocationUpdate],
        events: Queue,
        location_only: bool,
        save_each_product: bool = False,
    ) -> None:
        # This worker never calls Tkinter and never writes to the local database.
        total = len(products)
        completed = 0
        product = None
        try:
            for index, product in enumerate(products, start=1):

                def progress(text: str, *, _index=index, _product=product) -> None:
                    events.put(
                        (
                            "progress",
                            f"[{_index}/{total}] {_product.product_id}: {text}",
                        )
                    )

                if location_only:
                    result = self.website_uploader.modify_location(
                        product,
                        progress,
                        save=True if save_each_product else None,
                    )
                else:
                    result = self.website_uploader.upload(
                        product,
                        progress,
                        save=True if save_each_product else None,
                    )
                completed = index
                if total > 1:
                    events.put(
                        (
                            "progress",
                            f"[{index}/{total}] Finished {product.product_id}.",
                        )
                    )
        except Exception as error:
            product_id = product.product_id if product is not None else "unknown product"
            detail = (
                f"Batch stopped after {completed}/{total} product(s). "
                f"Failed at {product_id}.\n\n{error}"
                if total > 1
                else str(error)
            )
            events.put(
                ("error", detail, self.website_uploader.is_connected())
            )
        else:
            if total == 1:
                summary = result
            elif location_only:
                summary = (
                    f"Updated web locations for {total} products at "
                    f"{products[0].location_id}."
                )
            else:
                summary = (
                    f"Uploaded stock and web locations for {total} products at "
                    f"{products[0].location_id}."
                )
            events.put(("done", summary))

    def _poll_web_upload(self) -> None:
        self.web_upload_after_id = None
        while True:
            try:
                event_data = self.web_upload_events.get_nowait()
            except Empty:
                break
            event, text, *metadata = event_data
            if event == "progress":
                self.assignments.upload_status_text.set(text)
                if hasattr(self, "cell_transfer") and hasattr(self.cell_transfer, "status_text"):
                    self.cell_transfer.status_text.set(text)
                continue
            self.web_upload_busy = False
            self.assignments.upload_button.configure(state="normal")
            self.assignments.modify_location_button.configure(state="normal")
            self.assignments.web_batch_mode_check.configure(state="normal")
            if hasattr(self, "cell_transfer") and hasattr(self.cell_transfer, "modify_location_button"):
                self.cell_transfer.modify_location_button.configure(state="normal")
            action_title = (
                "Modify location"
                if self.web_upload_action == "location"
                else "Upload to web"
            )
            if event == "error":
                if metadata and not metadata[0]:
                    self.chrome_connected = False
                    self.connect_chrome_button.configure(text="Connect Chrome")
                self.assignments.upload_status_text.set(
                    f"{action_title} needs attention. See the message and check Chrome."
                )
                if hasattr(self, "cell_transfer") and hasattr(self.cell_transfer, "status_text"):
                    self.cell_transfer.status_text.set(f"{action_title} failed: {text}")
                self.status_text.set(
                    f"{action_title} was not verified. Local SQLite data is unchanged."
                )
                messagebox.showerror(action_title, text, parent=self.root)
            else:
                self.assignments.upload_status_text.set(text)
                if hasattr(self, "cell_transfer") and hasattr(self.cell_transfer, "status_text"):
                    self.cell_transfer.status_text.set(text)
                self.status_text.set(text)
            return
        if self.web_upload_busy:
            self.web_upload_after_id = self.root.after(100, self._poll_web_upload)

    def return_selected_to_queue(self) -> None:
        selected_items = self.assignments.contents_tree.selection()
        if not selected_items:
            messagebox.showinfo(
                "Choose products", "Select products from the slot contents first."
            )
            return

        for item_id in selected_items:
            state, separator, product_id = item_id.partition("::")
            if not separator or state not in {"staged", "saved"}:
                continue
            placements = (
                self.staged_assignments
                if state == "staged"
                else self.committed_placements
            )
            placement = placements.get(product_id)
            if placement is not None:
                self.transferred_stock[product_id] = placement.stock_qty
            elif state == "staged":
                self.transferred_stock.pop(product_id, None)
            if state == "staged":
                self.staged_assignments.pop(product_id, None)
            if product_id in self.committed_placements:
                self.pending_unassignments.add(product_id)
        self.refresh_all_views()
        self.status_text.set(
            "Products returned to the working queue with stock retained. "
            "Load another shelf and assign them when ready."
        )

    def schedule_queue_refresh(self, *_args: object) -> None:
        if self.search_after_id:
            self.root.after_cancel(self.search_after_id)
        self.search_after_id = self.root.after(180, self.refresh_product_lists)

    def refresh_product_lists(self) -> None:
        """Apply the one product search field to both working lists."""
        self.refresh_product_queue()
        self.refresh_catalog()

    def refresh_product_queue(self) -> None:
        if self.search_after_id:
            self.root.after_cancel(self.search_after_id)
            self.search_after_id = None
        raw_query = self.assignments.search_var.get().strip()
        query = normalize_search(raw_query)
        committed = set(self.committed_locations)
        staged = set(self.staged_assignments)
        on_hand = set(getattr(self, "on_hand_products", {}))
        returned_queue = getattr(self, "returned_queue_products", {})

        available = []
        for product_id, product_name in self.products.items():
            is_available = (
                (
                    product_id not in committed
                    or product_id in self.pending_unassignments
                    or product_id in self.transferred_stock
                )
                and product_id not in staged
                and product_id not in on_hand
            )
            if not is_available:
                continue
            if query and query not in self.product_search[product_id]:
                continue
            available.append((product_id, product_name))
        available.sort(
            key=lambda product: (
                product[0] not in returned_queue,
                product[0].casefold() != raw_query.casefold(),
                product[0].casefold(),
            )
        )

        self.assignments.queue_tree.delete(*self.assignments.queue_tree.get_children())
        for product_id, product_name in available[:MAX_VISIBLE_PRODUCTS]:
            if hasattr(self.assignments, "on_hand_tree"):
                returned = returned_queue.get(product_id)
                if returned is None:
                    qty_text = ""
                elif returned.stock_qty is None:
                    qty_text = "Unknown"
                else:
                    qty_text = str(returned.stock_qty)
                values = (product_id, product_name, qty_text)
                tags = ("returned",) if returned is not None else ()
            else:
                stored_qty = self.transferred_stock.get(product_id)
                tags = ("transferred",) if product_id in self.transferred_stock else ()
                qty_text = str(stored_qty) if stored_qty is not None else ""
                values = (product_id, product_name, qty_text)
            self.assignments.queue_tree.insert(
                "",
                "end",
                iid=f"product::{product_id}",
                values=values,
                tags=tags,
            )

        shown = min(len(available), MAX_VISIBLE_PRODUCTS)
        suffix = (
            " — narrow the search to see more"
            if len(available) > MAX_VISIBLE_PRODUCTS
            else ""
        )
        self.assignments.queue_count_text.set(
            f"{len(available):,} matching · showing {shown:,}{suffix}"
        )

    def refresh_catalog(self) -> None:
        if not hasattr(self.assignments, "catalog_tree"):
            return

        raw_query = self.assignments.search_var.get().strip()
        query = normalize_search(raw_query)
        matches = [
            (product_id, product_name, shortened_name)
            for product_id, (
                product_name,
                shortened_name,
            ) in self.catalog_products.items()
            if not query
            or query in self.catalog_search[product_id]
            or (
                product_id in getattr(self, "committed_locations", {})
                and query in normalize_search(self.committed_locations[product_id])
            )
        ]
        matches.sort(
            key=lambda product: (
                product[0].casefold() != raw_query.casefold(),
                product[0].casefold(),
            )
        )

        tree = self.assignments.catalog_tree
        tree.delete(*tree.get_children())
        for product_id, product_name, _shortened_name in matches[:MAX_VISIBLE_PRODUCTS]:
            placement = (
                getattr(self, "staged_assignments", {}).get(product_id)
                or getattr(self, "committed_placements", {}).get(product_id)
            )
            location_id = (
                placement.slot_name
                if placement is not None
                else getattr(self, "committed_locations", {}).get(product_id, "")
            )
            tree.insert(
                "",
                "end",
                iid=f"catalog::{product_id}",
                values=(product_id, product_name, location_id),
            )

        shown = min(len(matches), MAX_VISIBLE_PRODUCTS)
        suffix = (
            " — narrow the search to see more"
            if len(matches) > MAX_VISIBLE_PRODUCTS
            else ""
        )
        self.assignments.catalog_count_text.set(
            f"{len(matches):,} matching / {len(self.catalog_products):,} total · "
            f"showing {shown:,}{suffix}"
        )
        self.refresh_search_location(raw_query)

    def refresh_search_location(self, raw_query: str | None = None) -> None:
        location_text = getattr(self.assignments, "search_location_text", None)
        if location_text is None:
            return
        location_label = getattr(self.assignments, "search_location_label", None)

        raw_query = (
            self.assignments.search_var.get().strip()
            if raw_query is None
            else raw_query.strip()
        )
        product_id = None
        if raw_query:
            product_id = next(
                (
                    candidate
                    for candidate in self.catalog_products.keys() | self.products.keys()
                    if candidate.casefold() == raw_query.casefold()
                ),
                None,
            )

        message = ""
        location_exists = False
        if product_id is not None:
            staged = self.staged_assignments.get(product_id)
            saved = self.committed_placements.get(product_id)
            on_hand_item = getattr(self, "on_hand_products", {}).get(product_id)
            returned_item = getattr(self, "returned_queue_products", {}).get(
                product_id
            )
            if on_hand_item is not None:
                quantity = (
                    on_hand_item.stock_qty
                    if on_hand_item.stock_qty is not None
                    else "Unknown"
                )
                message = f"In on-hand queue · stock {quantity}"
                location_exists = True
            elif staged is not None:
                message = f"Already at {staged.slot_name} (staged)"
                location_exists = True
            elif saved is not None:
                suffix = (
                    " (queued for transfer)"
                    if product_id in self.pending_unassignments
                    or product_id in self.transferred_stock
                    else ""
                )
                message = f"Already at {saved.slot_name}{suffix}"
                location_exists = True
            elif returned_item is not None:
                quantity = (
                    returned_item.stock_qty
                    if returned_item.stock_qty is not None
                    else "Unknown"
                )
                message = f"In total queue · returned stock {quantity}"
            else:
                message = "Not in"

        location_text.set(message)
        if location_label is not None:
            location_label.configure(
                foreground="#c62828" if location_exists else "#555555"
            )

    def refresh_change_summary(self) -> None:
        changed_products = set(self.staged_assignments) | self.pending_unassignments
        if hasattr(self.assignments, "change_summary_text"):
            self.assignments.change_summary_text.set(
                f"{len(changed_products):,} staged product change(s) · Commit writes them to SQLite"
            )

    def refresh_all_views(self) -> None:
        self.refresh_product_lists()
        self.refresh_on_hand_queue()
        self.refresh_address_contents()
        self.refresh_change_summary()

    def reload_database_state(self, reload_catalog: bool = False) -> None:
        product_rows = self.database.get_product_records()
        self.products = {
            product_id: product_name
            for product_id, product_name, _shortened_name in product_rows
        }
        self.product_shortened_names = {
            product_id: shortened_name
            for product_id, _product_name, shortened_name in product_rows
        }
        self.product_search = {
            product_id: normalize_search(
                f"{product_id} {product_name} {shortened_name}"
            )
            for product_id, product_name, shortened_name in product_rows
        }
        if reload_catalog or not hasattr(self, "catalog_products") or not self.catalog_products:
            catalog_rows = self.database.get_catalog_products()
            self.catalog_products = {
                product_id: (product_name, shortened_name)
                for product_id, product_name, shortened_name in catalog_rows
            }
            self.catalog_search = {
                product_id: normalize_search(
                    f"{product_id} {product_name} {shortened_name}"
                )
                for product_id, product_name, shortened_name in catalog_rows
            }
        self.committed_placements = self.database.get_placement_details()
        self.on_hand_products = self.database.get_on_hand_products()
        self.returned_queue_products = self.database.get_returned_queue_products()
        if self.current_shelf_id is not None and self.preview_key:
            saved_floor, saved_side, saved_code, saved_layout = self.database.get_shelf(
                self.current_shelf_id
            )
            if (saved_floor, saved_side, saved_code) != self.preview_key:
                floor, side, code = self.preview_key
                renamed = {
                    make_slot_name(
                        saved_floor, saved_code, row, cell, side=saved_side
                    ): make_slot_name(floor, code, row, cell, side=side)
                    for row, count in enumerate(saved_layout, start=1)
                    for cell in range(1, count + 1)
                }
                self.committed_placements = {
                    product_id: Placement(
                        renamed.get(item.slot_name, item.slot_name),
                        item.stock_qty,
                        item.assigned_at,
                    )
                    for product_id, item in self.committed_placements.items()
                }
        self.committed_locations = {
            product_id: placement.slot_name
            for product_id, placement in self.committed_placements.items()
        }
        if hasattr(self, "transferred_stock"):
            self.transferred_stock = {
                pid: qty
                for pid, qty in self.transferred_stock.items()
                if pid in self.products
            }
        self.refresh_shelf_selector()
        if hasattr(self, "assignments"):
            self.refresh_product_lists()
            self.refresh_on_hand_queue()
            self.refresh_address_contents()
        if hasattr(self, "primal_view"):
            self.primal_view.refresh(reload_catalog=reload_catalog)

    def refresh_shelf_selector(self) -> None:
        choices = self.database.list_shelves()
        self.shelf_choices = {
            f"Floor {floor} — Side {side} — Shelf {shelf_code}": shelf_id
            for shelf_id, floor, side, shelf_code in choices
        }
        self.shelf_selector.configure(values=list(self.shelf_choices))
        if self.current_shelf_id is not None:
            for label, shelf_id in self.shelf_choices.items():
                if shelf_id == self.current_shelf_id:
                    self.shelf_selector.set(label)
                    break
        if hasattr(self, "shelf_browser"):
            self.shelf_browser.refresh()

    def import_csv(self) -> None:
        selected = filedialog.askopenfilename(
            title="Import product list",
            filetypes=(
                ("CSV files", "*.csv"),
                ("Text files", "*.txt"),
                ("All files", "*.*"),
            ),
        )
        if not selected:
            return
        try:
            csv_data = read_csv(Path(selected))
        except Exception as error:
            messagebox.showerror("CSV could not be read", str(error))
            return

        mapping_dialog = ColumnMappingDialog(self.root, csv_data.headers)
        self.root.wait_window(mapping_dialog)
        if mapping_dialog.result is None:
            return
        id_index, name_index, short_name_index = mapping_dialog.result

        records: dict[str, tuple[str, str]] = {}
        skipped = 0
        duplicates = 0
        required_index = max(id_index, name_index, short_name_index)
        for row in csv_data.rows:
            if len(row) <= required_index:
                skipped += 1
                continue
            product_id = row[id_index].strip()
            product_name = row[name_index].strip()
            shortened_name = row[short_name_index].strip() or product_name
            if not product_id or not product_name:
                skipped += 1
                continue
            if product_id in records:
                duplicates += 1
            records[product_id] = (product_name, shortened_name)

        if not records:
            messagebox.showerror(
                "No products", "No valid product ID/name rows were found."
            )
            return
        try:
            inserted, updated = self.database.import_products(records)
        except Exception as error:
            messagebox.showerror("Import failed", str(error))
            return

        self.reload_database_state(reload_catalog=True)
        self.refresh_all_views()
        messagebox.showinfo(
            "Import complete",
            f"New products: {inserted:,}\n"
            f"Existing products updated: {updated:,}\n"
            f"Blank/invalid rows skipped: {skipped:,}\n"
            f"Duplicate IDs inside CSV: {duplicates:,}",
        )
        self.status_text.set(
            f"Imported {len(records):,} product records from {Path(selected).name}."
        )

    def import_catalog_csv(self) -> None:
        selected = filedialog.askopenfilename(
            title="Import full product catalog",
            filetypes=(
                ("CSV files", "*.csv"),
                ("Text files", "*.txt"),
                ("All files", "*.*"),
            ),
        )
        if not selected:
            return
        try:
            csv_data = read_csv(Path(selected))
        except Exception as error:
            messagebox.showerror("CSV could not be read", str(error))
            return

        mapping_dialog = ColumnMappingDialog(self.root, csv_data.headers)
        self.root.wait_window(mapping_dialog)
        if mapping_dialog.result is None:
            return
        id_index, name_index, short_name_index = mapping_dialog.result

        records: dict[str, tuple[str, str]] = {}
        skipped = 0
        duplicates = 0
        required_index = max(id_index, name_index, short_name_index)
        for row in csv_data.rows:
            if len(row) <= required_index:
                skipped += 1
                continue
            product_id = row[id_index].strip()
            product_name = row[name_index].strip()
            shortened_name = row[short_name_index].strip()
            if not product_id or not product_name:
                skipped += 1
                continue
            if product_id in records:
                duplicates += 1
            records[product_id] = (product_name, shortened_name)

        if not records:
            messagebox.showerror(
                "No products", "No valid product ID/name rows were found."
            )
            return
        try:
            inserted, updated = self.database.import_catalog_products(records)
        except Exception as error:
            messagebox.showerror("Catalog import failed", str(error))
            return

        self.reload_database_state(reload_catalog=True)
        messagebox.showinfo(
            "Catalog import complete",
            f"New catalog products: {inserted:,}\n"
            f"Existing catalog products updated: {updated:,}\n"
            f"Blank/invalid rows skipped: {skipped:,}\n"
            f"Duplicate IDs inside CSV: {duplicates:,}\n\n"
            "Warehouse assignments and the unassigned queue were not changed.",
        )
        self.status_text.set(
            f"Imported {len(records):,} full-catalog records from {Path(selected).name}."
        )

    def has_pending_changes(self, *, excluding_queue_transfers: bool = False) -> bool:
        pending_unassignments = self.pending_unassignments
        if excluding_queue_transfers:
            pending_unassignments = (
                pending_unassignments - self.transferred_stock.keys()
            )
        return bool(
            self.staged_assignments
            or pending_unassignments
            or (self.current_layout and self.current_shelf_id is None)
            or self._editor_state() != self.saved_editor_state
        )

    def confirm_discard_pending(
        self, *, preserve_queue_transfers: bool = False
    ) -> bool:
        return not self.has_pending_changes(
            excluding_queue_transfers=preserve_queue_transfers,
        ) or messagebox.askyesno(
            "Discard changes?",
            "Discard the shelf or product changes that have not been committed?",
        )

    def new_shelf(self) -> None:
        if not self.confirm_discard_pending(preserve_queue_transfers=True):
            return
        self.current_shelf_id = None
        self.current_layout = []
        self.preview_key = None
        self.selected_slot = None
        self.staged_assignments.clear()
        self.pending_unassignments.intersection_update(self.transferred_stock)
        self.designer.floor_var.set("1")
        self.designer.side_var.set("1")
        self.designer.shelf_code_var.set("")
        self.designer.prepare_row_inputs([4] * 3, notify=False)
        self.saved_editor_state = self._editor_state()
        self.shelf_selector.set("")
        self.reload_database_state()
        self.refresh_all_views()
        self.notebook.select(self.designer_tab)
        self.status_text.set("Enter the new shelf metadata and row cell counts.")

    def load_selected_shelf(self) -> None:
        label = self.shelf_selector.get()
        shelf_id = self.shelf_choices.get(label)
        if shelf_id is None:
            messagebox.showinfo("Choose a shelf", "Select an existing shelf first.")
            return
        if not self.confirm_discard_pending(preserve_queue_transfers=True):
            return
        try:
            floor, side, shelf_code, layout = self.database.get_shelf(shelf_id)
        except Exception as error:
            messagebox.showerror("Shelf could not be loaded", str(error))
            return

        self.current_shelf_id = shelf_id
        self.designer.floor_var.set(floor)
        self.designer.side_var.set(side)
        self.designer.shelf_code_var.set(shelf_code)
        self.designer.prepare_row_inputs(layout, notify=False)
        self.current_layout = layout
        self.preview_key = (floor, side, shelf_code)
        self.selected_slot = None
        self.staged_assignments.clear()
        self.pending_unassignments.intersection_update(self.transferred_stock)
        self.saved_editor_state = self._editor_state()
        self.reload_database_state()
        self.refresh_all_views()
        self.notebook.select(self.designer_tab)
        self.status_text.set(f"Loaded {label}.")

    def commit_changes(self) -> bool:
        if not self.build_shelf_preview(switch_tab=False):
            return False
        floor, side, shelf_code = self.preview_key
        changed_products = len(
            set(self.staged_assignments) | self.pending_unassignments
        )
        try:
            shelf_id = self.database.commit_shelf(
                floor,
                shelf_code,
                self.current_layout,
                self.staged_assignments,
                self.pending_unassignments,
                side=side,
                shelf_id=self.current_shelf_id,
            )
        except LayoutConflictError as error:
            messagebox.showerror("Shelf layout cannot be changed", str(error))
            return False
        except Exception as error:
            messagebox.showerror("Commit failed", f"Nothing was saved.\n\n{error}")
            return False

        self.current_shelf_id = shelf_id
        self.staged_assignments.clear()
        self.pending_unassignments.clear()
        self.saved_editor_state = self._editor_state()
        self.reload_database_state()
        self.refresh_all_views()
        if hasattr(self, "shelf_browser"):
            self.shelf_browser.show_saved_shelf(shelf_id)
        messagebox.showinfo(
            "Commit complete",
            f"Side {side} / Shelf {shelf_code} was saved."
            + (
                f"\nLegacy staged product changes saved: {changed_products:,}."
                if changed_products
                else ""
            ),
        )
        self.status_text.set(
            f"Committed Floor {floor} / Side {side} / Shelf {shelf_code} to {self.database.path.name}."
        )
        return True

    def on_close(self) -> None:
        if getattr(self, "web_upload_busy", False) or getattr(
            self, "chrome_connect_busy", False
        ):
            messagebox.showinfo(
                "Browser task in progress",
                "Wait for the current Chrome connection or upload task before closing the mapper.",
                parent=self.root,
            )
            return
        if self.has_pending_changes():
            choice = messagebox.askyesnocancel(
                "Uncommitted changes",
                "Commit shelf and product changes before closing?",
            )
            if choice is None or (choice and not self.commit_changes()):
                return
        if self.search_after_id:
            self.root.after_cancel(self.search_after_id)
        if getattr(self, "chrome_connect_after_id", None):
            self.root.after_cancel(self.chrome_connect_after_id)
        if getattr(self, "web_upload_after_id", None):
            self.root.after_cancel(self.web_upload_after_id)
        if hasattr(self, "website_uploader"):
            self.website_uploader.disconnect()
        self.root.destroy()

"""Application actions: load shelves, stage placements, and commit changes.

The UI lives in designer.py and assignment_view.py. Layout lists remain ordered
from the ground upward; views alone translate them to screen coordinates.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .assignment_view import AssignmentView, StockQuantityDialog
from .common import APP_TITLE, MAX_VISIBLE_PRODUCTS, application_directory, make_slot_name, normalize_search
from .csv_import import ColumnMappingDialog, read_csv
from .database import LayoutConflictError, Placement, WarehouseDatabase, validate_stock_quantity
from .designer import ShelfDesigner
from .lookup_view import ProductLookupView
from .web_upload import LocationUpdate, UploadProduct, WebsiteUploader


class WarehouseMapperApp:
    def __init__(self, root: tk.Tk, database_path: Path | None = None):
        self.root = root
        self.database = WarehouseDatabase(database_path or application_directory() / "warehouse_locations.db")
        self.products: dict[str, str] = {}
        self.product_search: dict[str, str] = {}
        self.catalog_products: dict[str, tuple[str, str]] = {}
        self.catalog_search: dict[str, str] = {}
        self.committed_locations: dict[str, str] = {}
        self.committed_placements: dict[str, Placement] = {}
        self.staged_assignments: dict[str, Placement] = {}
        self.pending_unassignments: set[str] = set()
        self.transferred_stock: dict[str, int] = {}
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
        self.reload_database_state()
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
                return [elm for elm in style.map("Treeview", query_opt=option) if elm[:2] != ("!disabled", "!selected")]
            style.map("Treeview", foreground=fixed_map("foreground"), background=fixed_map("background"))
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Heading.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Commit.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 7))

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(12, 10))
        self.toolbar = toolbar
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text=APP_TITLE, style="Title.TLabel").pack(side="left")

        ttk.Button(toolbar, text="Import products CSV", command=self.import_csv).pack(side="left", padx=(20, 6))
        ttk.Button(
            toolbar, text="Import full catalog CSV", command=self.import_catalog_csv,
        ).pack(side="left", padx=6)
        ttk.Button(toolbar, text="New shelf", command=self.new_shelf).pack(side="left", padx=6)

        ttk.Label(toolbar, text="Existing shelf:").pack(side="left", padx=(18, 5))
        self.shelf_selector = ttk.Combobox(toolbar, state="readonly", width=28)
        self.shelf_selector.pack(side="left")
        ttk.Button(toolbar, text="Load", command=self.load_selected_shelf).pack(side="left", padx=(5, 6))
        self.connect_chrome_button = ttk.Button(
            toolbar, text="Connect Chrome", command=self.connect_chrome,
        )
        self.connect_chrome_button.pack(side="left", padx=(0, 6))

        ttk.Button(
            toolbar,
            text="Commit shelf + assignments",
            style="Commit.TButton",
            command=self.commit_changes,
        ).pack(side="right")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self.designer = ShelfDesigner(
            self.notebook, self.build_shelf_preview, self.can_resize_rows, self.on_rows_changed
        )
        self.assignments = AssignmentView(
            self.notebook, self.schedule_queue_refresh, self.assign_selected_products,
            self.return_selected_to_queue, self.select_slot,
            on_upload=self.upload_selected_product,
            on_modify_location=self.modify_selected_location,
            on_modify_stock=self.modify_selected_stock,
            on_transfer=self.transfer_selected_products,
            on_preassign_stock=self.preassign_queue_stock,
            on_catalog_to_queue=self.transfer_catalog_selection_to_queue,
        )
        self.notebook.add(self.designer, text="1. Shelf Designer")
        self.notebook.add(self.assignments, text="2. Assign Products")
        self.lookup = ProductLookupView(self.notebook, self.database)
        self.notebook.add(self.lookup, text="3. Find Product")
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        self.status_text = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.status_text, relief="sunken", anchor="w", padding=(8, 3)).pack(
            fill="x", side="bottom"
        )

    def on_tab_changed(self, _event=None) -> None:
        if self.notebook.select() == str(self.lookup):
            self.toolbar.pack_forget()
            self.lookup.refresh()
        else:
            self.toolbar.pack(fill="x", before=self.notebook)

    def _editor_state(self) -> tuple:
        return (
            self.designer.floor_var.get(), self.designer.side_var.get(), self.designer.shelf_code_var.get(),
            self.designer.row_count_var.get(),
            tuple(count.get() for count in self.designer.row_inputs),
        )

    def _slots_are_empty(self, removed_slots: set[str]) -> bool:
        """Check the working placements before removing any rows or cells."""
        locations = {
            product_id: slot for product_id, slot in self.committed_locations.items()
            if product_id not in self.pending_unassignments
        }
        locations.update({product_id: placement.slot_name for product_id, placement in self.staged_assignments.items()})
        occupied = sorted({slot for slot in locations.values() if slot in removed_slots})
        if occupied:
            messagebox.showerror(
                "Rows or cells still contain products",
                f"Return or move the products in {occupied[0]} before removing this row or cell."
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
            (row_number, cell): make_slot_name(floor, shelf_code, row_number, cell, side=side)
            for row_number, count in enumerate(layout, start=1)
            for cell in range(1, count + 1)
        }
        valid_slots = set(new_slots.values())
        if len(valid_slots) != len(new_slots):
            messagebox.showerror("Duplicate location IDs", "Use a shelf code that gives each cell a distinct ID.")
            return False
        if self.preview_key:
            old_floor, old_side, old_code = self.preview_key
            old_slots = {
                (row_number, cell): make_slot_name(old_floor, old_code, row_number, cell, side=old_side)
                for row_number, count in enumerate(self.current_layout, start=1)
                for cell in range(1, count + 1)
            }
            removed = {name for coordinate, name in old_slots.items() if coordinate not in new_slots}
            if not self._slots_are_empty(removed):
                return False
            if new_key != self.preview_key:
                renamed = {name: new_slots[coordinate] for coordinate, name in old_slots.items() if coordinate in new_slots}
                self.staged_assignments = {
                    product_id: Placement(renamed.get(item.slot_name, item.slot_name), item.stock_qty, item.assigned_at)
                    for product_id, item in self.staged_assignments.items()
                }
                if self.current_shelf_id is not None:
                    # These are working display caches. Tab 3 reads the database
                    # independently and keeps showing saved metadata until Commit.
                    self.committed_placements = {
                        product_id: Placement(renamed.get(item.slot_name, item.slot_name), item.stock_qty, item.assigned_at)
                        for product_id, item in self.committed_placements.items()
                    }
                    self.committed_locations = {
                        product_id: item.slot_name for product_id, item in self.committed_placements.items()
                    }
                self.selected_slot = renamed.get(self.selected_slot, self.selected_slot)

        self.current_layout = layout
        self.preview_key = new_key
        if self.selected_slot not in valid_slots:
            self.selected_slot = None
        self.refresh_all_views()
        if switch_tab:
            self.notebook.select(self.assignments)
        self.status_text.set("Shelf preview updated. Commit to save the layout and assignments.")
        return True

    def render_shelf(self) -> None:
        floor, side, shelf_code = self.preview_key or ("", "", "")
        self.assignments.render_shelf(
            floor, shelf_code, self.current_layout, self.visible_slot_counts(), self.selected_slot, side=side,
        )
        if self.current_layout:
            self.assignments.active_shelf_text.set(
                f"Floor {floor} · Side {side} · Shelf {shelf_code} · {len(self.current_layout)} rows · "
                f"{sum(self.current_layout)} slots"
            )
        else:
            self.assignments.active_shelf_text.set("No shelf built yet")
        self.refresh_slot_contents()

    def select_slot(self, slot_name: str) -> None:
        self.selected_slot = slot_name
        self.assignments.mark_selected(slot_name)
        self.refresh_slot_contents()

    def visible_slot_counts(self) -> dict[str, tuple[int, int]]:
        saved: dict[str, int] = {}
        staged: dict[str, int] = {}
        for product_id, slot_name in self.committed_locations.items():
            if product_id not in self.pending_unassignments and product_id not in self.staged_assignments:
                saved[slot_name] = saved.get(slot_name, 0) + 1
        for placement in self.staged_assignments.values():
            slot_name = placement.slot_name
            staged[slot_name] = staged.get(slot_name, 0) + 1
        return {
            slot_name: (saved.get(slot_name, 0), staged.get(slot_name, 0))
            for slot_name in set(saved) | set(staged)
        }

    def assign_selected_products(self) -> None:
        if not self.selected_slot:
            messagebox.showinfo("Choose a slot", "Click a shelf slot first.")
            return
        selected_items = self.assignments.queue_tree.selection()
        if not selected_items:
            messagebox.showinfo("Choose products", "Select one or more products from the queue.")
            return

        slot_name = self.selected_slot
        product_ids = [item_id.removeprefix("product::") for item_id in selected_items]
        initial_quantities = {
            product_id: self.transferred_stock.get(product_id)
            for product_id in product_ids
        }
        dialog = StockQuantityDialog(
            self.root, slot_name,
            [(product_id, self.products.get(product_id, "")) for product_id in product_ids],
            initial_quantities=initial_quantities,
        )
        self.root.wait_window(dialog)
        if dialog.result is None:
            return

        # Confirming quantities is the assignment action. Commit must persist
        # this captured value, even if the shelf is saved much later.
        assigned_at = datetime.now().astimezone().isoformat(timespec="seconds")
        for product_id, quantity in dialog.result.items():
            self.staged_assignments[product_id] = Placement(slot_name, quantity, assigned_at)
            self.transferred_stock.pop(product_id, None)

        self.refresh_all_views()
        self.status_text.set(
            f"Staged {len(selected_items)} product(s) in {self.selected_slot}. Press Commit to save."
        )

    def refresh_slot_contents(self) -> None:
        self.assignments.contents_tree.delete(*self.assignments.contents_tree.get_children())
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

        def newest_first(item):
            assigned_at = item[2].assigned_at
            try:
                timestamp = (
                    datetime.fromisoformat(assigned_at).timestamp()
                    if assigned_at else float("-inf")
                )
            except (TypeError, ValueError, OverflowError, OSError):
                timestamp = float("-inf")
            return -timestamp, item[1].casefold()

        for state, product_id, placement in sorted(visible_products, key=newest_first):
            self.assignments.contents_tree.insert(
                "", "end", iid=f"{state.lower()}::{product_id}",
                values=(
                    product_id, self.products.get(product_id, ""),
                    placement.stock_qty if placement.stock_qty is not None else "Unknown",
                    placement.assigned_at.replace("T", " ") if placement.assigned_at else "Unknown",
                    state,
                ),
            )

    def modify_selected_stock(self) -> None:
        selected = self.assignments.contents_tree.selection()
        if len(selected) != 1:
            messagebox.showinfo(
                "Choose one product",
                "Select exactly one product in Selected slot contents, then press Modify selected stock.",
                parent=self.root,
            )
            return

        state, separator, product_id = selected[0].partition("::")
        if not separator or state not in {"staged", "saved"} or product_id not in self.products:
            messagebox.showinfo(
                "Choose one product",
                "Select a current product from the slot contents list.",
                parent=self.root,
            )
            return

        placements = self.staged_assignments if state == "staged" else self.committed_placements
        placement = placements.get(product_id)
        stale_saved = (
            state == "saved"
            and (product_id in self.pending_unassignments or product_id in self.staged_assignments)
        )
        if placement is None or placement.slot_name != self.selected_slot or stale_saved:
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

        current_text = placement.stock_qty if placement.stock_qty is not None else "Unknown"
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
            if not separator or state not in {"staged", "saved"} or product_id not in self.products:
                continue

            placements = self.staged_assignments if state == "staged" else self.committed_placements
            placement = placements.get(product_id)
            if placement is not None and placement.stock_qty is not None:
                self.transferred_stock[product_id] = placement.stock_qty

            if state == "staged":
                self.staged_assignments.pop(product_id, None)
            else:
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
            product_id: self.catalog_products[product_id]
            for product_id in product_ids
        }
        try:
            self.database.import_products(records)
        except Exception as error:
            messagebox.showerror("Transfer failed", str(error), parent=self.root)
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
            if staged is not None and staged.stock_qty is not None:
                self.transferred_stock[product_id] = staged.stock_qty
            elif saved is not None and saved.stock_qty is not None:
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
            "Catalog transfer: " + ", ".join(summary)
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
            self.root, "Queue",
            [(product_id, self.products.get(product_id, "")) for product_id in product_ids],
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
        self.status_text.set(f"Pre-assigned stock for {len(dialog.result)} product(s) in queue.")

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
            self.chrome_connect_after_id = self.root.after(100, self._poll_chrome_connect)

    def _selected_web_placement(self, action_name: str) -> tuple[str, Placement]:
        selected = self.assignments.contents_tree.selection()
        if len(selected) != 1:
            raise ValueError(
                f"Select exactly one product in Selected slot contents, then press {action_name}."
            )
        state, separator, product_id = selected[0].partition("::")
        if not separator or state not in {"staged", "saved"} or product_id not in self.products:
            raise ValueError("Select a current product from the slot contents list.")
        placements = self.staged_assignments if state == "staged" else self.committed_placements
        placement = placements.get(product_id)
        if (placement is None or placement.slot_name != self.selected_slot or
                (state == "saved" and (product_id in self.pending_unassignments or product_id in self.staged_assignments))):
            raise ValueError("That selection changed. Select the product in its current slot again.")
        return product_id, placement

    def _selected_upload_product(self) -> UploadProduct:
        product_id, placement = self._selected_web_placement("Upload to web")
        if placement.stock_qty is None:
            raise ValueError(
                "This product has no recorded quantity. Return it to the queue and assign it again "
                "with a quantity before uploading."
            )
        return UploadProduct(product_id, placement.stock_qty, placement.slot_name)

    def _selected_location_update(self) -> LocationUpdate:
        product_id, placement = self._selected_web_placement("Modify location")
        return LocationUpdate(product_id, placement.slot_name)

    def _can_start_web_update(self) -> bool:
        if self.web_upload_busy or self.chrome_connect_busy:
            return False
        if self.chrome_connected:
            return True
        messagebox.showinfo(
            "Connect Chrome first",
            "Press Connect Chrome beside the shelf Load button, then try again.",
            parent=self.root,
        )
        return False

    def upload_selected_product(self) -> None:
        if not self._can_start_web_update():
            return
        try:
            product = self._selected_upload_product()
        except ValueError as error:
            messagebox.showinfo("Choose a product to upload", str(error), parent=self.root)
            return
        self._start_web_update(product, location_only=False)

    def modify_selected_location(self) -> None:
        if not self._can_start_web_update():
            return
        try:
            product = self._selected_location_update()
        except ValueError as error:
            messagebox.showinfo("Choose a product", str(error), parent=self.root)
            return
        self._start_web_update(product, location_only=True)

    def _start_web_update(
        self,
        product: UploadProduct | LocationUpdate,
        *,
        location_only: bool,
    ) -> None:
        # Capture the placement now. Later UI changes cannot alter this task.
        self.web_upload_busy = True
        self.web_upload_action = "location" if location_only else "upload"
        self.assignments.upload_button.configure(state="disabled")
        self.assignments.modify_location_button.configure(state="disabled")
        action = "Updating location" if location_only else "Uploading"
        self.assignments.upload_status_text.set(
            f"{action} {product.product_id} → {product.location_id}…"
        )
        self.status_text.set(
            f"{action} in progress. Leave the website tab untouched until it finishes."
        )
        self.web_upload_events = Queue()
        Thread(
            target=self._run_web_upload,
            args=(product, self.web_upload_events, location_only),
            daemon=True,
        ).start()
        self.web_upload_after_id = self.root.after(100, self._poll_web_upload)

    def _run_web_upload(
        self,
        product: UploadProduct | LocationUpdate,
        events: Queue,
        location_only: bool,
    ) -> None:
        # This worker never calls Tkinter and never writes to the local database.
        try:
            progress = lambda text: events.put(("progress", text))
            if location_only:
                result = self.website_uploader.modify_location(product, progress)
            else:
                result = self.website_uploader.upload(product, progress)
        except Exception as error:
            events.put(("error", str(error), self.website_uploader.is_connected()))
        else:
            events.put(("done", result))

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
                continue
            self.web_upload_busy = False
            self.assignments.upload_button.configure(state="normal")
            self.assignments.modify_location_button.configure(state="normal")
            action_title = "Modify location" if self.web_upload_action == "location" else "Upload to web"
            if event == "error":
                if metadata and not metadata[0]:
                    self.chrome_connected = False
                    self.connect_chrome_button.configure(text="Connect Chrome")
                self.assignments.upload_status_text.set(
                    f"{action_title} needs attention. See the message and check Chrome."
                )
                self.status_text.set(
                    f"{action_title} was not verified. Local staged changes are unchanged."
                )
                messagebox.showerror(action_title, text, parent=self.root)
            else:
                self.assignments.upload_status_text.set(text)
                suffix = " Use Commit to save any local changes." if self.web_upload_action == "upload" else ""
                self.status_text.set(text + suffix)
            return
        if self.web_upload_busy:
            self.web_upload_after_id = self.root.after(100, self._poll_web_upload)

    def return_selected_to_queue(self) -> None:
        selected_items = self.assignments.contents_tree.selection()
        if not selected_items:
            messagebox.showinfo("Choose products", "Select products from the slot contents first.")
            return

        for item_id in selected_items:
            state, product_id = item_id.split("::", 1)
            if state == "staged":
                self.staged_assignments.pop(product_id, None)
            else:
                self.pending_unassignments.add(product_id)
            self.transferred_stock.pop(product_id, None)
        self.refresh_all_views()
        self.status_text.set("Products returned to the working queue. Press Commit to save the change.")

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

        available = []
        for product_id, product_name in self.products.items():
            is_available = (product_id not in committed or product_id in self.pending_unassignments) and product_id not in staged
            if not is_available:
                continue
            if query and query not in self.product_search[product_id]:
                continue
            available.append((product_id, product_name))
        available.sort(
            key=lambda product: (
                product[0].casefold() != raw_query.casefold(),
                product[0].casefold(),
            )
        )

        self.assignments.queue_tree.delete(*self.assignments.queue_tree.get_children())
        for product_id, product_name in available[:MAX_VISIBLE_PRODUCTS]:
            stored_qty = self.transferred_stock.get(product_id)
            tags = ("transferred",) if stored_qty is not None else ()
            qty_text = str(stored_qty) if stored_qty is not None else ""
            self.assignments.queue_tree.insert(
                "", "end", iid=f"product::{product_id}",
                values=(product_id, product_name, qty_text),
                tags=tags,
            )

        shown = min(len(available), MAX_VISIBLE_PRODUCTS)
        suffix = " — narrow the search to see more" if len(available) > MAX_VISIBLE_PRODUCTS else ""
        self.assignments.queue_count_text.set(f"{len(available):,} matching · showing {shown:,}{suffix}")

    def refresh_catalog(self) -> None:
        if not hasattr(self.assignments, "catalog_tree"):
            return

        raw_query = self.assignments.search_var.get().strip()
        query = normalize_search(raw_query)
        matches = [
            (product_id, product_name, shortened_name)
            for product_id, (product_name, shortened_name) in self.catalog_products.items()
            if not query or query in self.catalog_search[product_id]
        ]
        matches.sort(
            key=lambda product: (
                product[0].casefold() != raw_query.casefold(),
                product[0].casefold(),
            )
        )

        tree = self.assignments.catalog_tree
        tree.delete(*tree.get_children())
        for product_id, product_name, shortened_name in matches[:MAX_VISIBLE_PRODUCTS]:
            tree.insert(
                "",
                "end",
                iid=f"catalog::{product_id}",
                values=(product_id, product_name, shortened_name),
            )

        shown = min(len(matches), MAX_VISIBLE_PRODUCTS)
        suffix = " — narrow the search to see more" if len(matches) > MAX_VISIBLE_PRODUCTS else ""
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
            if staged is not None:
                message = f"Already at {staged.slot_name} (staged)"
                location_exists = True
            elif saved is not None:
                suffix = " (queued for transfer)" if product_id in self.pending_unassignments else ""
                message = f"Already at {saved.slot_name}{suffix}"
                location_exists = True
            else:
                message = "Not in"

        location_text.set(message)
        if location_label is not None:
            location_label.configure(
                foreground="#c62828" if location_exists else "#555555"
            )

    def refresh_change_summary(self) -> None:
        changed_products = set(self.staged_assignments) | self.pending_unassignments
        self.assignments.change_summary_text.set(
            f"{len(changed_products):,} staged product change(s) · Commit writes them to SQLite"
        )

    def refresh_all_views(self) -> None:
        self.refresh_product_lists()
        self.render_shelf()
        self.refresh_change_summary()

    def reload_database_state(self) -> None:
        product_rows = self.database.get_product_records()
        self.products = {
            product_id: product_name
            for product_id, product_name, _shortened_name in product_rows
        }
        self.product_search = {
            product_id: normalize_search(f"{product_id} {product_name} {shortened_name}")
            for product_id, product_name, shortened_name in product_rows
        }
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
        if self.current_shelf_id is not None and self.preview_key:
            saved_floor, saved_side, saved_code, saved_layout = self.database.get_shelf(self.current_shelf_id)
            if (saved_floor, saved_side, saved_code) != self.preview_key:
                floor, side, code = self.preview_key
                renamed = {
                    make_slot_name(saved_floor, saved_code, row, cell, side=saved_side):
                    make_slot_name(floor, code, row, cell, side=side)
                    for row, count in enumerate(saved_layout, start=1)
                    for cell in range(1, count + 1)
                }
                self.committed_placements = {
                    product_id: Placement(renamed.get(item.slot_name, item.slot_name), item.stock_qty, item.assigned_at)
                    for product_id, item in self.committed_placements.items()
                }
        self.committed_locations = {
            product_id: placement.slot_name for product_id, placement in self.committed_placements.items()
        }
        if hasattr(self, "transferred_stock"):
            self.transferred_stock = {pid: qty for pid, qty in self.transferred_stock.items() if pid in self.products}
        self.refresh_shelf_selector()
        if hasattr(self, "assignments"):
            self.refresh_product_lists()

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

    def import_csv(self) -> None:
        selected = filedialog.askopenfilename(
            title="Import product list",
            filetypes=(("CSV files", "*.csv"), ("Text files", "*.txt"), ("All files", "*.*")),
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
            messagebox.showerror("No products", "No valid product ID/name rows were found.")
            return
        try:
            inserted, updated = self.database.import_products(records)
        except Exception as error:
            messagebox.showerror("Import failed", str(error))
            return

        self.reload_database_state()
        self.refresh_all_views()
        messagebox.showinfo(
            "Import complete",
            f"New products: {inserted:,}\n"
            f"Existing products updated: {updated:,}\n"
            f"Blank/invalid rows skipped: {skipped:,}\n"
            f"Duplicate IDs inside CSV: {duplicates:,}",
        )
        self.status_text.set(f"Imported {len(records):,} product records from {Path(selected).name}.")

    def import_catalog_csv(self) -> None:
        selected = filedialog.askopenfilename(
            title="Import full product catalog",
            filetypes=(("CSV files", "*.csv"), ("Text files", "*.txt"), ("All files", "*.*")),
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
            messagebox.showerror("No products", "No valid product ID/name rows were found.")
            return
        try:
            inserted, updated = self.database.import_catalog_products(records)
        except Exception as error:
            messagebox.showerror("Catalog import failed", str(error))
            return

        self.reload_database_state()
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

    def has_pending_changes(self) -> bool:
        return bool(
            self.staged_assignments or self.pending_unassignments
            or (self.current_layout and self.current_shelf_id is None)
            or self._editor_state() != self.saved_editor_state
        )

    def confirm_discard_pending(self) -> bool:
        return not self.has_pending_changes() or messagebox.askyesno(
            "Discard changes?", "Discard the shelf or product changes that have not been committed?"
        )

    def new_shelf(self) -> None:
        if not self.confirm_discard_pending():
            return
        self.current_shelf_id = None
        self.current_layout = []
        self.preview_key = None
        self.selected_slot = None
        self.staged_assignments.clear()
        self.pending_unassignments.clear()
        self.designer.floor_var.set("1")
        self.designer.side_var.set("1")
        self.designer.shelf_code_var.set("")
        self.designer.prepare_row_inputs([4] * 3, notify=False)
        self.saved_editor_state = self._editor_state()
        self.shelf_selector.set("")
        self.reload_database_state()
        self.refresh_all_views()
        self.notebook.select(self.designer)
        self.status_text.set("Enter the new shelf metadata and row cell counts.")

    def load_selected_shelf(self) -> None:
        label = self.shelf_selector.get()
        shelf_id = self.shelf_choices.get(label)
        if shelf_id is None:
            messagebox.showinfo("Choose a shelf", "Select an existing shelf first.")
            return
        if not self.confirm_discard_pending():
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
        self.pending_unassignments.clear()
        self.saved_editor_state = self._editor_state()
        self.reload_database_state()
        self.refresh_all_views()
        self.notebook.select(self.assignments)
        self.status_text.set(f"Loaded {label}.")

    def commit_changes(self) -> bool:
        if not self.build_shelf_preview(switch_tab=False):
            return False
        floor, side, shelf_code = self.preview_key
        changed_products = len(set(self.staged_assignments) | self.pending_unassignments)
        try:
            shelf_id = self.database.commit_shelf(
                floor, shelf_code, self.current_layout,
                self.staged_assignments, self.pending_unassignments,
                side=side, shelf_id=self.current_shelf_id,
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
        messagebox.showinfo(
            "Commit complete",
            f"Side {side} / Shelf {shelf_code} and {changed_products:,} product change(s) were saved.",
        )
        self.status_text.set(
            f"Committed Floor {floor} / Side {side} / Shelf {shelf_code} to {self.database.path.name}."
        )
        return True

    def on_close(self) -> None:
        if getattr(self, "web_upload_busy", False) or getattr(self, "chrome_connect_busy", False):
            messagebox.showinfo(
                "Browser task in progress",
                "Wait for the current Chrome connection or upload task before closing the mapper.",
                parent=self.root,
            )
            return
        if self.has_pending_changes():
            choice = messagebox.askyesnocancel(
                "Uncommitted changes", "Commit shelf and product changes before closing?"
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

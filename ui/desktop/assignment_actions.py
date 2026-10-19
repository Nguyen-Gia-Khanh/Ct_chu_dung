"""Tkinter actions for staging, assigning, and returning inventory."""

from __future__ import annotations

from datetime import datetime
from tkinter import messagebox, simpledialog

from mapper.core.common import clean_location_segment, vietnam_time
from mapper.persistence.database import OnHandProduct
from mapper.services.assignment import (
    SHIFT_CONFIRM_CLICKS, SHIFT_CONFIRM_SECONDS, needs_shift_confirmation, shift_prefix_error, shift_transfer,
)
from mapper.services.shelf_grid import load_grid
from .dialogs import StockQuantityDialog
from .widgets import sync_tree_rows


class AssignmentActions:
    def assign_product_records_to_address(self, records) -> None:
        """Normal queue/catalog assignment skips the on-hand holding area."""
        if self.selected_address is None:
            messagebox.showinfo(
                "Load an address", "Load the destination shelf address first.", parent=self.root,
            )
            return
        address = self.selected_address
        initial_quantities = {}
        for pid in records:
            item = (
                self.staged_assignments.get(pid)
                or getattr(self, "on_hand_products", {}).get(pid)
                or self.committed_placements.get(pid)
            )
            if item is not None:
                initial_quantities[pid] = item.stock_qty
        dialog = StockQuantityDialog(
            self.root, address.slot_name,
            [(pid, name) for pid, (name, _brand_name) in records.items()],
            initial_quantities=initial_quantities,
            footer_text="Assignment is saved immediately to the loaded shelf address.",
        )
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        assigned_at = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            moved = self.database.assign_catalog_direct_to_slot(
                address.slot_id, assigned_at, records, quantities=dialog.result,
            )
        except Exception as error:
            messagebox.showerror("Assignment failed", str(error), parent=self.root)
            return
        for pid in records:
            self.staged_assignments.pop(pid, None)
            self.pending_unassignments.discard(pid)
            self.transferred_stock.pop(pid, None)
        self.reconcile_inventory_products(records, affected_slots=(address.slot_name,))
        self.status_text.set(f"Assigned {moved} product(s) to {address.slot_name}. Saved immediately.")

    def _start_queue_shift_timer(self) -> None:
        if self.queue_shift_timer is not None:
            try:
                self.root.after_cancel(self.queue_shift_timer)
            except Exception:  # noqa: BLE001, S110
                pass
        self.queue_shift_timer = self.root.after(SHIFT_CONFIRM_SECONDS * 1000, self._reset_queue_shift_clicks)

    def _show_search_refusal(self, message: str) -> None:
        if hasattr(self.assignments, "search_location_text"):
            self.assignments.search_location_text.set(message)
        if hasattr(self.assignments, "search_location_label"):
            self.assignments.search_location_label.configure(foreground="#c62828")

    def _reset_queue_shift_clicks(self) -> None:
        if self.queue_shift_timer is not None:
            try:
                self.root.after_cancel(self.queue_shift_timer)
            except Exception:  # noqa: BLE001, S110
                pass
            self.queue_shift_timer = None
        self.queue_shift_clicks = 0
        if hasattr(self, "assignments"):
            self.assignments.set_queue_button_clicks(None)

    def _on_whole_mode_change(self, enabled: bool) -> None:
        if not enabled:
            self._reset_queue_shift_clicks()

    def assign_queue_selection_to_address(self, to_shelf: bool = False) -> None:
        is_to_shelf = to_shelf or getattr(self.assignments, "whole_mode", False)
        if not is_to_shelf:
            self._reset_queue_shift_clicks()
            selected_items = self.assignments.queue_tree.selection()
            product_ids = [
                item_id.removeprefix("product::")
                for item_id in selected_items
                if item_id.startswith("product::")
                and item_id.removeprefix("product::") in self.products
                and self.is_queue_product_available(item_id.removeprefix("product::"))
            ]
            if not product_ids:
                messagebox.showinfo(
                    "Choose products",
                    "Select one or more ready products from the total queue. Products already on-hand or assigned cannot move again.",
                    parent=self.root,
                )
                return

            self.assign_product_records_to_address({
                pid: (self.products[pid], self.product_brand_names.get(pid, ""))
                for pid in product_ids
            })
            return

        # Whole mode: Transfer total queue straight to shelf with stock 999
        if self.selected_address is None:
            messagebox.showinfo(
                "Load an address",
                "Enter the shelf address and press Load address first.",
                parent=self.root,
            )
            self._reset_queue_shift_clicks()
            return

        queue_items = self.assignments.queue_tree.get_children()
        queue_pids = [
            item_id.removeprefix("product::")
            for item_id in queue_items
            if item_id.startswith("product::")
            and self.is_queue_product_available(item_id.removeprefix("product::"))
        ]
        if not queue_pids:
            if hasattr(self.assignments, "search_location_text"):
                self.assignments.search_location_text.set(
                    "No products in queue to transfer."
                )
            if hasattr(self.assignments, "search_location_label"):
                self.assignments.search_location_label.configure(foreground="#c62828")
            self._reset_queue_shift_clicks()
            return

        refusal = shift_prefix_error(queue_pids)
        if refusal:
            self._show_search_refusal(refusal)
            self._reset_queue_shift_clicks()
            return

        if needs_shift_confirmation(len(queue_pids)):
            self.queue_shift_clicks += 1
            if self.queue_shift_clicks < SHIFT_CONFIRM_CLICKS:
                self.assignments.set_queue_button_clicks(SHIFT_CONFIRM_CLICKS - self.queue_shift_clicks)
                self._start_queue_shift_timer()
                return

        self._reset_queue_shift_clicks()

        records = {}
        for pid in queue_pids:
            name = self.products.get(pid, "")
            if not name and pid in self.catalog_products:
                name = self.catalog_products[pid][0]
            records[pid] = (name, "")

        try:
            moved, transfer_data = shift_transfer(self.database, self.selected_address.slot_id, records)
        except Exception as error:
            messagebox.showerror("Transfer failed", str(error), parent=self.root)
            return

        self.last_shift_transfer = transfer_data
        if hasattr(self.assignments, "revert_button"):
            self.assignments.revert_button.configure(state="normal")

        for pid in queue_pids:
            self.staged_assignments.pop(pid, None)
            self.pending_unassignments.discard(pid)
            self.transferred_stock.pop(pid, None)

        self.reconcile_inventory_products(
            queue_pids, affected_slots=(self.selected_address.slot_name,)
        )
        self.status_text.set(
            f"Transferred {moved} queue product(s) to {self.selected_address.slot_name} with retained stock (999 when uncounted). Saved immediately."
        )

    def refresh_on_hand_queue(self) -> None:
        if not hasattr(self.assignments, "on_hand_tree"):
            return
        tree = self.assignments.on_hand_tree
        rows = []
        for product_id, item in sorted(
            self.on_hand_products.items(),
            key=lambda entry: (entry[1].queued_at, entry[0].casefold()),
        ):
            rows.append((
                f"hand::{product_id}",
                (
                    product_id,
                    self.catalog_products.get(product_id, (product_id, ""))[0],
                    item.stock_qty if item.stock_qty is not None else "Unknown",
                ),
                (),
            ))
        sync_tree_rows(tree, rows)
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
        if quantity is None or quantity == item.stock_qty:
            return
        try:
            self.database.update_on_hand_stock(
                product_id, quantity,
                modified_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            )
        except Exception as error:
            messagebox.showerror(
                "Stock could not be updated", str(error), parent=self.root
            )
            return
        self.apply_inventory_changes(
            on_hand={product_id: OnHandProduct(product_id, quantity, item.queued_at)},
            queue_changed=False,
            catalog_changed=False,
        )
        self.status_text.set(f"Updated on-hand stock for {product_id} to {quantity}.")

    def preview_assignment_shelf(self) -> None:
        """Show the saved shelf matching tab 2's Floor, Side, and Shelf fields."""
        floor, side, shelf_code = (clean_location_segment(var.get()) for var in
                                   (self.assignments.floor_var, self.assignments.side_var, self.assignments.shelf_var))
        if not all((floor, side, shelf_code)):
            self.assignments.clear_shelf_preview("Enter Floor, Side, and Shelf below.")
            return
        shelf_id = self.database.get_shelf_id(floor, shelf_code, side=side)
        if shelf_id is None:
            self.assignments.clear_shelf_preview(f"No saved shelf at Floor {floor} / Side {side} / Shelf {shelf_code}.")
            return
        try:
            grid, _contents = load_grid(self.database, shelf_id)
        except KeyError:
            self.assignments.clear_shelf_preview("That shelf changed. Select it again.")
            return
        self.assignments.render_shelf_preview(grid)

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
            self.assignments.highlight_shelf_cell(0, 0)
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
        self.assignments.highlight_shelf_cell(address.row_number, address.slot_number)
        self.refresh_address_contents()
        self.status_text.set(f"Loaded {address.slot_name}.")

    def refresh_address_contents(self, contents=None) -> None:
        if not hasattr(self.assignments, "contents_tree") or not hasattr(
            self.assignments, "address_status_text"
        ):
            return
        tree = self.assignments.contents_tree
        if self.selected_address is None:
            sync_tree_rows(tree, [])
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
            sync_tree_rows(tree, [])
            self.selected_address = None
            self.assignments.selected_slot_text.set("No address loaded")
            self.assignments.address_status_text.set(
                "The loaded address changed or was removed. Enter and load it again."
            )
            return
        address = current_address
        self.selected_address = current_address
        if contents is None:
            contents = self.database.get_slot_contents(address.slot_id)
        self.assignments.selected_slot_text.set(address.slot_name)
        self.assignments.address_status_text.set(
            f"Loaded {address.slot_name} · {len(contents)} product(s)"
        )
        rows = []
        stock_modifications = self.database.get_slot_stock_modifications(address.slot_id)
        for product_id, product_name, placement in contents:
            rows.append((
                f"saved::{product_id}",
                (
                    product_id,
                    product_name,
                    placement.stock_qty
                    if placement.stock_qty is not None
                    else "Unknown",
                    vietnam_time(placement.assigned_at)
                    if placement.assigned_at
                    else "Unknown",
                    vietnam_time(stock_modifications.get(product_id)),
                ),
                (),
            ))
        sync_tree_rows(tree, rows)

    def assign_on_hand_to_address(self, whole_mode: bool = False) -> None:
        if self.selected_address is None:
            messagebox.showinfo(
                "Load an address",
                "Enter the shelf address and press Load address first.",
                parent=self.root,
            )
            return

        is_whole = whole_mode or getattr(self.assignments, "whole_mode", False)
        transfer_data = None
        if is_whole:
            if not self.on_hand_products:
                messagebox.showinfo(
                    "On-hand queue empty",
                    "There are no products in the on-hand queue to assign.",
                    parent=self.root,
                )
                return
            product_ids = None
            affected_pids = list(self.on_hand_products.keys())
            transfer_data = self.database.capture_shift_transfer(affected_pids,self.selected_address.slot_id)
        else:
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
                    "Select one or more on-hand products with Ctrl-click first, or hold Shift for whole mode.",
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

        if is_whole and transfer_data:
            self.last_shift_transfer = transfer_data
            if hasattr(self.assignments, "revert_button"):
                self.assignments.revert_button.configure(state="normal")

        moved_ids = affected_pids if is_whole else product_ids
        self.reconcile_inventory_products(moved_ids, affected_slots=(address.slot_name,))
        if is_whole:
            self.status_text.set(
                f"Assigned all {moved} on-hand product(s) to {address.slot_name}. Saved immediately."
            )
        else:
            self.status_text.set(
                f"Assigned {moved} product(s) to {address.slot_name}. Saved immediately."
            )

    def revert_latest_shift_transfer(self) -> None:
        if not self.last_shift_transfer:
            return
        products = self.last_shift_transfer.get("products", [])
        confirm = messagebox.askyesno(
            "Revert shift transfer",
            f"Revert the latest shift transfer of {len(products)} product(s)?",
            parent=self.root,
        )
        if not confirm:
            return

        try:
            self.database.revert_shift_transfer(self.last_shift_transfer)
        except Exception as error:
            messagebox.showerror(
                "Revert failed", f"Could not revert shift transfer: {error}", parent=self.root
            )
            return

        for item in products:
            pid = item["product_id"]
            if item.get("prev_transferred_stock") is not None:
                self.transferred_stock[pid] = item["prev_transferred_stock"]
            else:
                self.transferred_stock.pop(pid, None)

        self.last_shift_transfer = None
        if hasattr(self.assignments, "revert_button"):
            self.assignments.revert_button.configure(state="disabled")
        self.reconcile_inventory_products(item["product_id"] for item in products)
        self.status_text.set("Successfully reverted the latest shift transfer.")


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
        self.reconcile_inventory_products(
            (pid for pid, _name, _placement in contents),
            affected_slots=(address.slot_name,),
        )
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
        self.reconcile_inventory_products(product_ids, affected_slots=(address.slot_name,))
        self.status_text.set(
            f"Moved {moved} selected product(s) from {address.slot_name} to on-hand."
        )

    def modify_selected_stock(self) -> None:
        if self.selected_address is None:
            messagebox.showinfo("Load an address", "Load a shelf address first.", parent=self.root)
            return
        self._modify_loaded_address_stock()

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
                modified_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            )
        except Exception as error:
            messagebox.showerror(
                "Stock could not be updated", str(error), parent=self.root
            )
            return
        self.reconcile_inventory_products(
            (product_id,),
            affected_slots=(address.slot_name,),
            queue_changed=False,
            catalog_changed=False,
            hand_changed=False,
        )
        self.status_text.set(
            f"Updated {product_id} stock at {address.slot_name}: {current_text} → {quantity}."
        )

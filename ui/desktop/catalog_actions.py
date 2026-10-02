"""Tkinter actions for searching, importing, and updating the catalog."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

from .assignment_view import StockQuantityDialog
from mapper.core.common import MAX_VISIBLE_PRODUCTS, normalize_search
from mapper.features.csv_import import read_csv
from .csv_dialog import ColumnMappingDialog
from .widgets import sync_tree_rows


class CatalogActions:
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

    def transfer_catalog_selection_to_queue(self, to_shelf: bool | None = None) -> None:
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

        is_to_shelf = (
            not getattr(self.assignments, "whole_mode", False)
            if to_shelf is None else to_shelf
        )
        if is_to_shelf:
            if self.selected_address is None:
                messagebox.showinfo(
                    "Load an address",
                    "Enter the shelf address and press Load address first.",
                    parent=self.root,
                )
                return

            if len(product_ids) > 1:
                if hasattr(self.assignments, "search_location_text"):
                    self.assignments.search_location_text.set(
                        f"Cannot transfer: Direct catalog transfer only affects 1 product ID (selected {len(product_ids)})."
                    )
                if hasattr(self.assignments, "search_location_label"):
                    self.assignments.search_location_label.configure(foreground="#c62828")
                return

            records = {
                product_id: self.catalog_products[product_id] for product_id in product_ids
            }
            pid = product_ids[0]
            prev_p = self.committed_placements.get(pid)
            prev_oh = getattr(self, "on_hand_products", {}).get(pid)
            prev_ret = getattr(self, "returned_queue_products", {}).get(pid)
            transfer_data = {
                "type": "catalog",
                "slot_id": self.selected_address.slot_id,
                "products": [
                    {
                        "product_id": pid,
                        "prev_placement": (prev_p.slot_name, prev_p.stock_qty, prev_p.assigned_at) if prev_p else None,
                        "prev_on_hand": prev_oh.stock_qty if prev_oh else None,
                        "was_in_on_hand": prev_oh is not None,
                        "prev_returned": prev_ret.stock_qty if prev_ret else None,
                        "was_in_returned": prev_ret is not None,
                        "was_in_products": pid in self.products,
                        "prev_transferred_stock": self.transferred_stock.get(pid),
                    }
                ],
            }
            assigned_at = datetime.now().astimezone().isoformat(timespec="seconds")
            try:
                moved = self.database.assign_catalog_direct_to_slot(
                    self.selected_address.slot_id,
                    assigned_at,
                    records,
                    default_stock=999,
                )
            except Exception as error:
                messagebox.showerror("Transfer failed", str(error), parent=self.root)
                return
            self.last_shift_transfer = transfer_data
            if hasattr(self.assignments, "revert_button"):
                self.assignments.revert_button.configure(state="normal")
            for pid in product_ids:
                self.staged_assignments.pop(pid, None)
                self.pending_unassignments.discard(pid)
                self.transferred_stock.pop(pid, None)
            self.reconcile_inventory_products(
                product_ids, affected_slots=(self.selected_address.slot_name,)
            )
            self.status_text.set(
                f"Assigned {moved} catalog product(s) directly to {self.selected_address.slot_name} with stock 999. Saved immediately."
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

            self.reconcile_inventory_products(product_ids)

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

        self.reconcile_inventory_products(product_ids)

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
        self.refresh_working_changes()
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
        if getattr(self, "queue_shift_clicks", 0) > 0:
            self._reset_queue_shift_clicks()
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

        rows = []
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
            rows.append((f"product::{product_id}", values, tags))
        sync_tree_rows(self.assignments.queue_tree, rows)

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
                and query in self.location_search.get(product_id, "")
            )
        ]
        matches.sort(
            key=lambda product: (
                product[0].casefold() != raw_query.casefold(),
                product[0].casefold(),
            )
        )

        tree = self.assignments.catalog_tree
        rows = []
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
            rows.append((f"catalog::{product_id}", (product_id, product_name, location_id), ()))
        sync_tree_rows(tree, rows)

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
            product_id = self.product_id_lookup.get(raw_query.casefold())

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
            f"Duplicate IDs inside CSV: {duplicates:,}\n\n"
            "Shelf assignments, stock, and stored catalog names were kept.",
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
        self.refresh_all_views()
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

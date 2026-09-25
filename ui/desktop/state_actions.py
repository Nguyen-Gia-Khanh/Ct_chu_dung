"""Reload database state and refresh desktop views."""

from __future__ import annotations


from mapper.core.common import make_slot_name, normalize_search
from mapper.persistence.database import Placement


class StateActions:
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
        if hasattr(self, "exceptions_view"):
            self.exceptions_view.refresh()

    def on_exception_data_changed(self) -> None:
        self.reload_database_state(reload_catalog=True)
        self.refresh_all_views()

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
        self.product_id_lookup = {
            product_id.casefold(): product_id for product_id in self.products
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
        self.product_id_lookup.update(
            {product_id.casefold(): product_id for product_id in self.catalog_products}
        )
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
        self.location_search = {
            product_id: normalize_search(location)
            for product_id, location in self.committed_locations.items()
        }
        if hasattr(self, "transferred_stock"):
            self.transferred_stock = {
                pid: qty
                for pid, qty in self.transferred_stock.items()
                if pid in self.products
            }
        self.refresh_shelf_selector()
        if hasattr(self, "primal_view"):
            self.primal_view.refresh(reload_catalog=reload_catalog)

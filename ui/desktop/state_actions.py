"""Keep desktop caches and visible widgets in sync with SQLite."""

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
        if hasattr(self, "assignments"):
            self.assignments.refresh_shelf_preview()
        self.refresh_change_summary()
        if hasattr(self, "exceptions_view"):
            self.exceptions_view.refresh()

    def refresh_visible_cells(self, slot_names) -> None:
        """Read only changed cells, and touch only the shelf currently on screen."""
        active = self.notebook.select()
        names = set(slot_names)
        for slot_name in names:
            show_assignment = (
                active == str(self.assignments)
                and (
                    (
                        self.assignments.hand_view.get() == "shelf"
                        and slot_name in self.assignments.shelf_slot_names
                    )
                    or (
                        self.selected_address is not None
                        and self.selected_address.slot_name == slot_name
                    )
                )
            )
            show_primal = (
                active == str(self.primal_view)
                and slot_name in self.primal_view.slot_buttons
            )
            show_browser = (
                active == str(self.shelf_browser)
                and self.shelf_browser.current_shelf_id is not None
                and slot_name in self.shelf_browser.view.slot_buttons
            )
            panes = (
                (self.cell_transfer.left, self.cell_transfer.right)
                if active == str(self.cell_transfer) else ()
            )
            visible_panes = [pane for pane in panes if slot_name in pane.slot_buttons]
            if not (show_assignment or show_primal or show_browser or visible_panes):
                continue
            address = self.database.get_slot_by_name(slot_name)
            if address is None:
                continue  # A structural reload handles removed cells.
            contents = self.database.get_slot_contents(address.slot_id)
            if show_assignment:
                if self.assignments.hand_view.get() == "shelf" and slot_name in self.assignments.shelf_slot_names:
                    self.assignments.refresh_shelf_cell(slot_name, len(contents))
                if self.selected_address is not None and self.selected_address.slot_name == slot_name:
                    self.refresh_address_contents(contents)
            if show_primal:
                self.primal_view.refresh_cell(slot_name, contents)
            if show_browser:
                self.shelf_browser.refresh_cell(slot_name, contents)
            for pane in visible_panes:
                pane.refresh_cell(slot_name, contents)

    def apply_inventory_changes(
        self,
        *,
        placements: dict[str, Placement | None] | None = None,
        on_hand: dict | None = None,
        returned: dict | None = None,
        affected_slots=(),
        queue_changed: bool = True,
        catalog_changed: bool = True,
        hand_changed: bool = True,
    ) -> None:
        """Update known post-commit records without reloading the warehouse."""
        slots = set(affected_slots)
        if placements is not None:
            for product_id, placement in placements.items():
                old = self.committed_placements.get(product_id)
                if old is not None:
                    slots.update(old.slot_name.split(", "))
                if placement is None:
                    self.committed_placements.pop(product_id, None)
                    self.committed_locations.pop(product_id, None)
                    self.location_search.pop(product_id, None)
                else:
                    self.committed_placements[product_id] = placement
                    self.committed_locations[product_id] = placement.slot_name
                    self.location_search[product_id] = normalize_search(placement.slot_name)
                    slots.update(placement.slot_name.split(", "))
        if on_hand is not None:
            for product_id, item in on_hand.items():
                if item is None:
                    self.on_hand_products.pop(product_id, None)
                else:
                    self.on_hand_products[product_id] = item
        if returned is not None:
            for product_id, item in returned.items():
                if item is None:
                    self.returned_queue_products.pop(product_id, None)
                else:
                    self.returned_queue_products[product_id] = item
        if queue_changed and (placements is not None or on_hand is not None or returned is not None):
            self.refresh_product_queue()
        if catalog_changed and placements is not None:
            self.refresh_catalog()
        else:
            self.refresh_search_location()
        if hand_changed and on_hand is not None:
            self.refresh_on_hand_queue()
        self.refresh_change_summary()
        self._preview_dirty = True
        self.refresh_visible_cells(slots)

    def refresh_working_changes(self) -> None:
        """Refresh staged queue state without touching committed shelf views."""
        self.refresh_product_queue()
        self.refresh_catalog()
        self.refresh_change_summary()
        self._preview_dirty = True
        if self.notebook.select() == str(self.shelf_browser) and self.shelf_browser.current_shelf_id is None:
            self.render_shelf()
            self._preview_dirty = False

    def remember_imported_products(self, records: dict[str, tuple[str, str]]) -> None:
        """Mirror a successful product upsert in the search caches."""
        for product_id, (name, short_name) in records.items():
            short_name = short_name or name
            self.products[product_id] = name
            self.product_shortened_names[product_id] = short_name
            self.product_search[product_id] = normalize_search(
                f"{product_id} {name} {short_name}"
            )
            self.product_id_lookup[product_id.casefold()] = product_id

    def reconcile_inventory_products(
        self, product_ids, *, affected_slots=(), queue_changed: bool = True,
        catalog_changed: bool = True, hand_changed: bool = True,
    ) -> None:
        """Narrow SQLite readback for writes that may affect exception placements."""
        states = self.database.get_product_inventory_states(product_ids)
        if not states:
            self.refresh_visible_cells(affected_slots)
            return
        if not hasattr(self, "catalog_only_products"):
            self.catalog_only_products = set()
        for product_id, state in states.items():
            if state.get("catalog_only", False):
                self.catalog_only_products.add(product_id)
            else:
                self.catalog_only_products.discard(product_id)
            product = state["product"]
            if product is None:
                self.products.pop(product_id, None)
                self.product_shortened_names.pop(product_id, None)
                self.product_search.pop(product_id, None)
                if product_id not in self.catalog_products:
                    self.product_id_lookup.pop(product_id.casefold(), None)
            else:
                self.remember_imported_products({product_id: product})
                if product_id in self.catalog_products:
                    self.catalog_products[product_id] = product
                    self.catalog_search[product_id] = normalize_search(
                        f"{product_id} {product[0]} {product[1]}"
                    )
        self.apply_inventory_changes(
            placements={pid: state["placement"] for pid, state in states.items()},
            on_hand={pid: state["on_hand"] for pid, state in states.items()},
            returned={pid: state["returned"] for pid, state in states.items()},
            affected_slots=affected_slots,
            queue_changed=queue_changed,
            catalog_changed=catalog_changed,
            hand_changed=hand_changed,
        )

    def on_exception_data_changed(self) -> None:
        self.reload_database_state(reload_catalog=True)
        self.refresh_all_views()

    def reload_database_state(
        self, reload_catalog: bool = False, *, reload_shelves: bool = False
    ) -> None:
        product_rows = self.database.get_product_records()
        self.catalog_only_products = self.database.get_catalog_only_product_ids()
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
            catalog_rows = self.database.get_display_catalog_products()
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
        if reload_shelves:
            self.refresh_shelf_selector()
            if hasattr(self, "primal_view"):
                self.primal_view.refresh()

"""Tkinter actions for shelf design and whole-cell transfers."""

from __future__ import annotations

from tkinter import messagebox

from mapper.core.common import make_slot_name
from mapper.persistence.database import LayoutConflictError, Placement


class ShelfActions:
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
        if hasattr(self, "cell_transfer"):
            self.cell_transfer.refresh()

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
        self.reload_database_state(reload_shelves=True)
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

"""Tkinter actions for shelf design and whole-cell transfers.

Tab 1 previews and commits through one layout plan (mapper.services.layout_plan):
removed cells that still hold products become ghost cells, and inserted or removed
rows move the rows above them together with their products.
"""

from __future__ import annotations

from dataclasses import replace
from tkinter import messagebox

from mapper.core.common import clean_location_segment, split_locations
from mapper.persistence.database import LayoutConflictError, Placement
from mapper.services.layout_plan import LayoutPlan, ghost_warning, plan_layout


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
            self.designer.revert_location_id_var.get(),
            tuple(count.get() for count in self.designer.row_inputs),
            tuple(self.designer.row_origins),
        )

    def _plan_layout(self, floor: str, side: str, shelf_code: str, layout: list[int],
                     reverse: bool) -> tuple[LayoutPlan, dict[str, str]]:
        """Plan the editor's rows against the loaded saved shelf. Occupancy counts the
        designer's own pending removals and staged products. Returns the plan and the
        saved-ID -> planned-ID map."""
        origins = self.designer.row_origins if len(self.designer.row_origins) == len(layout) else None
        if self.current_shelf_id is None:
            return plan_layout([], 0, layout, floor=floor, side=side, shelf_code=shelf_code,
                               revert_location_id=reverse, row_origins=[None] * len(layout)), {}
        row_count, cells = self.database.get_layout_cells(self.current_shelf_id)
        to_saved = {planned: saved for saved, planned in self._preview_renames.items()}
        occupied = {placement.slot_name for pid, _name, placement in self.database.get_shelf_contents(self.current_shelf_id)
                    if pid not in self.pending_unassignments and pid not in self.staged_assignments}
        occupied |= {to_saved.get(item.slot_name, item.slot_name) for item in self.staged_assignments.values()}
        cells = [replace(cell, occupied=cell.name in occupied) for cell in cells]
        plan = plan_layout(cells, row_count, layout, floor=floor, side=side, shelf_code=shelf_code,
                           revert_location_id=reverse, row_origins=origins)
        return plan, {cell.name: plan.kept[cell.key].name for cell in cells if cell.key in plan.kept}

    def refresh_ghost_warning(self) -> None:
        """Tab 1's red line, recomputed from the typed rows without any popup."""
        if self.current_shelf_id is None:
            self.designer.set_ghost_warning("")
            return
        layout = self.designer.typed_layout()
        if layout is None:
            return  # Leave the line as it is while a count is half typed.
        floor, side, shelf_code = (clean_location_segment(variable.get()) or "X" for variable in (
            self.designer.floor_var, self.designer.side_var, self.designer.shelf_code_var))
        try:
            plan, _renames = self._plan_layout(floor, side, shelf_code, layout,
                                               self.designer.revert_location_id_var.get())
        except (KeyError, ValueError):
            return
        self.designer.set_ghost_warning(ghost_warning(plan))

    def _refresh_preview_plan(self) -> None:
        """Plan the loaded shelf exactly as the editor shows it (after Load or Commit)."""
        if self.current_shelf_id is None or not self.preview_key:
            self._preview_plan, self._preview_renames = None, {}
            self.designer.set_ghost_warning("")
            return
        floor, side, shelf_code = self.preview_key
        self._preview_plan, self._preview_renames = self._plan_layout(
            floor, side, shelf_code, self.current_layout, self.preview_revert_location_id)
        self.designer.set_ghost_warning(ghost_warning(self._preview_plan))

    def on_rows_changed(self) -> None:
        if self.preview_key:
            self.build_shelf_preview(switch_tab=False)
        else:
            self.refresh_ghost_warning()

    def _apply_preview_renames(self, renames: dict[str, str]) -> None:
        """Show working locations under the previewed IDs. Both maps are keyed by saved
        IDs, so each preview renames from the saved shelf, never from the last preview."""
        if renames == self._preview_renames:
            return
        to_saved = {planned: saved for saved, planned in self._preview_renames.items()}

        def rename(name: str) -> str:
            saved = to_saved.get(name, name)
            return renames.get(saved, saved)

        self._preview_renames = renames
        self.staged_assignments = {
            product_id: Placement(rename(item.slot_name), item.stock_qty, item.assigned_at)
            for product_id, item in self.staged_assignments.items()
        }
        if self.current_shelf_id is not None:
            # These are working display caches. Tab 3 reads the database
            # independently and keeps showing saved metadata until Commit.
            self.committed_placements = {
                product_id: Placement(
                    ", ".join(rename(slot) for slot in split_locations(item.slot_name)),
                    item.stock_qty,
                    item.assigned_at,
                )
                for product_id, item in self.committed_placements.items()
            }
            self.committed_locations = {
                product_id: item.slot_name
                for product_id, item in self.committed_placements.items()
            }
        if self.selected_slot:
            self.selected_slot = rename(self.selected_slot)
        if hasattr(self, "shelf_browser") and self.shelf_browser.current_key == self.preview_key:
            grid = self.shelf_browser.shelf_grid
            if grid.selected:
                grid.selected = rename(grid.selected)
        # Renamed cells change the location column of the product lists.
        self.refresh_product_lists()

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
        reverse = self.designer.revert_location_id_var.get()
        try:
            plan, renames = self._plan_layout(floor, side, shelf_code, layout, reverse)
        except (KeyError, ValueError) as error:
            messagebox.showerror("Shelf preview failed", str(error))
            return False
        names = [cell.name for cell in (*plan.kept.values(), *plan.created)]
        if len(set(names)) != len(names):
            messagebox.showerror(
                "Duplicate location IDs",
                "Use a shelf code that gives each cell a distinct ID.",
            )
            return False

        self._apply_preview_renames(renames)
        self.current_layout = layout
        self.preview_key = new_key
        self.preview_revert_location_id = reverse
        self._preview_plan = plan
        if self.selected_slot not in set(names):
            self.selected_slot = None
        self.designer.set_ghost_warning(ghost_warning(plan))
        self.render_shelf()
        if switch_tab:
            self.notebook.select(self.shelf_browser)
        self.status_text.set(
            "Shelf preview updated. Commit on tab 1 to save its design."
        )
        return True

    def _saved_slot_renames(self) -> dict[str, str]:
        """Saved location ID -> the ID the current preview gives it."""
        return dict(self._preview_renames)

    def render_shelf(self) -> None:
        floor, side, shelf_code = self.preview_key or ("", "", "")
        if not hasattr(self, "shelf_browser"):
            return
        contents = []
        if self.current_shelf_id is not None:
            renamed = self._preview_renames
            contents = [(pid, name, Placement(renamed.get(p.slot_name, p.slot_name), p.stock_qty, p.assigned_at))
                        for pid, name, p in self.database.get_shelf_contents(self.current_shelf_id)
                        if pid not in self.pending_unassignments and pid not in self.staged_assignments]
        contents.extend((pid, self.products.get(pid, ""), p) for pid, p in self.staged_assignments.items())
        ghosts = [(cell.row, cell.number, cell.name) for cell in self._preview_plan.ghosts] if self._preview_plan else []
        self.shelf_browser.show_preview(floor, side, shelf_code, self.current_layout, contents,
                                        revert_location_id=self.preview_revert_location_id, ghosts=ghosts)

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
            self.refresh_visible_or_mark_stale(self.cell_transfer)

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
        self.preview_revert_location_id = False
        self._preview_plan, self._preview_renames = None, {}
        self.selected_slot = None
        self.staged_assignments.clear()
        self.pending_unassignments.intersection_update(self.transferred_stock)
        self.designer.floor_var.set("1")
        self.designer.side_var.set("1")
        self.designer.shelf_code_var.set("")
        self.designer.revert_location_id_var.set(False)
        self.designer.prepare_row_inputs([4] * 3, notify=False)
        self.designer.set_ghost_warning("")
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
            revert_location_id = self.database.get_shelf_revert_location_id(shelf_id)
        except Exception as error:
            messagebox.showerror("Shelf could not be loaded", str(error))
            return

        self.current_shelf_id = shelf_id
        self.designer.floor_var.set(floor)
        self.designer.side_var.set(side)
        self.designer.shelf_code_var.set(shelf_code)
        self.designer.revert_location_id_var.set(revert_location_id)
        self.designer.prepare_row_inputs(layout, notify=False, origins=list(range(1, len(layout) + 1)))
        self.current_layout = layout
        self.preview_key = (floor, side, shelf_code)
        self.preview_revert_location_id = revert_location_id
        self.selected_slot = None
        self.staged_assignments.clear()
        self.pending_unassignments.intersection_update(self.transferred_stock)
        self._preview_renames = {}
        self._refresh_preview_plan()
        self.saved_editor_state = self._editor_state()
        self.reload_database_state()
        self.refresh_all_views()
        self.notebook.select(self.designer_tab)
        self.status_text.set(f"Loaded {label}.")

    def delete_selected_shelf(self) -> None:
        """Immediately delete the selected saved shelf, only when it is empty."""
        label = self.shelf_selector.get()
        shelf_id = self.shelf_choices.get(label)
        if shelf_id is None:
            messagebox.showinfo(
                "Choose a shelf", "Select an existing shelf first.", parent=self.root
            )
            return
        if self.has_pending_changes(excluding_queue_transfers=True):
            messagebox.showinfo(
                "Finish pending shelf changes",
                "Commit the pending Shelf Designer changes or discard them with "
                "New shelf before deleting a saved shelf.",
                parent=self.root,
            )
            return
        if not messagebox.askyesno(
            "Delete shelf?",
            f"Delete {label} and all its rows and cells?\n\n"
            "Only empty shelves can be deleted. This saves immediately.",
            parent=self.root,
        ):
            return
        try:
            floor, side, shelf_code, _layout = self.database.get_shelf(shelf_id)
            self.database.delete_shelf(shelf_id)
        except Exception as error:
            messagebox.showerror("Shelf could not be deleted", str(error), parent=self.root)
            return

        if self.shelf_browser.current_key == (floor, side, shelf_code):
            self.shelf_browser.clear_shelf()
        if self.current_shelf_id == shelf_id:
            self.new_shelf()
        self.shelf_selector.set("")
        self.reload_database_state(reload_shelves=True)
        self.refresh_all_views()
        self.status_text.set(f"Deleted {label}.")

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
                revert_location_id=self.designer.revert_location_id_var.get(),
                row_origins=list(self.designer.row_origins),
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
        self._preview_renames = {}
        self.designer.mark_saved()
        self._refresh_preview_plan()
        kept_ghosts = sum(cell.occupied for cell in self._preview_plan.ghosts) if self._preview_plan else 0
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
            )
            + (
                f"\nGhost cells kept: {kept_ghosts}. They stay red until you move their products out."
                if kept_ghosts
                else ""
            ),
        )
        self.status_text.set(
            f"Committed Floor {floor} / Side {side} / Shelf {shelf_code} to {self.database.path.name}."
        )
        return True

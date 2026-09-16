"""Application actions: load shelves, stage placements, and commit changes.

The UI lives in designer.py and assignment_view.py. Layout lists remain ordered
from the ground upward; views alone translate them to screen coordinates.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .assignment_view import AssignmentView, StockQuantityDialog
from .common import APP_TITLE, MAX_VISIBLE_PRODUCTS, application_directory, make_slot_name, normalize_search
from .csv_import import ColumnMappingDialog, read_csv
from .database import LayoutConflictError, Placement, WarehouseDatabase
from .designer import ShelfDesigner
from .lookup_view import ProductLookupView


class WarehouseMapperApp:
    def __init__(self, root: tk.Tk, database_path: Path | None = None):
        self.root = root
        self.database = WarehouseDatabase(database_path or application_directory() / "warehouse_locations.db")
        self.products: dict[str, str] = {}
        self.product_search: dict[str, str] = {}
        self.committed_locations: dict[str, str] = {}
        self.committed_placements: dict[str, Placement] = {}
        self.staged_assignments: dict[str, Placement] = {}
        self.pending_unassignments: set[str] = set()
        self.current_layout: list[int] = []
        self.preview_key: tuple[str, str, str] | None = None
        self.current_shelf_id: int | None = None
        self.selected_slot: str | None = None
        self.shelf_choices: dict[str, int] = {}
        self.search_after_id: str | None = None

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
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Heading.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Commit.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 7))

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(12, 10))
        self.toolbar = toolbar
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text=APP_TITLE, style="Title.TLabel").pack(side="left")

        ttk.Button(toolbar, text="Import products CSV", command=self.import_csv).pack(side="left", padx=(20, 6))
        ttk.Button(toolbar, text="New shelf", command=self.new_shelf).pack(side="left", padx=6)

        ttk.Label(toolbar, text="Existing shelf:").pack(side="left", padx=(18, 5))
        self.shelf_selector = ttk.Combobox(toolbar, state="readonly", width=28)
        self.shelf_selector.pack(side="left")
        ttk.Button(toolbar, text="Load", command=self.load_selected_shelf).pack(side="left", padx=(5, 6))

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
        dialog = StockQuantityDialog(
            self.root, slot_name,
            [(product_id, self.products.get(product_id, "")) for product_id in product_ids],
        )
        self.root.wait_window(dialog)
        if dialog.result is None:
            return

        # Confirming quantities is the assignment action. Commit must persist
        # this captured value, even if the shelf is saved much later.
        assigned_at = datetime.now().astimezone().isoformat(timespec="seconds")
        for product_id, quantity in dialog.result.items():
            self.staged_assignments[product_id] = Placement(slot_name, quantity, assigned_at)

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
        for state, product_ids, placements in (
            ("Saved", saved_products, self.committed_placements),
            ("Staged", staged_products, self.staged_assignments),
        ):
            for product_id in sorted(product_ids, key=str.casefold):
                placement = placements[product_id]
                self.assignments.contents_tree.insert(
                    "", "end", iid=f"{state.lower()}::{product_id}",
                    values=(
                        product_id, self.products.get(product_id, ""),
                        placement.stock_qty if placement.stock_qty is not None else "Unknown",
                        placement.assigned_at.replace("T", " ") if placement.assigned_at else "Unknown",
                        state,
                    ),
                )

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
        self.refresh_all_views()
        self.status_text.set("Products returned to the working queue. Press Commit to save the change.")

    def schedule_queue_refresh(self, *_args: object) -> None:
        if self.search_after_id:
            self.root.after_cancel(self.search_after_id)
        self.search_after_id = self.root.after(180, self.refresh_product_queue)

    def refresh_product_queue(self) -> None:
        if self.search_after_id:
            self.root.after_cancel(self.search_after_id)
            self.search_after_id = None
        query = normalize_search(self.assignments.search_var.get().strip())
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

        self.assignments.queue_tree.delete(*self.assignments.queue_tree.get_children())
        for product_id, product_name in available[:MAX_VISIBLE_PRODUCTS]:
            self.assignments.queue_tree.insert("", "end", iid=f"product::{product_id}", values=(product_id, product_name))

        shown = min(len(available), MAX_VISIBLE_PRODUCTS)
        suffix = " — narrow the search to see more" if len(available) > MAX_VISIBLE_PRODUCTS else ""
        self.assignments.queue_count_text.set(f"{len(available):,} matching · showing {shown:,}{suffix}")

    def refresh_change_summary(self) -> None:
        changed_products = set(self.staged_assignments) | self.pending_unassignments
        self.assignments.change_summary_text.set(
            f"{len(changed_products):,} staged product change(s) · Commit writes them to SQLite"
        )

    def refresh_all_views(self) -> None:
        self.refresh_product_queue()
        self.render_shelf()
        self.refresh_change_summary()

    def reload_database_state(self) -> None:
        product_rows = self.database.get_products()
        self.products = dict(product_rows)
        self.product_search = {
            product_id: normalize_search(f"{product_id} {product_name}")
            for product_id, product_name in product_rows
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
        self.refresh_shelf_selector()
        if hasattr(self, "assignments"):
            self.refresh_product_queue()

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
        id_index, name_index = mapping_dialog.result

        records: dict[str, str] = {}
        skipped = 0
        duplicates = 0
        required_index = max(id_index, name_index)
        for row in csv_data.rows:
            if len(row) <= required_index:
                skipped += 1
                continue
            product_id = row[id_index].strip()
            product_name = row[name_index].strip()
            if not product_id or not product_name:
                skipped += 1
                continue
            if product_id in records:
                duplicates += 1
            records[product_id] = product_name

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
        if self.has_pending_changes():
            choice = messagebox.askyesnocancel(
                "Uncommitted changes", "Commit shelf and product changes before closing?"
            )
            if choice is None or (choice and not self.commit_changes()):
                return
        if self.search_after_id:
            self.root.after_cancel(self.search_after_id)
        self.root.destroy()

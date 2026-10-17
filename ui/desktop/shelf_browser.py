"""Read-only shelf browser used by the fourth notebook tab."""

from __future__ import annotations

from mapper.core.common import vietnam_time

from collections import Counter
import tkinter as tk
from tkinter import messagebox, ttk

from .assignment_view import AssignmentView
from .shelf_address_lookup import ShelfAddressLookup
from .widgets import sync_tree_rows
from mapper.persistence.database import Placement, WarehouseDatabase


class ShelfBrowserView(ttk.Frame):
    def __init__(self, parent: tk.Misc, database: WarehouseDatabase):
        super().__init__(parent, padding=10)
        self.database = database
        self.shelf_choices: dict[str, int] = {}
        self.current_shelf_id: int | None = None
        self.current_key: tuple[str, str, str] | None = None
        self.current_contents: list[tuple[str, str, Placement]] = []

        chooser = ttk.Frame(self)
        chooser.pack(fill="x", pady=(0, 8))
        ttk.Label(chooser, text="Existing shelf:").pack(side="left")
        self.shelf_selector = ttk.Combobox(chooser, state="readonly", width=42)
        self.shelf_selector.pack(side="left", padx=(6, 5))
        self.shelf_selector.bind(
            "<<ComboboxSelected>>", lambda _event: self.load_selected()
        )
        ttk.Button(chooser, text="Load shelf", command=self.load_selected).pack(
            side="left"
        )
        ttk.Button(chooser, text="Refresh list", command=self.refresh).pack(
            side="left", padx=(6, 0)
        )
        ttk.Label(
            chooser,
            text="Read-only view",
            foreground="#555555",
        ).pack(side="right")

        self.shelf_address_lookup = ShelfAddressLookup(
            self, self.database.list_shelves, self.show_saved_shelf
        )
        self.shelf_address_lookup.pack(fill="x", pady=(0, 8))

        self.view = AssignmentView(
            self,
            lambda *_args: None,
            lambda: None,
            None,
            self.select_slot,
            read_only=True,
        )
        self.view.pack(fill="both", expand=True)
        self.view.hide_product_panel()
        self.view.empty_shelf_message = "Choose a shelf above."
        self.clear_shelf()

    def clear_shelf(self) -> None:
        self.current_shelf_id = None
        self.current_key = None
        self.current_contents = []
        self.shelf_selector.set("")
        self.shelf_address_lookup.set_address("", "", "")
        self.view.change_summary_text.set("Committed SQLite data")
        self.view.active_shelf_text.set("Choose a shelf above")
        self.view.render_shelf("", "", [], {}, None)

    def refresh(self, *, select_shelf_id: int | None = None) -> None:
        choices = self.database.list_shelves()
        self.shelf_choices = {
            f"Floor {floor} — Side {side} — Shelf {shelf_code}": shelf_id
            for shelf_id, floor, side, shelf_code in choices
        }
        self.shelf_selector.configure(values=list(self.shelf_choices))
        target = (
            select_shelf_id if select_shelf_id is not None else self.current_shelf_id
        )
        if target is not None:
            for label, shelf_id in self.shelf_choices.items():
                if shelf_id == target:
                    self.shelf_selector.set(label)
                    break
            else:
                self.shelf_selector.set("")
                self.current_shelf_id = None
        elif self.shelf_selector.get() not in self.shelf_choices:
            self.shelf_selector.set("")

    def load_selected(self) -> None:
        shelf_id = self.shelf_choices.get(self.shelf_selector.get())
        if shelf_id is None:
            messagebox.showinfo(
                "Choose a shelf",
                "Select an existing shelf first.",
                parent=self,
            )
            return
        self.show_saved_shelf(shelf_id)

    def show_saved_shelf(self, shelf_id: int) -> None:
        try:
            floor, side, shelf_code, layout = self.database.get_shelf(shelf_id)
            contents = self.database.get_shelf_contents(shelf_id)
        except Exception as error:
            messagebox.showerror("Shelf could not be loaded", str(error), parent=self)
            return
        self.current_shelf_id = shelf_id
        self.current_contents = contents
        self.shelf_address_lookup.set_address(floor, side, shelf_code)
        self._show_layout(
            floor,
            side,
            shelf_code,
            layout,
            contents,
            summary="Committed SQLite data",
        )
        self.refresh(select_shelf_id=shelf_id)

    def show_preview(
        self,
        floor: str,
        side: str,
        shelf_code: str,
        layout: list[int],
        contents: list[tuple[str, str, Placement]] | None = None,
    ) -> None:
        """Show an editor preview without pretending it is already committed."""
        self.current_shelf_id = None
        self.shelf_selector.set("")
        self.shelf_address_lookup.set_address(floor, side, shelf_code)
        self.current_contents = list(contents or [])
        self._show_layout(
            floor,
            side,
            shelf_code,
            layout,
            self.current_contents,
            summary="Uncommitted shelf preview",
        )

    def _show_layout(
        self,
        floor: str,
        side: str,
        shelf_code: str,
        layout: list[int],
        contents: list[tuple[str, str, Placement]],
        *,
        summary: str,
    ) -> None:
        self.current_key = (floor, side, shelf_code)
        counts = Counter(placement.slot_name for _, _, placement in contents)
        self.view.active_shelf_text.set(
            f"Floor {floor} · Side {side} · Shelf {shelf_code} · "
            f"{len(layout)} rows · {sum(layout)} cells"
        )
        self.view.change_summary_text.set(summary)
        self.view.render_shelf(
            floor,
            shelf_code,
            layout,
            {slot_name: (count, 0) for slot_name, count in counts.items()},
            None,
            side=side,
        )
        if self.view.selected_slot:
            self.select_slot(self.view.selected_slot)
        else:
            sync_tree_rows(self.view.contents_tree, [])

    def refresh_cell(
        self, slot_name: str, contents: list[tuple[str, str, Placement]]
    ) -> None:
        if self.current_shelf_id is None or slot_name not in self.view.slot_buttons:
            return
        self.current_contents = [
            item for item in self.current_contents if item[2].slot_name != slot_name
        ] + list(contents)
        self.view.refresh_cell(slot_name, (len(contents), 0))
        if self.view.selected_slot == slot_name:
            self.select_slot(slot_name)

    def refresh_loaded_contents(self) -> None:
        if self.current_shelf_id is None:
            return
        contents = self.database.get_shelf_contents(self.current_shelf_id)
        self.current_contents = contents
        counts = Counter(item[2].slot_name for item in contents)
        for slot_name in self.view.slot_buttons:
            self.view.refresh_cell(slot_name, (counts.get(slot_name, 0), 0))
        if self.view.selected_slot:
            self.select_slot(self.view.selected_slot)

    def select_slot(self, slot_name: str) -> None:
        self.view.mark_selected(slot_name)
        tree = self.view.contents_tree
        rows = []
        for product_id, product_name, placement in self.current_contents:
            if placement.slot_name != slot_name:
                continue
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
                    "Saved",
                ),
                (),
            ))
        sync_tree_rows(tree, rows)


ShelfBrowserFrame = ShelfBrowserView

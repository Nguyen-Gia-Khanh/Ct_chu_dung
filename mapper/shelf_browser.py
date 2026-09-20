"""Read-only shelf browser used by the fourth notebook tab."""

from __future__ import annotations

from collections import Counter
import tkinter as tk
from tkinter import messagebox, ttk

from .assignment_view import AssignmentView
from .database import Placement, WarehouseDatabase


class ShelfBrowserView(ttk.Frame):
    def __init__(self, parent: tk.Misc, database: WarehouseDatabase):
        super().__init__(parent, padding=10)
        self.database = database
        self.shelf_choices: dict[str, int] = {}
        self.current_shelf_id: int | None = None
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
        self.view.contents_tree.delete(*self.view.contents_tree.get_children())

    def select_slot(self, slot_name: str) -> None:
        self.view.mark_selected(slot_name)
        tree = self.view.contents_tree
        tree.delete(*tree.get_children())
        for product_id, product_name, placement in self.current_contents:
            if placement.slot_name != slot_name:
                continue
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
                    "Saved",
                ),
            )

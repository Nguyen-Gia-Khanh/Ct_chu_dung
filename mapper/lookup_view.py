"""Read-only product lookup, independent of the shelf editor's staged changes."""

from __future__ import annotations

import tkinter as tk
from collections import Counter
from tkinter import ttk

from .assignment_view import AssignmentView
from .common import MAX_VISIBLE_PRODUCTS, normalize_search
from .database import Placement, WarehouseDatabase
from utils.barcode_scanner import format_product_id


class ProductLookupView(ttk.Frame):
    def __init__(self, parent, database: WarehouseDatabase):
        super().__init__(parent)
        self.database = database
        self.products: dict[str, str] = {}
        self.shortened_names: dict[str, str] = {}
        self.search_text: dict[str, str] = {}
        self.selected_product_id: str | None = None
        self.shelf_contents: list[tuple[str, str, Placement]] = []
        self.search_after_id: str | None = None
        self.visible_ids: list[str] = []
        self.target_slot: str | None = None

        header = ttk.Frame(self, padding=(10, 8))
        header.pack(fill="x")
        ttk.Label(
            header,
            text="Search the full product catalog. Type an ID and press Enter, or select a product below.",
        ).pack(anchor="w")
        self.result_text = tk.StringVar(self, "Choose a product to see its committed location.")
        ttk.Label(
            header, textvariable=self.result_text, style="Heading.TLabel", wraplength=1150,
        ).pack(anchor="w", pady=(6, 0))
        self.view = AssignmentView(
            self, self.schedule_search, self.find_product, None, self.select_slot, read_only=True,
        )
        self.view.pack(fill="both", expand=True)
        self.view.change_summary_text.set("Read-only · committed locations only")
        self.view.search_entry.bind("<Return>", self.find_product, add="+")
        self.view.queue_tree.bind("<<TreeviewSelect>>", self.on_product_selected)
        self.view.queue_tree.bind("<Return>", self.find_product)

    def refresh(self) -> None:
        """Called on tab entry; never load a shelf into the editing controller."""
        self._cancel_search()
        catalog_rows = self.database.get_catalog_products()
        self.products = {
            product_id: product_name
            for product_id, product_name, _shortened_name in catalog_rows
        }
        self.shortened_names = {
            product_id: shortened_name
            for product_id, _product_name, shortened_name in catalog_rows
        }
        self.search_text = {
            product_id: normalize_search(
                f"{product_id} {product_name} {self.shortened_names[product_id]}"
            )
            for product_id, product_name in self.products.items()
        }
        self.refresh_results()
        if self.selected_product_id is not None:
            self.show_product(self.selected_product_id)

    def _cancel_search(self) -> None:
        if self.search_after_id is not None:
            self.after_cancel(self.search_after_id)
            self.search_after_id = None

    def schedule_search(self, *_args) -> None:
        self._cancel_search()
        self.search_after_id = self.after(180, self.refresh_results)

    def refresh_results(self) -> None:
        self._cancel_search()
        raw_query = self.view.search_var.get().strip()
        query = normalize_search(raw_query)
        matches = [product_id for product_id in self.products if query in self.search_text[product_id]]
        # An exact ID must stay visible even when many names/IDs also contain it.
        matches.sort(key=lambda product_id: (product_id != raw_query, product_id.casefold() != raw_query.casefold()))
        self.visible_ids = matches[:MAX_VISIBLE_PRODUCTS]
        tree = self.view.queue_tree
        tree.delete(*tree.get_children())
        for product_id in self.visible_ids:
            tree.insert(
                "",
                "end",
                iid=f"product::{product_id}",
                values=(product_id, self.products[product_id], self.shortened_names[product_id]),
            )
        self.view.queue_count_text.set(
            f"{len(matches):,} matching / {len(self.products):,} imported"
            + (f" · showing first {MAX_VISIBLE_PRODUCTS:,}; refine search" if len(matches) > MAX_VISIBLE_PRODUCTS else "")
        )
        if self.selected_product_id in self.visible_ids:
            tree.selection_set(f"product::{self.selected_product_id}")
        else:
            self.clear_result(
                "No full-catalog products imported yet. Use Import full catalog CSV on tab 1 or 2."
                if not self.products else
                "No matching product in the full catalog." if not matches else
                "Choose a product to see its committed location."
            )

    def find_product(self, _event=None) -> str:
        raw_query = self.view.search_var.get().strip()
        formatted_query = format_product_id(raw_query)
        if formatted_query != raw_query:
            self.view.search_var.set(formatted_query)
        raw_query = formatted_query

        self.refresh_results()
        exact = [product_id for product_id in self.products if product_id.casefold() == raw_query.casefold()]
        if raw_query in self.products:
            product_id = raw_query
        elif len(exact) == 1:
            product_id = exact[0]
        elif len(self.visible_ids) == 1:
            product_id = self.visible_ids[0]
        elif self.selected_product_id in self.visible_ids:
            product_id = self.selected_product_id
        else:
            if self.visible_ids:
                self.clear_result("Several products match. Select one, or enter its complete product ID.")
            return "break"
        self.view.queue_tree.selection_set(f"product::{product_id}")
        self.view.queue_tree.see(f"product::{product_id}")
        self.show_product(product_id)
        return "break"

    def on_product_selected(self, _event=None) -> None:
        selected = self.view.queue_tree.selection()
        if selected:
            product_id = selected[0].removeprefix("product::")
            if product_id != self.selected_product_id:
                self.show_product(product_id)

    def clear_result(self, message: str) -> None:
        self.selected_product_id = None
        self.target_slot = None
        self.shelf_contents = []
        self.result_text.set(message)
        self.view.active_shelf_text.set("No saved shelf selected")
        self.view.render_shelf("", "", [], {}, None)
        self.view.contents_tree.delete(*self.view.contents_tree.get_children())

    def show_product(self, product_id: str) -> None:
        if product_id not in self.products:
            self.clear_result("Product ID not found in the full catalog.")
            return
        name = self.products[product_id]
        location = self.database.get_product_location(product_id)
        if location is None:
            self.clear_result(f"{product_id} — {name}\nNo committed location. Assign it on tab 2 and Commit first.")
            self.selected_product_id = product_id
            return

        floor, side, code, layout = self.database.get_shelf(location.shelf_id)
        self.shelf_contents = self.database.get_shelf_contents(location.shelf_id)
        self.selected_product_id = product_id
        self.target_slot = location.placement.slot_name
        quantity = location.placement.stock_qty
        self.result_text.set(
            f"{product_id} — {name}\n"
            f"Location: {self.target_slot}  ·  Stock qty: {quantity if quantity is not None else 'Unknown'}"
        )
        self.view.active_shelf_text.set(
            f"Floor {floor} — Side {side} — Shelf {code} — Row {location.row_number} — Cell {location.slot_number}"
        )
        counts = Counter(placement.slot_name for _, _, placement in self.shelf_contents)
        self.view.render_shelf(
            floor, code, layout, {slot: (count, 0) for slot, count in counts.items()}, self.target_slot, side=side,
        )
        self.select_slot(self.target_slot)
        button = self.view.slot_buttons.get(self.target_slot)
        if button is not None:
            button.configure(background="#cfe8ff", activebackground="#b4d8ff")
            self._reveal_slot(button)

    def select_slot(self, slot_name: str) -> None:
        self.view.mark_selected(slot_name)
        tree = self.view.contents_tree
        tree.delete(*tree.get_children())
        for product_id, name, placement in self.shelf_contents:
            if placement.slot_name != slot_name:
                continue
            item_id = f"saved::{product_id}"
            tree.insert(
                "", "end", iid=item_id,
                values=(product_id, name, placement.stock_qty if placement.stock_qty is not None else "Unknown",
                        placement.assigned_at.replace("T", " ") if placement.assigned_at else "Unknown", "Saved"),
            )
            if product_id == self.selected_product_id:
                tree.selection_set(item_id)
                tree.focus(item_id)
                tree.see(item_id)

    def _reveal_slot(self, button) -> None:
        """Center the result even on shelves larger than the viewport."""
        inner, canvas = self.view.shelf_scroll.inner, self.view.shelf_scroll.canvas
        inner.update_idletasks()
        x = button.winfo_rootx() - inner.winfo_rootx()
        y = button.winfo_rooty() - inner.winfo_rooty()
        canvas.xview_moveto(max(0, (x + button.winfo_width() / 2 - canvas.winfo_width() / 2) / max(1, inner.winfo_width())))
        canvas.yview_moveto(max(0, (y + button.winfo_height() / 2 - canvas.winfo_height() / 2) / max(1, inner.winfo_height())))

    def destroy(self) -> None:
        self._cancel_search()
        super().destroy()

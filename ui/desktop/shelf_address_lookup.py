"""Direct shelf lookup controls shared by the desktop shelf views."""

from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import messagebox, ttk

from mapper.core.common import clean_location_segment


ShelfRow = tuple[int, str, str, str]


def find_shelf_id(
    shelves: list[ShelfRow], floor: str, side: str, shelf_name: str
) -> int | None:
    """Match a complete shelf address, ignoring case and surrounding spaces."""
    address = tuple(clean_location_segment(value) for value in (floor, side, shelf_name))
    if not all(address):
        return None
    for shelf_id, stored_floor, stored_side, stored_name in shelves:
        if address == tuple(
            clean_location_segment(value)
            for value in (stored_floor, stored_side, stored_name)
        ):
            return shelf_id
    return None


class ShelfAddressLookup(ttk.Frame):
    """Three address entries and a button for loading a saved shelf."""

    def __init__(
        self,
        parent: tk.Misc,
        list_shelves: Callable[[], list[ShelfRow]],
        on_load: Callable[[int], None],
    ) -> None:
        super().__init__(parent)
        self.list_shelves = list_shelves
        self.on_load = on_load
        self.floor_var = tk.StringVar(self)
        self.side_var = tk.StringVar(self)
        self.shelf_name_var = tk.StringVar(self)

        for label, variable, width in (
            ("Floor:", self.floor_var, 5),
            ("Side:", self.side_var, 5),
            ("Shelf name:", self.shelf_name_var, 8),
        ):
            ttk.Label(self, text=label).pack(side="left", padx=(0, 3))
            entry = ttk.Entry(self, textvariable=variable, width=width)
            entry.pack(side="left", padx=(0, 8))
            entry.bind("<Return>", self.load)
        ttk.Button(self, text="Find shelf", command=self.load).pack(side="left")

    def set_address(self, floor: str, side: str, shelf_name: str) -> None:
        self.floor_var.set(floor)
        self.side_var.set(side)
        self.shelf_name_var.set(shelf_name)

    def load(self, _event: tk.Event | None = None) -> str:
        floor = self.floor_var.get().strip()
        side = self.side_var.get().strip()
        shelf_name = self.shelf_name_var.get().strip()
        if not all((floor, side, shelf_name)):
            messagebox.showinfo(
                "Enter shelf address",
                "Enter floor, side, and shelf name to find a shelf.",
                parent=self,
            )
            return "break"
        shelf_id = find_shelf_id(self.list_shelves(), floor, side, shelf_name)
        if shelf_id is None:
            messagebox.showinfo(
                "Shelf not found",
                f"No saved shelf matches floor {floor}, side {side}, shelf {shelf_name}.",
                parent=self,
            )
            return "break"
        self.on_load(shelf_id)
        return "break"

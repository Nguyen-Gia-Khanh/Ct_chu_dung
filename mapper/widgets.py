"""Shared scrollable Tkinter container."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent: tk.Misc, *, horizontal: bool = False, vertical: bool = True):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, background="#ffffff")
        self.inner = ttk.Frame(self.canvas)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        if vertical:
            y_scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
            y_scroll.grid(row=0, column=1, sticky="ns")
            self.canvas.configure(yscrollcommand=y_scroll.set)
        if horizontal:
            x_scroll = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
            x_scroll.grid(row=1, column=0, sticky="ew")
            self.canvas.configure(xscrollcommand=x_scroll.set)
            self.bind_all("<Shift-MouseWheel>", self._shift_scroll_horizontal, add="+")
            self.bind_all("<Shift-Button-4>", self._shift_scroll_horizontal, add="+")
            self.bind_all("<Shift-Button-5>", self._shift_scroll_horizontal, add="+")

        self.inner.bind("<Configure>", self._update_scroll_region)
        if not horizontal:
            self.canvas.bind("<Configure>", self._fit_inner_width)

    def _update_scroll_region(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _fit_inner_width(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _shift_scroll_horizontal(self, event: tk.Event):
        # Each product tab owns a shelf scroller, but only the visible tab
        # should react. The pointer can be anywhere in that active tab/window.
        if not self.winfo_ismapped():
            return None

        if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
            units = -1
        elif getattr(event, "num", None) == 5 or getattr(event, "delta", 0) < 0:
            units = 1
        else:
            return None
        self.canvas.xview_scroll(units, "units")
        return "break"

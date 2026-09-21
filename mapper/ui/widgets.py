"""Shared scrollable Tkinter container."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ScrollableFrame(ttk.Frame):
    _WHEEL_PIXELS = 72
    _MAX_ANIMATION_STEP = 18
    _ANIMATION_DELAY_MS = 10
    _MAX_PENDING_PIXELS = 360

    def __init__(
        self,
        parent: tk.Misc,
        *,
        horizontal: bool = False,
        vertical: bool = True,
        smooth: bool = False,
    ):
        super().__init__(parent)
        self.horizontal = horizontal
        self.vertical = vertical
        self.smooth = smooth
        self._scroll_remaining = {"x": 0, "y": 0}
        self._scroll_after_ids = {"x": None, "y": None}
        canvas_options = {"highlightthickness": 0, "background": "#ffffff"}
        if smooth:
            # Make one canvas scroll unit equal one pixel. Wheel input is then
            # divided into small timed movements rather than one large jump.
            canvas_options.update(xscrollincrement=1, yscrollincrement=1)
        self.canvas = tk.Canvas(self, **canvas_options)
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

        self.inner.bind("<Configure>", self._update_scroll_region)
        if not horizontal:
            self.canvas.bind("<Configure>", self._fit_inner_width)
        self.bind_wheel_events()

    def bind_wheel_events(self) -> None:
        """Bind wheel scrolling to this frame and all of its current children."""
        pending = [self]
        while pending:
            widget = pending.pop()
            if self.vertical:
                widget.bind("<MouseWheel>", self._scroll_vertical)
                widget.bind("<Button-4>", self._scroll_vertical)
                widget.bind("<Button-5>", self._scroll_vertical)
            if self.horizontal:
                widget.bind("<Shift-MouseWheel>", self._shift_scroll_horizontal)
                widget.bind("<Shift-Button-4>", self._shift_scroll_horizontal)
                widget.bind("<Shift-Button-5>", self._shift_scroll_horizontal)
            pending.extend(widget.winfo_children())

    def _update_scroll_region(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _fit_inner_width(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)

    @staticmethod
    def _wheel_direction(event: tk.Event) -> int:
        if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
            return -1
        if getattr(event, "num", None) == 5 or getattr(event, "delta", 0) < 0:
            return 1
        return 0

    def _queue_smooth_scroll(self, axis: str, direction: int) -> None:
        remaining = self._scroll_remaining[axis] + direction * self._WHEEL_PIXELS
        self._scroll_remaining[axis] = max(
            -self._MAX_PENDING_PIXELS,
            min(self._MAX_PENDING_PIXELS, remaining),
        )
        if self._scroll_after_ids[axis] is None:
            self._animate_scroll(axis)

    def _animate_scroll(self, axis: str) -> None:
        self._scroll_after_ids[axis] = None
        remaining = self._scroll_remaining[axis]
        if not remaining:
            return

        magnitude = min(
            abs(remaining),
            max(2, min(self._MAX_ANIMATION_STEP, round(abs(remaining) * 0.3))),
        )
        pixels = magnitude if remaining > 0 else -magnitude
        try:
            if axis == "x":
                self.canvas.xview_scroll(pixels, "units")
            else:
                self.canvas.yview_scroll(pixels, "units")
        except tk.TclError:
            self._scroll_remaining[axis] = 0
            return

        self._scroll_remaining[axis] -= pixels
        if self._scroll_remaining[axis]:
            self._scroll_after_ids[axis] = self.after(
                self._ANIMATION_DELAY_MS,
                lambda current_axis=axis: self._animate_scroll(current_axis),
            )

    def _shift_scroll_horizontal(self, event: tk.Event):
        direction = self._wheel_direction(event)
        if not direction:
            return None
        if self.smooth:
            self._queue_smooth_scroll("x", direction)
        else:
            self.canvas.xview_scroll(direction, "units")
        return "break"

    def _scroll_vertical(self, event: tk.Event):
        if getattr(event, "state", 0) & 0x0001:
            return None

        direction = self._wheel_direction(event)
        if not direction:
            return None
        if self.smooth:
            self._queue_smooth_scroll("y", direction)
        else:
            self.canvas.yview_scroll(direction, "units")
        return "break"

"""Shared Tkinter widgets: a canvas-drawn shelf grid, Treeview syncing, and a scrollable frame."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from weakref import WeakSet

from mapper.services.shelf_grid import GridCell, ShelfGrid, cell_color


def products_label(count: int) -> str:
    return f"{count} product{'s' if count != 1 else ''}"


class ShelfGridCanvas(ttk.Frame):
    """A whole shelf drawn on one Canvas.

    Drawing rectangles takes milliseconds where one Button per cell took about half
    a second for a large shelf. Rows are listed top-down by the ShelfGrid model and
    each row's cells share its full width, like the physical shelf front.
    """

    ROW_LABEL_WIDTH = 74
    TITLE_HEIGHT = 34

    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_select: Callable[[GridCell], None] | None = None,
        label: Callable[[GridCell], str] = lambda cell: f"{cell.row}-{cell.cell}",
        count_text: Callable[[int], str] = products_label,
        row_label: Callable[[int], str] = lambda row: f"R{row}" + (" · ground" if row == 1 else ""),
        cell_width: int = 80,
        cell_height: int = 56,
        min_row_width: int = 320,
        font_size: int = 9,
        show_title: bool = True,
    ):
        super().__init__(parent)
        self.on_select = on_select
        self.label, self.count_text, self.row_label = label, count_text, row_label
        self.cell_width, self.cell_height, self.min_row_width = cell_width, cell_height, min_row_width
        self.font = ("Segoe UI", font_size)
        self.bold_font = ("Segoe UI", font_size, "bold")
        self.show_title = show_title
        self.model: ShelfGrid | None = None
        self.cells: dict[str, GridCell] = {}
        self.counts: dict[str, int] = {}
        self.staged: dict[str, int] = {}
        self.selected: str | None = None
        self._items: dict[str, tuple[int, int]] = {}
        self._slot_by_item: dict[int, str] = {}

        self.canvas = tk.Canvas(self, background="#ffffff", highlightthickness=0,
                                xscrollincrement=20, yscrollincrement=20)
        y_scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        x_scroll = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.canvas.tag_bind("cell", "<Button-1>", self._clicked)
        self.canvas.bind("<MouseWheel>", lambda e: self._wheel(e, self.canvas.yview_scroll))
        self.canvas.bind("<Shift-MouseWheel>", lambda e: self._wheel(e, self.canvas.xview_scroll))

    def __contains__(self, slot_name: object) -> bool:
        return slot_name in self.cells

    @property
    def key(self) -> tuple | None:
        return None if self.model is None else (*self.model.key, self.model.layout)

    def show(self, grid: ShelfGrid, *, selected: str | None = None, staged: dict[str, int] | None = None,
             keep_view: bool = True) -> None:
        """Draw a shelf; the same shelf with the same layout only recolors its cells."""
        counts = {cell.slot_name: cell.count for cell in grid.cells()}
        if self.key == (*grid.key, grid.layout):
            self.model, self.counts, self.staged = grid, counts, dict(staged or {})
            self.selected = selected if selected in counts else None
            for slot_name in self.cells:
                self._paint(slot_name)
            return
        self.model, self.counts, self.staged = grid, counts, dict(staged or {})
        self.selected = selected if selected in counts else None
        self._draw(keep_view=keep_view)

    def show_message(self, text: str) -> None:
        self.model, self.selected = None, None
        self.cells, self.counts, self.staged = {}, {}, {}
        self._items, self._slot_by_item = {}, {}
        self.canvas.delete("all")
        self.canvas.create_text(24, 24, text=text, anchor="nw", width=360, font=self.font, fill="#555555")
        self.canvas.configure(scrollregion=(0, 0, 400, 80))
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def set_count(self, slot_name: str, count: int, staged: int = 0) -> None:
        if slot_name in self.cells:
            self.counts[slot_name] = count
            self.staged[slot_name] = staged
            self._paint(slot_name)

    def select(self, slot_name: str | None, *, reveal: bool = True) -> None:
        previous, self.selected = self.selected, slot_name if slot_name in self.cells else None
        for name in {previous, self.selected} - {None}:
            self._paint(name)
        if reveal and self.selected is not None:
            self.reveal(self.selected)

    def select_coordinates(self, row: int, cell: int) -> str | None:
        name = next((n for n, c in self.cells.items() if (c.row, c.cell) == (row, cell)), None)
        self.select(name)
        return name

    def cell_text(self, slot_name: str) -> str:
        return self.canvas.itemcget(self._items[slot_name][1], "text")

    def cell_fill(self, slot_name: str) -> str:
        return self.canvas.itemcget(self._items[slot_name][0], "fill")

    def reveal(self, slot_name: str) -> None:
        """Scroll so the cell sits near the middle of the view."""
        self.canvas.update_idletasks()
        x1, y1, x2, y2 = self.canvas.coords(self._items[slot_name][0])
        region = self.canvas.bbox("all")
        if region is None:
            return
        for start, end, viewport, center, move in (
            (region[0], region[2], self.canvas.winfo_width(), (x1 + x2) / 2, self.canvas.xview_moveto),
            (region[1], region[3], self.canvas.winfo_height(), (y1 + y2) / 2, self.canvas.yview_moveto),
        ):
            span = end - start
            if viewport > 1 and span > viewport:
                move(max(0.0, min(1.0, (center - viewport / 2 - start) / span)))

    def _draw(self, *, keep_view: bool) -> None:
        x_view, y_view = self.canvas.xview()[0], self.canvas.yview()[0]
        self.canvas.delete("all")
        self.cells, self._items, self._slot_by_item = {}, {}, {}
        grid = self.model
        widest = max((len(row) for row in grid.rows), default=1)
        row_width = max(self.min_row_width, widest * self.cell_width)
        top = 0
        if self.show_title:
            self.canvas.create_text(
                self.ROW_LABEL_WIDTH + row_width / 2, 16, font=self.bold_font, fill="#24476b",
                text=f"FLOOR {grid.floor.upper()} · SIDE {grid.side.upper()} · SHELF {grid.shelf_code.upper()}")
            top = self.TITLE_HEIGHT
        for index, row in enumerate(grid.rows):
            y1 = top + index * (self.cell_height + 4)
            y2 = y1 + self.cell_height
            if row:
                self.canvas.create_text(self.ROW_LABEL_WIDTH - 8, (y1 + y2) / 2, anchor="e",
                                        text=self.row_label(row[0].row), font=self.font, fill="#333333")
            width = row_width / max(len(row), 1)
            for column, cell in enumerate(row):
                x1 = self.ROW_LABEL_WIDTH + column * width
                rect = self.canvas.create_rectangle(x1 + 1, y1, x1 + width - 1, y2, tags=("cell",))
                text = self.canvas.create_text((x1 + x1 + width) / 2, (y1 + y2) / 2, tags=("cell",),
                                               justify="center", width=max(width - 6, 10))
                self.cells[cell.slot_name] = cell
                self._items[cell.slot_name] = (rect, text)
                self._slot_by_item[rect] = self._slot_by_item[text] = cell.slot_name
                self._paint(cell.slot_name)
        bottom = top + len(grid.rows) * (self.cell_height + 4)
        self.canvas.create_line(0, bottom + 4, self.ROW_LABEL_WIDTH + row_width, bottom + 4, fill="#999999")
        self.canvas.configure(scrollregion=(0, 0, self.ROW_LABEL_WIDTH + row_width + 8, bottom + 12))
        self.canvas.xview_moveto(x_view if keep_view else 0)
        self.canvas.yview_moveto(y_view if keep_view else 0)

    def _paint(self, slot_name: str) -> None:
        rect, text = self._items[slot_name]
        count = self.counts.get(slot_name, 0)
        staged = self.staged.get(slot_name, 0)
        selected = slot_name == self.selected
        self.canvas.itemconfigure(rect, fill=cell_color(count + staged, staged=bool(staged), selected=selected),
                                  outline="#1f5f99" if selected else "#8a8a8a", width=3 if selected else 1)
        self.canvas.itemconfigure(text, text=f"{self.label(self.cells[slot_name])}\n{self.count_text(count + staged)}",
                                  font=self.bold_font if selected else self.font)

    def _clicked(self, _event: tk.Event) -> None:
        current = self.canvas.find_withtag("current")
        slot_name = self._slot_by_item.get(current[0]) if current else None
        if slot_name is not None and self.on_select is not None:
            self.on_select(self.cells[slot_name])

    @staticmethod
    def _wheel(event: tk.Event, scroll) -> str:
        scroll(-1 if event.delta > 0 else 1, "units")
        return "break"


def sync_tree_rows(tree: ttk.Treeview, rows: list[tuple[str, tuple, tuple]]) -> None:
    """Reconcile a filtered Treeview with (id, values, tags) rows, keeping unchanged items."""
    order = tuple(item_id for item_id, _values, _tags in rows)
    existing = tree.get_children()
    stale = set(existing).difference(order)
    if stale:
        tree.delete(*stale)
    present = set(existing) - stale
    for item_id, values, tags in rows:
        if item_id not in present:
            tree.insert("", "end", iid=item_id, values=values, tags=tags)
            continue
        if tuple(tree.item(item_id, "values")) != tuple(str(value) for value in values):
            tree.item(item_id, values=values)
        if tuple(tree.item(item_id, "tags") or ()) != tuple(tags):
            tree.item(item_id, tags=tags)
    if tree.get_children() != order:
        tree.set_children("", *order)


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
        self._wheel_bound_widgets: WeakSet[tk.Misc] = WeakSet()
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
            pending.extend(widget.winfo_children())
            if widget in self._wheel_bound_widgets:
                continue
            if self.vertical:
                widget.bind("<MouseWheel>", self._scroll_vertical)
                widget.bind("<Button-4>", self._scroll_vertical)
                widget.bind("<Button-5>", self._scroll_vertical)
            if self.horizontal:
                widget.bind("<Shift-MouseWheel>", self._shift_scroll_horizontal)
                widget.bind("<Shift-Button-4>", self._shift_scroll_horizontal)
                widget.bind("<Shift-Button-5>", self._shift_scroll_horizontal)
            self._wheel_bound_widgets.add(widget)

    def _update_scroll_region(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _fit_inner_width(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def center_widget(self, widget: tk.Widget) -> None:
        """Scroll both axes to put a child near the viewport center."""
        canvas = self.canvas
        canvas.update_idletasks()
        if not widget.winfo_exists():
            return
        region = canvas.bbox("all")
        if region is None:
            return

        # A pending smooth wheel step must not move the view away afterward.
        for axis in ("x", "y"):
            self._scroll_remaining[axis] = 0
            after_id = self._scroll_after_ids[axis]
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass
                self._scroll_after_ids[axis] = None

        for axis, start, end, viewport, target in (
            (
                "x", region[0], region[2], canvas.winfo_width(),
                widget.winfo_rootx() - self.inner.winfo_rootx() + widget.winfo_width() / 2,
            ),
            (
                "y", region[1], region[3], canvas.winfo_height(),
                widget.winfo_rooty() - self.inner.winfo_rooty() + widget.winfo_height() / 2,
            ),
        ):
            span = end - start
            if viewport <= 1 or span <= viewport:
                continue
            fraction = (target - viewport / 2 - start) / span
            if axis == "x":
                canvas.xview_moveto(max(0.0, min(1.0, fraction)))
            else:
                canvas.yview_moveto(max(0.0, min(1.0, fraction)))

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

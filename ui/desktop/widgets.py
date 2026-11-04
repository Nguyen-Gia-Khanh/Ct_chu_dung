"""Shared Tkinter widgets: a canvas-drawn shelf grid, Treeview syncing, and a scrollable frame."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk
from weakref import WeakSet

from mapper.services.shelf_grid import GridCell, ShelfGrid, cell_color, trim_ghosts


MARKED_COLOR = "#9fc5ec"
DRAG_THRESHOLD_PX = 5


def products_label(count: int) -> str:
    return f"{count} product{'s' if count != 1 else ''}"


def _grid_key(grid: ShelfGrid) -> tuple:
    """Same key means same cells: only colors and counts need repainting."""
    return (*grid.key, grid.layout, grid.revert_location_id, tuple(cell.slot_name for cell in grid.ghosts))


@dataclass
class _GridDrag:
    """A press on the grid; it becomes a selection box once the mouse moves."""
    press: tuple[int, int]
    start: tuple[float, float]   # canvas coordinates, so scrolling keeps the anchor in place
    slot_name: str | None
    select: bool                 # starting on a marked cell makes the box unmark
    pointer: tuple[int, int]
    started: bool = False
    band: int | None = None


class ShelfGridCanvas(ttk.Frame):
    """A whole shelf drawn on one Canvas.

    Drawing rectangles takes milliseconds where one Button per cell took about half
    a second for a large shelf. Rows are listed top-down by the ShelfGrid model and
    each row's cells share its full width, like the physical shelf front.

    With drag_select, dragging a box marks a block of cells (`marked`) while a plain
    click still picks one cell through on_select.
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
        drag_select: bool = False,
        on_marked: Callable[[set[str]], None] | None = None,
    ):
        super().__init__(parent)
        self.on_select = on_select
        self.on_marked = on_marked
        self.marked: set[str] = set()
        self._drag: _GridDrag | None = None
        self._autoscroll_id: str | None = None
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
        if drag_select:
            # A press only becomes a click or a box on release, once we know which.
            self.canvas.bind("<ButtonPress-1>", self._press)
            self.canvas.bind("<B1-Motion>", self._motion)
            self.canvas.bind("<ButtonRelease-1>", self._release)
            self.canvas.bind("<Escape>", self._cancel_drag)
        else:
            self.canvas.tag_bind("cell", "<Button-1>", self._clicked)
        self.canvas.bind("<MouseWheel>", lambda e: self._wheel(e, self.canvas.yview_scroll))
        self.canvas.bind("<Shift-MouseWheel>", lambda e: self._wheel(e, self.canvas.xview_scroll))

    def __contains__(self, slot_name: object) -> bool:
        return slot_name in self.cells

    @property
    def key(self) -> tuple | None:
        return None if self.model is None else _grid_key(self.model)

    def show(self, grid: ShelfGrid, *, selected: str | None = None, staged: dict[str, int] | None = None,
             keep_view: bool = True) -> None:
        """Draw a shelf; the same shelf with the same layout only recolors its cells."""
        counts = {cell.slot_name: cell.count for cell in grid.cells()}
        self.marked &= counts.keys()
        if self.key == _grid_key(grid):
            self.model, self.counts, self.staged = grid, counts, dict(staged or {})
            self.selected = selected if selected in counts else None
            for slot_name in self.cells:
                self._paint(slot_name)
            return
        self.model, self.counts, self.staged = grid, counts, dict(staged or {})
        self.selected = selected if selected in counts else None
        self._draw(keep_view=keep_view)

    def show_message(self, text: str) -> None:
        self._end_drag()
        self.model, self.selected = None, None
        self.marked = set()
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
            if self.cells[slot_name].ghost:
                # An emptied ghost (with nothing occupied to its right) leaves the drawing.
                self.show(trim_ghosts(self.model, self.counts), selected=self.selected, staged=self.staged)
                return
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
        if self._drag is not None:
            self._drag.band = None
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

    def _paint(self, slot_name: str, *, marked: bool | None = None) -> None:
        rect, text = self._items[slot_name]
        cell = self.cells[slot_name]
        count = self.counts.get(slot_name, 0)
        staged = self.staged.get(slot_name, 0)
        selected = slot_name == self.selected
        if marked is None:
            marked = slot_name in self.marked
        fill = MARKED_COLOR if marked else cell_color(count + staged, staged=bool(staged), selected=selected,
                                                      ghost=cell.ghost)
        outline = "#1f5f99" if selected else "#b03a3a" if cell.ghost else "#8a8a8a"
        self.canvas.itemconfigure(rect, fill=fill, outline=outline, width=3 if selected else 1)
        warning = "\u26a0 " if cell.ghost else ""
        self.canvas.itemconfigure(text, text=f"{warning}{self.label(cell)}\n{self.count_text(count + staged)}",
                                  font=self.bold_font if selected else self.font)

    def _clicked(self, _event: tk.Event) -> None:
        current = self.canvas.find_withtag("current")
        slot_name = self._slot_by_item.get(current[0]) if current else None
        if slot_name is not None and self.on_select is not None:
            self.on_select(self.cells[slot_name])

    # --- drag a box to mark a block of cells (drag_select=True) ---

    def set_marked(self, slot_names) -> None:
        self.marked = set(slot_names) & self.cells.keys()
        for slot_name in self.cells:
            self._paint(slot_name)
        if self.on_marked is not None:
            self.on_marked(set(self.marked))

    def _slots_in(self, left: float, top: float, right: float, bottom: float) -> set[str]:
        """Every cell the box touches, not only the ones fully inside it."""
        items = self.canvas.find_overlapping(left, top, right, bottom)
        return {self._slot_by_item[item] for item in items if item in self._slot_by_item}

    def _drag_box(self, drag: _GridDrag) -> tuple[float, float, float, float]:
        x, y = self.canvas.canvasx(drag.pointer[0]), self.canvas.canvasy(drag.pointer[1])
        return min(drag.start[0], x), min(drag.start[1], y), max(drag.start[0], x), max(drag.start[1], y)

    def _press(self, event: tk.Event) -> None:
        if self.model is None:
            return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        slot_name = next(iter(self._slots_in(x, y, x, y)), None)
        self._drag = _GridDrag((event.x, event.y), (x, y), slot_name,
                               select=slot_name not in self.marked, pointer=(event.x, event.y))

    def _motion(self, event: tk.Event) -> None:
        drag = self._drag
        if drag is None:
            return
        drag.pointer = (event.x, event.y)
        if not drag.started:
            if max(abs(event.x - drag.press[0]), abs(event.y - drag.press[1])) < DRAG_THRESHOLD_PX:
                return
            drag.started = True
            self.canvas.focus_set()  # so Esc reaches the canvas; plain clicks leave focus alone
        self._show_drag(drag)
        if self._autoscroll_id is None:
            self._autoscroll()

    def _show_drag(self, drag: _GridDrag) -> None:
        """Draw the box and preview each cell as if the mouse were released now."""
        if drag.band is None:
            drag.band = self.canvas.create_rectangle(0, 0, 0, 0, width=2, dash=(5, 3),
                                                     outline="#1f5f99" if drag.select else "#c0392b")
        box = self._drag_box(drag)
        self.canvas.coords(drag.band, *box)
        self.canvas.tag_raise(drag.band)
        hits = self._slots_in(*box)
        for slot_name in self.cells:
            self._paint(slot_name, marked=drag.select if slot_name in hits else slot_name in self.marked)

    def _autoscroll(self) -> None:
        """Keep scrolling while a drag is held past the edge of the grid."""
        self._autoscroll_id = None
        drag = self._drag
        if drag is None or not drag.started:
            return
        x, y = drag.pointer
        dx = -1 if x < 0 else 1 if x > self.canvas.winfo_width() else 0
        dy = -1 if y < 0 else 1 if y > self.canvas.winfo_height() else 0
        if not (dx or dy):
            return
        if dx:
            self.canvas.xview_scroll(dx, "units")
        if dy:
            self.canvas.yview_scroll(dy, "units")
        self._show_drag(drag)
        self._autoscroll_id = self.after(60, self._autoscroll)

    def _end_drag(self) -> _GridDrag | None:
        drag, self._drag = self._drag, None
        if self._autoscroll_id is not None:
            self.after_cancel(self._autoscroll_id)
            self._autoscroll_id = None
        if drag is not None and drag.band is not None:
            self.canvas.delete(drag.band)
        return drag

    def _release(self, event: tk.Event) -> None:
        drag = self._drag
        if drag is None:
            return
        drag.pointer = (event.x, event.y)
        hits = self._slots_in(*self._drag_box(drag)) if drag.started else set()
        self._end_drag()
        if not drag.started:
            if drag.slot_name is not None and self.on_select is not None:
                self.on_select(self.cells[drag.slot_name])
            return
        self.set_marked(self.marked | hits if drag.select else self.marked - hits)

    def _cancel_drag(self, _event: tk.Event | None = None) -> None:
        drag = self._end_drag()
        if drag is not None and drag.started:
            for slot_name in self.cells:
                self._paint(slot_name)

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

"""Shelf metadata and row inputs, displayed from the highest row down to Row 1.

A blue bar marks where Insert row adds a row; each row's ✕ removes it. Every row
remembers which saved row it came from (row_origins), so Commit moves products with
their rows. A red line lists ghost cells: removed cells that still hold products.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import tkinter as tk
from tkinter import messagebox, ttk

from mapper.core.common import clean_location_segment
from .widgets import ScrollableFrame

NEW_ROW_CELLS = 4
MAX_ROWS = 100
BAR_COLOR = "#1f6fd1"
WARNING_COLOR = "#b00020"
CELLS_EDIT_DELAY_MS = 400


def gap_at(row_middles: Sequence[float], y: float) -> int:
    """The insert gap nearest a pointer. row_middles are the rows' screen middles from
    the top row down; gap k sits between Row k and Row k + 1 (0 is below Row 1)."""
    return len(row_middles) - sum(middle < y for middle in row_middles)


class ShelfDesigner(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        on_build: Callable[[], object],
        on_rows_changed: Callable[[], None],
        on_cells_edited: Callable[[], None] | None = None,
    ):
        super().__init__(parent, padding=12)
        self.on_rows_changed = on_rows_changed
        self.on_cells_edited = on_cells_edited
        # Storage order is always bottom first: index 0 is physical Row 1.
        self.row_inputs: list[tk.StringVar] = []
        self.row_origins: list[int | None] = []   # saved row each editor row came from
        self.saved_row_count = 0                   # 0 for a shelf that is not saved yet
        self.insert_gap = 0
        self._row_trace_names: list[tuple[tk.StringVar, str]] = []
        self._row_labels: list[ttk.Label] = []
        self._cells_edit_job: str | None = None
        self.insert_bar: tk.Frame | None = None
        self.floor_var = tk.StringVar(master=self, value="1")
        self.side_var = tk.StringVar(master=self, value="1")
        self.revert_location_id_var = tk.BooleanVar(master=self, value=False)
        self.shelf_code_var = tk.StringVar(master=self, value="A")
        self.row_count_var = tk.StringVar(master=self, value="3")

        metadata = ttk.LabelFrame(self, text="Shelf metadata", padding=12)
        metadata.pack(fill="x")
        for column, label in enumerate(("Floor", "Side", "Shelf code", "Number of rows")):
            ttk.Label(metadata, text=label).grid(row=0, column=column, sticky="w")
        ttk.Entry(metadata, textvariable=self.floor_var, width=18).grid(
            row=1, column=0, padx=(0, 15), sticky="w"
        )
        ttk.Entry(metadata, textvariable=self.side_var, width=10).grid(
            row=1, column=1, padx=(0, 15), sticky="w"
        )
        ttk.Entry(metadata, textvariable=self.shelf_code_var, width=18).grid(
            row=1, column=2, padx=(0, 15), sticky="w"
        )
        self.row_count_input = ttk.Spinbox(
            metadata, from_=1, to=MAX_ROWS, textvariable=self.row_count_var,
            width=10, command=self.prepare_row_inputs,
        )
        self.row_count_input.grid(row=1, column=3, padx=(0, 15), sticky="w")
        self.row_count_input.bind("<Return>", lambda _event: self.prepare_row_inputs())
        ttk.Button(metadata, text="Apply row count", command=self.prepare_row_inputs).grid(
            row=1, column=4, padx=(0, 10)
        )
        ttk.Button(metadata, text="Build / refresh 2D shelf", command=on_build).grid(
            row=1, column=5
        )
        ttk.Label(
            metadata,
            text="Row 1 is at ground level. The row count adds or removes rows at the top. Location example: L1-1A8-10.\n"
                 "Changing a loaded shelf's metadata renames it on Commit. Use New shelf for another side.",
            foreground="#555555",
        ).grid(row=2, column=0, columnspan=6, sticky="w", pady=(10, 0))

        self.reverse_location_checkbox = ttk.Checkbutton(
            metadata, text="Reverse location ID (right to left; products stay in place)",
            variable=self.revert_location_id_var, command=self.on_rows_changed,
        )
        self.reverse_location_checkbox.grid(row=3, column=0, columnspan=6, sticky="w", pady=(8, 0))

        row_editor = ttk.LabelFrame(self, text="Rows — front view", padding=8)
        row_editor.pack(fill="both", expand=True, pady=(12, 0))
        controls = ttk.Frame(row_editor)
        controls.pack(fill="x", pady=(0, 8))
        self.insert_row_button = ttk.Button(controls, text="Insert row at bar", command=self.insert_row)
        self.insert_row_button.pack(side="left")
        ttk.Label(
            controls,
            text="Drag the blue ▶ bar between rows to choose where the new row goes. "
                 "✕ removes a row; the rows above it move down.",
            foreground="#555555",
        ).pack(side="left", padx=(10, 0))
        self.ghost_warning_var = tk.StringVar(master=self, value="")
        self.ghost_warning = ttk.Label(
            row_editor, textvariable=self.ghost_warning_var, foreground=WARNING_COLOR,
            font=("Segoe UI", 9, "bold"), wraplength=820, justify="left",
        )
        self.row_editor_scroll = ScrollableFrame(row_editor)
        self.row_editor_scroll.pack(fill="both", expand=True)
        self.prepare_row_inputs(notify=False)

    # --- row list ---

    def prepare_row_inputs(
        self, layout: list[int] | None = None, *, notify: bool = True,
        origins: Sequence[int | None] | None = None,
    ) -> bool:
        """With a layout (loading a shelf): show it, with origins for a saved shelf.
        Without one: apply the typed row count, adding or removing rows at the top."""
        try:
            row_count = len(layout) if layout is not None else int(self.row_count_var.get())
        except ValueError:
            messagebox.showerror("Invalid rows", "Number of rows must be a whole number.")
            return False
        if not 1 <= row_count <= MAX_ROWS:
            messagebox.showerror("Invalid rows", f"Number of rows must be between 1 and {MAX_ROWS}.")
            return False

        bar_on_top = layout is not None or self.insert_gap >= len(self.row_inputs)
        if layout is not None:
            values = list(layout)
            new_origins = list(origins) if origins is not None else [None] * row_count
            self.saved_row_count = sum(origin is not None for origin in new_origins)
        else:
            # Keep the lower rows exactly as entered. Only truncate/extend the top.
            old_values = [count.get() for count in self.row_inputs]
            values = old_values[:row_count] + [NEW_ROW_CELLS] * (row_count - len(old_values))
            new_origins = self.row_origins[:row_count] + [None] * (row_count - len(self.row_origins))
        if bar_on_top:
            self.insert_gap = row_count
        self._build_rows(values, new_origins)
        if notify:
            self.on_rows_changed()
        return True

    def insert_row(self) -> None:
        """Add a row at the bar; every row above it moves up by one."""
        if len(self.row_inputs) >= MAX_ROWS:
            return
        values = [count.get() for count in self.row_inputs]
        origins = list(self.row_origins)
        gap = self.insert_gap
        values.insert(gap, str(NEW_ROW_CELLS))
        origins.insert(gap, None)
        self.insert_gap = gap + 1
        self._build_rows(values, origins)
        self.on_rows_changed()

    def remove_row(self, row_number: int) -> None:
        """Remove one row; every row above it moves down by one."""
        if len(self.row_inputs) <= 1 or not 1 <= row_number <= len(self.row_inputs):
            return
        values = [count.get() for count in self.row_inputs]
        origins = list(self.row_origins)
        del values[row_number - 1], origins[row_number - 1]
        if self.insert_gap >= row_number:
            self.insert_gap -= 1
        self._build_rows(values, origins)
        self.on_rows_changed()

    def mark_saved(self) -> None:
        """After Commit, every row is its own saved row again."""
        self.row_origins = list(range(1, len(self.row_inputs) + 1))
        self.saved_row_count = len(self.row_inputs)
        for row_number, label in enumerate(self._row_labels, start=1):
            label.configure(text=self._row_label_text(row_number))

    def row_labels(self) -> list[str]:
        """Row label texts as shown, top row first."""
        return [label.cget("text") for label in reversed(self._row_labels)]

    def _row_label_text(self, row_number: int) -> str:
        origin = self.row_origins[row_number - 1]
        history = ""
        if self.saved_row_count:
            history = " (new)" if origin is None else f" (was {origin})" if origin != row_number else ""
        return f"Row {row_number}{history}" + (" — ground" if row_number == 1 else "")

    # Grid rows: headings at 0, then the top gap, the top row, the gap below it, and so on.
    def _gap_grid_row(self, gap: int) -> int:
        return 1 + 2 * (len(self.row_inputs) - gap)

    def _row_grid_row(self, row_number: int) -> int:
        return 2 + 2 * (len(self.row_inputs) - row_number)

    def _build_rows(self, values: list, origins: list[int | None]) -> None:
        for variable, trace_name in self._row_trace_names:
            variable.trace_remove("write", trace_name)
        self._row_trace_names.clear()
        inner = self.row_editor_scroll.inner
        for child in inner.winfo_children():
            child.destroy()
        self.row_inputs = [tk.StringVar(master=self, value=str(count)) for count in values]
        self.row_origins = list(origins)
        self._row_labels = []
        row_count = len(values)
        self.insert_gap = max(0, min(self.insert_gap, row_count))
        self.row_count_var.set(str(row_count))
        for column, heading in enumerate(("Row", "Cells in row", "Result", "")):
            ttk.Label(inner, text=heading, style="Heading.TLabel").grid(
                row=0, column=column, padx=10, pady=(5, 4), sticky="w"
            )
        for gap in range(row_count + 1):
            inner.rowconfigure(self._gap_grid_row(gap), minsize=8)

        for row_number, count_var in enumerate(self.row_inputs, start=1):
            # Tk grids count downward; physical shelf rows count upward.
            grid_row = self._row_grid_row(row_number)
            label = ttk.Label(inner, text=self._row_label_text(row_number))
            label.grid(row=grid_row, column=0, padx=10, pady=2, sticky="w")
            self._row_labels.append(label)
            ttk.Spinbox(inner, from_=1, to=200, textvariable=count_var, width=12).grid(
                row=grid_row, column=1, padx=10, pady=2, sticky="w"
            )
            result_label = ttk.Label(inner, text=f"{count_var.get() or '0'} cells across the row")
            result_label.grid(row=grid_row, column=2, padx=10, pady=2, sticky="w")
            ttk.Button(
                inner, text="✕", width=3, command=lambda row=row_number: self.remove_row(row),
                state="normal" if row_count > 1 else "disabled",
            ).grid(row=grid_row, column=3, padx=(0, 10), pady=2)

            def update_result(*_args: object, count=count_var, result=result_label) -> None:
                result.configure(text=f"{count.get() or '0'} cells across the row")
                self._schedule_cells_edited()

            trace_name = count_var.trace_add("write", update_result)
            self._row_trace_names.append((count_var, trace_name))

        bottom = self._gap_grid_row(0)
        ttk.Separator(inner).grid(row=bottom + 1, column=0, columnspan=4, sticky="ew", padx=10, pady=(8, 2))
        ttk.Label(inner, text="Ground", foreground="#555555").grid(
            row=bottom + 2, column=0, columnspan=4, sticky="w", padx=10
        )
        self._build_insert_bar(inner)
        self.insert_row_button.configure(state="disabled" if row_count >= MAX_ROWS else "normal")

    # --- insert bar ---

    def _build_insert_bar(self, inner: tk.Misc) -> None:
        bar = tk.Frame(inner, cursor="sb_v_double_arrow")
        arrow = tk.Label(bar, text="▶ new row goes here", foreground=BAR_COLOR,
                         font=("Segoe UI", 8, "bold"), cursor="sb_v_double_arrow")
        arrow.pack(side="left")
        line = tk.Frame(bar, height=3, background=BAR_COLOR, cursor="sb_v_double_arrow")
        line.pack(side="left", fill="x", expand=True, padx=(6, 0))
        for widget in (bar, arrow, line):
            widget.bind("<B1-Motion>", self._drag_insert_bar)
        self.insert_bar = bar
        bar.grid(row=self._gap_grid_row(self.insert_gap), column=0, columnspan=4, sticky="ew", padx=6)

    def set_insert_gap(self, gap: int) -> None:
        self.insert_gap = max(0, min(gap, len(self.row_inputs)))
        if self.insert_bar is not None:
            self.insert_bar.grid_configure(row=self._gap_grid_row(self.insert_gap))

    def _drag_insert_bar(self, event: tk.Event) -> None:
        inner = self.row_editor_scroll.inner
        y = event.y_root - inner.winfo_rooty()
        middles = [label.winfo_y() + label.winfo_height() / 2 for label in reversed(self._row_labels)]
        gap = gap_at(middles, y)
        if gap != self.insert_gap:
            self.set_insert_gap(gap)

    # --- ghost warning and cell edits ---

    def set_ghost_warning(self, text: str) -> None:
        """Show the red ghost-cell line above the rows, or hide it when there is none."""
        self.ghost_warning_var.set(text)
        if text and not self.ghost_warning.winfo_manager():
            self.ghost_warning.pack(fill="x", pady=(0, 6), before=self.row_editor_scroll)
        elif not text and self.ghost_warning.winfo_manager():
            self.ghost_warning.pack_forget()

    def _schedule_cells_edited(self) -> None:
        if self.on_cells_edited is None:
            return
        if self._cells_edit_job is not None:
            self.after_cancel(self._cells_edit_job)
        self._cells_edit_job = self.after(CELLS_EDIT_DELAY_MS, self._cells_edited)

    def _cells_edited(self) -> None:
        self._cells_edit_job = None
        if self.on_cells_edited is not None:
            self.on_cells_edited()

    def destroy(self) -> None:
        if self._cells_edit_job is not None:
            self.after_cancel(self._cells_edit_job)
            self._cells_edit_job = None
        super().destroy()

    # --- reading the inputs ---

    def typed_layout(self) -> list[int] | None:
        """The typed cell counts without any popup, or None while one is not valid."""
        try:
            layout = [int(count.get()) for count in self.row_inputs]
        except ValueError:
            return None
        return layout if all(1 <= count <= 200 for count in layout) else None

    def validated_layout(self) -> tuple[str, str, str, list[int]] | None:
        floor = clean_location_segment(self.floor_var.get())
        side = clean_location_segment(self.side_var.get())
        shelf_code = clean_location_segment(self.shelf_code_var.get())
        if not floor:
            messagebox.showerror("Floor missing", "Enter a floor name or code.")
            return None
        if not shelf_code:
            messagebox.showerror("Shelf code missing", "Enter the shelf alphabet/code.")
            return None
        if not side:
            messagebox.showerror("Side missing", "Enter the shelf side, for example 1 or 2.")
            return None
        try:
            row_count = int(self.row_count_var.get())
        except ValueError:
            messagebox.showerror("Invalid rows", "Number of rows must be a whole number.")
            return None
        if row_count != len(self.row_inputs) and not self.prepare_row_inputs(notify=False):
            return None

        layout: list[int] = []
        for row_number, count_var in enumerate(self.row_inputs, start=1):
            try:
                count = int(count_var.get())
            except ValueError:
                messagebox.showerror("Invalid cells", f"Row {row_number} needs a whole number of cells.")
                return None
            if not 1 <= count <= 200:
                messagebox.showerror("Invalid cells", f"Row {row_number} must have between 1 and 200 cells.")
                return None
            layout.append(count)
        return floor, side, shelf_code, layout


ShelfDesignerFrame = ShelfDesigner

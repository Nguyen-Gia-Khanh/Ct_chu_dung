"""Shelf metadata and row inputs, displayed from the highest row down to Row 1."""

from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import messagebox, ttk

from mapper.common import clean_location_segment
from .widgets import ScrollableFrame


class ShelfDesigner(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        on_build: Callable[[], object],
        can_resize: Callable[[int], bool],
        on_rows_changed: Callable[[], None],
    ):
        super().__init__(parent, padding=12)
        self.can_resize = can_resize
        self.on_rows_changed = on_rows_changed
        # Storage order is always bottom first: index 0 is physical Row 1.
        self.row_inputs: list[tk.StringVar] = []
        self.floor_var = tk.StringVar(master=self, value="1")
        self.side_var = tk.StringVar(master=self, value="1")
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
            metadata, from_=1, to=100, textvariable=self.row_count_var,
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
            text="Row 1 is at ground level. New rows are added at the top. Location example: L1-1A8-10.\n"
                 "Changing a loaded shelf's metadata renames it on Commit. Use New shelf for another side.",
            foreground="#555555",
        ).grid(row=2, column=0, columnspan=6, sticky="w", pady=(10, 0))

        row_editor = ttk.LabelFrame(self, text="Rows — front view", padding=8)
        row_editor.pack(fill="both", expand=True, pady=(12, 0))
        controls = ttk.Frame(row_editor)
        controls.pack(fill="x", pady=(0, 8))
        self.add_row_button = ttk.Button(controls, text="Add row at top", command=self.add_row)
        self.add_row_button.pack(side="left")
        self.remove_row_button = ttk.Button(
            controls, text="Remove top row", command=self.remove_top_row
        )
        self.remove_row_button.pack(side="left", padx=(8, 0))
        self.row_editor_scroll = ScrollableFrame(row_editor)
        self.row_editor_scroll.pack(fill="both", expand=True)
        self.prepare_row_inputs(notify=False)

    def add_row(self) -> None:
        self.row_count_var.set(str(len(self.row_inputs) + 1))
        self.prepare_row_inputs()

    def remove_top_row(self) -> None:
        if len(self.row_inputs) > 1:
            self.row_count_var.set(str(len(self.row_inputs) - 1))
            self.prepare_row_inputs()

    def prepare_row_inputs(
        self, layout: list[int] | None = None, *, notify: bool = True
    ) -> bool:
        try:
            row_count = len(layout) if layout is not None else int(self.row_count_var.get())
        except ValueError:
            messagebox.showerror("Invalid rows", "Number of rows must be a whole number.")
            return False
        if not 1 <= row_count <= 100:
            messagebox.showerror("Invalid rows", "Number of rows must be between 1 and 100.")
            return False
        if layout is None and row_count < len(self.row_inputs) and not self.can_resize(row_count):
            self.row_count_var.set(str(len(self.row_inputs)))
            return False

        # Keep the lower rows exactly as entered. Only truncate/extend the top.
        old_values = [count.get() for count in self.row_inputs]
        values = layout if layout is not None else old_values[:row_count]
        values = list(values) + [4] * (row_count - len(values))
        for child in self.row_editor_scroll.inner.winfo_children():
            child.destroy()
        self.row_inputs = [
            tk.StringVar(master=self, value=str(count)) for count in values
        ]
        self.row_count_var.set(str(row_count))
        headings = ("Row", "Cells in row", "Result")
        for column, heading in enumerate(headings):
            ttk.Label(self.row_editor_scroll.inner, text=heading, style="Heading.TLabel").grid(
                row=0, column=column, padx=10, pady=(5, 10), sticky="w"
            )

        for row_number, count_var in enumerate(self.row_inputs, start=1):
            # Tk grids count downward; physical shelf rows count upward.
            screen_row = row_count - row_number + 1
            label = f"Row {row_number}" + (" — ground" if row_number == 1 else "")
            ttk.Label(self.row_editor_scroll.inner, text=label).grid(
                row=screen_row, column=0, padx=10, pady=5, sticky="w"
            )
            ttk.Spinbox(
                self.row_editor_scroll.inner, from_=1, to=200,
                textvariable=count_var, width=12,
            ).grid(row=screen_row, column=1, padx=10, pady=5, sticky="w")
            result_label = ttk.Label(self.row_editor_scroll.inner)
            result_label.grid(row=screen_row, column=2, padx=10, pady=5, sticky="w")

            def update_result(*_args: object, count=count_var, result=result_label) -> None:
                result.configure(text=f"{count.get() or '0'} cells across the row")

            count_var.trace_add("write", update_result)
            update_result()

        ttk.Separator(self.row_editor_scroll.inner).grid(
            row=row_count + 1, column=0, columnspan=3, sticky="ew", padx=10, pady=(8, 2)
        )
        ttk.Label(self.row_editor_scroll.inner, text="Ground", foreground="#555555").grid(
            row=row_count + 2, column=0, columnspan=3, sticky="w", padx=10
        )
        self.add_row_button.configure(state="disabled" if row_count == 100 else "normal")
        self.remove_row_button.configure(state="disabled" if row_count == 1 else "normal")
        if notify:
            self.on_rows_changed()
        return True

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

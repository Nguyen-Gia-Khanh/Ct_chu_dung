"""Small modal dialogs shared by the desktop tabs."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from mapper.persistence.database import validate_stock_quantity
from .widgets import ScrollableFrame


class StockQuantityDialog(tk.Toplevel):
    """Collect a separate manual quantity for every selected product."""

    def __init__(
        self,
        parent: tk.Misc,
        slot_name: str,
        products: list[tuple[str, str]],
        initial_quantities: dict[str, int | None] | None = None,
        *,
        title_text: str | None = None,
        destination_label: str | None = None,
        button_text: str = "Assign products",
        footer_text: str = "Press Commit on the main window to save staged changes.",
    ):
        super().__init__(parent)
        self.result: dict[str, int] | None = None
        self.quantity_inputs: dict[str, tuple[tk.StringVar, ttk.Entry]] = {}
        self.title(title_text or f"Assign products to {slot_name}")
        self.transient(parent)
        self.geometry(f"660x{min(540, 200 + 36 * len(products))}")
        self.minsize(520, 230)

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=destination_label or f"Destination: {slot_name}").pack(
            anchor="w"
        )
        ttk.Label(
            body,
            text="Enter each product's stock quantity (whole units, 0 or more).",
            wraplength=590,
        ).pack(anchor="w", pady=(4, 10))
        rows = ScrollableFrame(body)
        rows.pack(fill="both", expand=True)
        rows.inner.columnconfigure(1, weight=1)
        for column, heading in enumerate(("Product ID", "Product name", "Stock qty")):
            ttk.Label(rows.inner, text=heading).grid(
                row=0, column=column, sticky="w", padx=5, pady=5
            )
        for row_number, (product_id, product_name) in enumerate(products, start=1):
            ttk.Label(rows.inner, text=product_id, wraplength=140).grid(
                row=row_number,
                column=0,
                sticky="w",
                padx=5,
                pady=5,
            )
            ttk.Label(rows.inner, text=product_name, wraplength=300).grid(
                row=row_number,
                column=1,
                sticky="w",
                padx=5,
                pady=5,
            )
            init_val = ""
            if initial_quantities and product_id in initial_quantities:
                qty = initial_quantities[product_id]
                if qty is not None:
                    init_val = str(qty)
            quantity = tk.StringVar(self, value=init_val)
            entry = ttk.Entry(rows.inner, textvariable=quantity, width=12)
            entry.grid(row=row_number, column=2, sticky="e", padx=5, pady=5)
            self.quantity_inputs[product_id] = (quantity, entry)

        ttk.Label(
            body,
            text=footer_text,
            wraplength=590,
        ).pack(anchor="w", pady=(10, 8))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        ttk.Button(buttons, text=button_text, command=self.confirm).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(
            side="right", padx=(0, 8)
        )
        self.bind("<Return>", self.confirm)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.lift()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        if self.quantity_inputs:
            next(iter(self.quantity_inputs.values()))[1].focus_set()
        else:
            self.focus_force()

    def confirm(self, _event=None) -> None:
        quantities = {}
        for product_id, (variable, entry) in self.quantity_inputs.items():
            try:
                text = variable.get().strip()
                if not text.isascii() or not text.isdecimal():
                    raise ValueError("Enter a whole number of units (0 or more).")
                quantity = int(text)
                validate_stock_quantity(quantity)
            except ValueError as error:
                messagebox.showerror(
                    "Invalid stock quantity", f"{product_id}: {error}", parent=self
                )
                entry.focus_set()
                entry.selection_range(0, "end")
                return
            quantities[product_id] = quantity
        self.result = quantities
        self.destroy()

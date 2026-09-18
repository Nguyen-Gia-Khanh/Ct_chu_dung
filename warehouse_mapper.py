"""Run this file with your selected Python interpreter.

Editable modules live in mapper/:
    app.py              Application actions and staged assignments.
    designer.py         Shelf metadata and left/right row inputs.
    assignment_view.py  Product queue and clickable shelf front view.
    database.py         SQLite tables and commit operations.
    csv_import.py       CSV reader and column-selection dialog.
    common.py           Location naming, search normalization, and paths.
    widgets.py          Shared scrollable frame.

Keep the mapper folder beside this script.
"""

import tkinter as tk

from mapper.app import WarehouseMapperApp
# Retain these imports for existing scripts/tests that imported from this file.
from mapper.common import make_slot_name, normalize_search
from mapper.database import LayoutConflictError, WarehouseDatabase

__all__ = ["WarehouseMapperApp", "WarehouseDatabase", "LayoutConflictError", "make_slot_name", "normalize_search", "main"]


def main() -> None:
    root = tk.Tk()
    root.state("zoomed")
    WarehouseMapperApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

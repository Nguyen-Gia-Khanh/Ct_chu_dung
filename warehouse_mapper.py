"""Run this file with your selected Python interpreter.

Choose which UI to run using the UI_MODE constant below:
    UI_MODE = "ts"       -> Launch modern TypeScript Web UI (Tab 1-5, offline browser runtime)
    UI_MODE = "tkinter"  -> Launch classic Tkinter Desktop UI

Editable modules live in mapper/:
    web_server.py       HTTP server and REST API bridge for the TypeScript UI.
    tkinter_ui/         Desktop Tkinter UI components.
    database.py         SQLite tables and commit operations.
    csv_import.py       CSV reader and column-selection dialog.
    common.py           Location naming, search normalization, and paths.

TypeScript UI source code lives in ui/:
    ui/src/             React 18 + TypeScript source files.
    ui/dist/            Self-contained offline browser build.
"""

import sys
import tkinter as tk

from mapper.tkinter_ui.app import WarehouseMapperApp
# Retain these imports for existing scripts/tests that imported from this file.
from mapper.common import make_slot_name, normalize_search
from mapper.database import LayoutConflictError, WarehouseDatabase

__all__ = [
    "UI_MODE",
    "WarehouseMapperApp",
    "WarehouseDatabase",
    "LayoutConflictError",
    "make_slot_name",
    "normalize_search",
    "main",
]

# ==============================================================================
# UI CONFIGURATION CONSTANT:
# Set to "ts" (or "vscode") to run the modern VS Code Light+ desktop app (smooth, fast, reliable).
# Set to "tkinter" to run the classic Tkinter desktop UI.
# ==============================================================================
UI_MODE = "tkinter"


def main() -> None:
    mode = UI_MODE.strip().lower()

    if mode in ("ts", "typescript", "vscode", "web", "app"):
        from mapper.web_server import run_desktop_app
        run_desktop_app(port=8000, title="Warehouse Shelf Mapper")
    elif mode == "tkinter":
        root = tk.Tk()
        root.state("zoomed")
        WarehouseMapperApp(root)
        root.mainloop()
    else:
        print(f"Error: Unknown UI_MODE {UI_MODE!r}. Please set UI_MODE to 'ts' or 'tkinter'.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

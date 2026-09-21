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
# Set to "qt" (or "pyqt") to run the modern 100% offline native desktop UI (PyQt6).
# Set to "tkinter" to run the classic Tkinter desktop UI.
# Set to "ts" to run the TypeScript browser/webview UI.
# ==============================================================================
UI_MODE = "qt"


def main() -> None:
    mode = UI_MODE.strip().lower()

    if mode in ("qt", "pyqt", "desktop", "native"):
        from mapper.qt_ui import run_qt_app
        run_qt_app()
    elif mode == "tkinter":
        root = tk.Tk()
        root.state("zoomed")
        WarehouseMapperApp(root)
        root.mainloop()
    elif mode in ("ts", "typescript", "web", "app"):
        from mapper.web_server import run_desktop_app
        run_desktop_app(port=8000, title="Warehouse Shelf Mapper")
    else:
        print(f"Error: Unknown UI_MODE {UI_MODE!r}. Please set UI_MODE to 'qt' or 'tkinter'.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

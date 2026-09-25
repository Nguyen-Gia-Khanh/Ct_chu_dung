"""Launch either supported Warehouse Shelf Mapper interface."""

from __future__ import annotations

import argparse
from pathlib import Path

from mapper.core.common import default_database_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Warehouse Shelf Mapper")
    parser.add_argument("--ui", choices=("desktop", "web"), default="desktop")
    parser.add_argument("--db", type=Path, help="Use an explicit SQLite database path")
    parser.add_argument("--port", type=int, default=8000, help="Local web API port")
    args = parser.parse_args(argv)
    try:
        database_path = args.db or default_database_path()
    except RuntimeError as error:
        parser.exit(2, f"{error}\n")

    if args.ui == "desktop":
        import tkinter as tk

        from ui.desktop.app import WarehouseMapperApp

        root = tk.Tk()
        root.state("zoomed")
        WarehouseMapperApp(root, database_path=database_path)
        root.mainloop()
    else:
        from mapper.api.server import run_desktop_app

        run_desktop_app(port=args.port, database_path=database_path)


if __name__ == "__main__":
    main()

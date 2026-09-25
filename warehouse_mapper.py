"""Launch the Tkinter warehouse mapper from the project root."""

from __future__ import annotations

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Warehouse Shelf Mapper")
    parser.add_argument("--db", type=Path, help="Use an explicit SQLite database path")
    args = parser.parse_args(argv)

    from mapper.core.common import default_database_path

    try:
        database_path = args.db or default_database_path()
    except RuntimeError as error:
        parser.exit(2, f"{error}\n")

    import tkinter as tk

    from ui.desktop.app import WarehouseMapperApp

    root = tk.Tk()
    root.state("zoomed")
    WarehouseMapperApp(root, database_path=database_path)
    root.mainloop()


if __name__ == "__main__":
    main()

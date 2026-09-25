"""Launch the deprecated local web interface from the project root."""

from __future__ import annotations

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="Use an explicit SQLite database path")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    from mapper.core.common import default_database_path
    from mapper.api.server import run_desktop_app

    try:
        database_path = args.db or default_database_path()
    except RuntimeError as error:
        parser.exit(2, f"{error}\n")
    run_desktop_app(port=args.port, database_path=database_path)


if __name__ == "__main__":
    main()

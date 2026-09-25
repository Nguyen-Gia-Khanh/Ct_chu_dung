"""Move legacy local data into ``data/`` when the refactored app is activated."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from mapper.core.common import application_directory


DATA_MOVES = (
    ("label_printouts", "data/labels"),
    ("xl/app_result", "data/exports/location_comparison"),
    ("icsparts_scrape/icsparts_output", "data/icsparts"),
)


def _check_database(path: Path) -> None:
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
        result = connection.execute("PRAGMA quick_check").fetchone()
    if result != ("ok",):
        raise RuntimeError(f"SQLite integrity check failed for {path}: {result}")


def migration_moves(root: Path) -> list[tuple[Path, Path]]:
    """Return existing sources; refuse ambiguous database or destination paths."""
    root = root.resolve()
    old_databases = [root / name for name in ("warehouse_locations.db", "warehouse.db")]
    present_databases = [path for path in old_databases if path.exists()]
    if len(present_databases) > 1:
        raise RuntimeError("Both legacy database names exist; choose the active one before migration.")

    moves = [(root / source, root / target) for source, target in DATA_MOVES]
    if present_databases:
        moves.append((present_databases[0], root / "data" / "warehouse_locations.db"))
    for source, target in moves:
        if source.exists() and target.exists():
            raise FileExistsError(f"Both source and destination exist: {source} and {target}")
    return [(source, target) for source, target in moves if source.exists()]


def migrate(root: Path, *, apply: bool = False) -> list[tuple[Path, Path]]:
    """Preview or move local data. No source is overwritten or deleted."""
    root = root.resolve()
    moves = migration_moves(root)
    if not apply or not moves:
        return moves

    database_move = next((pair for pair in moves if pair[1].name == "warehouse_locations.db"), None)
    if database_move:
        source, _ = database_move
        _check_database(source)
        backup_dir = root / "data" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"warehouse_locations_before_move_{datetime.now():%Y%m%d_%H%M%S_%f}.db"
        with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(backup)) as copy:
                original.backup(copy)
        _check_database(backup)

    for source, target in moves:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        if target.name == "warehouse_locations.db":
            _check_database(target)
    return moves


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Move files after previewing and closing the apps")
    args = parser.parse_args(argv)
    moves = migrate(application_directory(), apply=args.apply)
    if not moves:
        print("No legacy data needs moving.")
        return
    action = "Moved" if args.apply else "Would move"
    for source, target in moves:
        print(f"{action}: {source} -> {target}")
    if not args.apply:
        print("Close all mapper and printer windows, then rerun with --apply when activating the new code.")


if __name__ == "__main__":
    main()

"""Review or back up and apply the one-time floor 1 shelf direction conversion."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

VERSION = 5


def checks(connection: sqlite3.Connection) -> dict:
    result = {
        "integrity_check": [row[0] for row in connection.execute("PRAGMA integrity_check")],
        "foreign_key_check": [list(row) for row in connection.execute("PRAGMA foreign_key_check")],
    }
    if result["integrity_check"] != ["ok"] or result["foreign_key_check"]:
        raise sqlite3.IntegrityError(f"Database checks failed: {result}")
    return result


def targets(connection: sqlite3.Connection) -> list[int]:
    return [shelf_id for shelf_id, side in connection.execute("SELECT shelf_id, side FROM shelves WHERE floor = '1' ORDER BY shelf_id")
            if side.isdecimal() and int(side) % 2 == 0]


def add_direction_setting(connection: sqlite3.Connection) -> list[int]:
    """Called inside a migration transaction, including older cleanup upgrades."""
    if connection.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (VERSION,)).fetchone():
        return []
    columns = {row[1] for row in connection.execute("PRAGMA table_info(shelves)")}
    if "revert_location_id" not in columns:
        connection.execute("ALTER TABLE shelves ADD COLUMN revert_location_id INTEGER NOT NULL DEFAULT 0 "
                           "CHECK (revert_location_id IN (0, 1))")
    selected = targets(connection)
    connection.executemany("UPDATE shelves SET revert_location_id = 1 WHERE shelf_id = ?", [(sid,) for sid in selected])
    connection.execute("INSERT INTO schema_migrations(version) VALUES (?)", (VERSION,))
    return selected


def preserved_data(connection: sqlite3.Connection) -> dict:
    """Keep every pre-existing field for comparison, including original shelf metadata."""
    result = {}
    for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'schema_migrations'"):
        columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')
                   if not (table == "shelves" and row[1] == "revert_location_id")]
        selection = ', '.join('"' + column.replace('"', '""') + '"' for column in columns)
        result[table] = [tuple(row) for row in connection.execute(f'SELECT {selection} FROM "{table}" ORDER BY rowid')]
    return result


def migrate(connection: sqlite3.Connection) -> dict:
    if connection.in_transaction:
        raise RuntimeError("Migration must own its transaction.")
    connection.execute("PRAGMA foreign_keys = ON")
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        before_checks = checks(connection)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(shelves)")}
        if connection.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (VERSION,)).fetchone():
            if "revert_location_id" not in columns:
                raise RuntimeError("Version 5 is recorded but the shelf direction column is missing.")
            return {"status": "already_applied", "converted_shelf_ids": [], **before_checks}
        if not connection.execute("SELECT 1 FROM schema_migrations WHERE version = 4").fetchone():
            raise RuntimeError("Run the backed-up warehouse cleanup migration to version 4 first.")
        before = preserved_data(connection)
        selected = add_direction_setting(connection)
        if preserved_data(connection) != before:
            raise RuntimeError("The direction conversion changed existing warehouse data; rolling back.")
        expected = set(selected)
        actual = {row[0] for row in connection.execute("SELECT shelf_id FROM shelves WHERE revert_location_id = 1")}
        if actual != expected:
            raise RuntimeError("Unexpected shelf direction flags; rolling back.")
        return {"status": "applied", "converted_shelf_ids": selected, **checks(connection)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/warehouse_locations.db"))
    parser.add_argument("--apply", action="store_true", help="Close the app first. Back up and apply once.")
    args = parser.parse_args()
    database = args.database.resolve()
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        report = {"database": str(database), "target_shelf_ids": targets(connection), **checks(connection)}
    if args.apply:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = database.with_name(f"{database.stem}.before-shelf-direction-{stamp}.db")
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(backup)) as destination:
                source.backup(destination)
                checks(destination)
        with closing(sqlite3.connect(database.as_uri() + "?mode=rw", uri=True)) as connection:
            report.update(migrate(connection))
        report["backup"] = str(backup)
        report_path = backup.with_suffix(".json")
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

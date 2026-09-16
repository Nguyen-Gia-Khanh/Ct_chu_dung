"""SQLite storage for products, shelves, rows, slots, and placements."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .common import clean_location_segment, make_slot_name


class LayoutConflictError(ValueError):
    pass


def validate_stock_quantity(quantity: int | None) -> None:
    if type(quantity) is not int or not 0 <= quantity <= 9_223_372_036_854_775_807:
        raise ValueError("Stock quantity must be a whole number from 0 to 9,223,372,036,854,775,807.")


@dataclass(frozen=True)
class Placement:
    slot_name: str
    stock_qty: int | None
    assigned_at: str | None


@dataclass(frozen=True)
class ProductLocation:
    shelf_id: int
    row_number: int
    slot_number: int
    placement: Placement


class WarehouseDatabase:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with closing(self.connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS products (
                    product_id   TEXT PRIMARY KEY,
                    product_name TEXT NOT NULL,
                    imported_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS shelves (
                    shelf_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                    floor       TEXT NOT NULL COLLATE NOCASE,
                    side        TEXT NOT NULL DEFAULT '1' COLLATE NOCASE CHECK (length(trim(side)) > 0),
                    shelf_code  TEXT NOT NULL COLLATE NOCASE,
                    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (floor, side, shelf_code)
                );

                CREATE TABLE IF NOT EXISTS shelf_rows (
                    row_id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    shelf_id          INTEGER NOT NULL REFERENCES shelves(shelf_id) ON DELETE CASCADE,
                    row_number        INTEGER NOT NULL,
                    slot_count        INTEGER NOT NULL CHECK (slot_count >= 0),
                    UNIQUE (shelf_id, row_number)
                );

                CREATE TABLE IF NOT EXISTS slots (
                    slot_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    row_id       INTEGER NOT NULL REFERENCES shelf_rows(row_id) ON DELETE CASCADE,
                    slot_number  INTEGER NOT NULL CHECK (slot_number > 0),
                    slot_name    TEXT NOT NULL UNIQUE,
                    UNIQUE (row_id, slot_number)
                );

                CREATE TABLE IF NOT EXISTS placements (
                    product_id  TEXT PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
                    slot_id     INTEGER NOT NULL REFERENCES slots(slot_id) ON DELETE RESTRICT,
                    stock_qty   INTEGER CHECK (stock_qty IS NULL OR (stock_qty >= 0 AND typeof(stock_qty) = 'integer')),
                    assigned_at TEXT,
                    committed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_products_name
                    ON products(product_name COLLATE NOCASE);
                CREATE INDEX IF NOT EXISTS idx_placements_slot
                    ON placements(slot_id);
                """
            )
            # Older versions called the commit time "assigned_at". Preserve it
            # under its correct name; the actual assignment time is unknown.
            # Rebuilding referenced layout tables needs foreign keys disabled
            # before BEGIN. Check all references before the transaction commits.
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("BEGIN IMMEDIATE")
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(placements)")}
            if "committed_at" not in columns:
                connection.execute("ALTER TABLE placements RENAME COLUMN assigned_at TO committed_at")
                columns.remove("assigned_at")
            if "assigned_at" not in columns:
                connection.execute("ALTER TABLE placements ADD COLUMN assigned_at TEXT")
            if "stock_qty" not in columns:
                connection.execute(
                    "ALTER TABLE placements ADD COLUMN stock_qty INTEGER "
                    "CHECK (stock_qty IS NULL OR (stock_qty >= 0 AND typeof(stock_qty) = 'integer'))"
                )
            self._migrate_continuous_cells(connection)
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise sqlite3.IntegrityError("Database upgrade found invalid location references; changes were rolled back.")

    @staticmethod
    def _rename_slots(connection: sqlite3.Connection, names: dict[int, str]) -> None:
        if not names:
            return
        if len(set(names.values())) != len(names):
            raise LayoutConflictError("These shelf codes produce duplicate location IDs. Use distinct shelf codes.")
        # Temporary names avoid UNIQUE collisions between old and new labels.
        prefix = f"__location_update_{uuid4().hex}_"
        connection.executemany(
            "UPDATE slots SET slot_name = ? WHERE slot_id = ?",
            ((f"{prefix}{slot_id}", slot_id) for slot_id in names),
        )
        try:
            connection.executemany(
                "UPDATE slots SET slot_name = ? WHERE slot_id = ?",
                ((name, slot_id) for slot_id, name in names.items()),
            )
        except sqlite3.IntegrityError as error:
            raise LayoutConflictError("A location ID already belongs to another shelf. Use a distinct side or shelf code.") from error

    @staticmethod
    def _migrate_continuous_cells(connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(shelf_rows)")}
        if "left_slot_count" not in columns:
            return

        sequences = dict(connection.execute(
            "SELECT name, seq FROM sqlite_sequence WHERE name IN ('shelf_rows', 'slots')"
        ).fetchall())
        old_slots = connection.execute(
            """
            SELECT slots.*, shelf_rows.row_number, shelf_rows.left_slot_count,
                   shelves.floor, shelves.side AS shelf_side, shelves.shelf_code
            FROM slots
            JOIN shelf_rows ON shelf_rows.row_id = slots.row_id
            JOIN shelves ON shelves.shelf_id = shelf_rows.shelf_id
            """
        ).fetchall()
        # Keep row_id and slot_id unchanged so placements do not move. Build
        # replacement tables first; never rename the old referenced tables.
        connection.execute("""
            CREATE TABLE shelf_rows_new (
                row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                shelf_id INTEGER NOT NULL REFERENCES shelves(shelf_id) ON DELETE CASCADE,
                row_number INTEGER NOT NULL,
                slot_count INTEGER NOT NULL CHECK (slot_count >= 0),
                UNIQUE (shelf_id, row_number)
            )
        """)
        connection.execute("""
            INSERT INTO shelf_rows_new (row_id, shelf_id, row_number, slot_count)
            SELECT row_id, shelf_id, row_number, left_slot_count + right_slot_count
            FROM shelf_rows
        """)
        connection.execute("""
            CREATE TABLE slots_new (
                slot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                row_id INTEGER NOT NULL REFERENCES shelf_rows(row_id) ON DELETE CASCADE,
                slot_number INTEGER NOT NULL CHECK (slot_number > 0),
                slot_name TEXT NOT NULL UNIQUE,
                UNIQUE (row_id, slot_number)
            )
        """)
        for row in old_slots:
            cell = row["slot_number"] + (row["left_slot_count"] if row["side"] == "R" else 0)
            connection.execute(
                "INSERT INTO slots_new (slot_id, row_id, slot_number, slot_name) VALUES (?, ?, ?, ?)",
                (row["slot_id"], row["row_id"], cell,
                 make_slot_name(row["floor"], row["shelf_code"], row["row_number"], cell, side=row["shelf_side"])),
            )
        connection.execute("DROP TABLE slots")
        connection.execute("DROP TABLE shelf_rows")
        connection.execute("ALTER TABLE shelf_rows_new RENAME TO shelf_rows")
        connection.execute("ALTER TABLE slots_new RENAME TO slots")
        # Preserve AUTOINCREMENT history, including IDs of previously removed
        # top rows/cells, so those old IDs are never reused after the upgrade.
        for table, sequence in sequences.items():
            cursor = connection.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = ?", (sequence, table))
            if cursor.rowcount == 0:
                connection.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (table, sequence))

    def import_products(self, records: dict[str, str]) -> tuple[int, int]:
        if not records:
            return 0, 0

        with closing(self.connect()) as connection, connection:
            existing = {
                row["product_id"]
                for row in connection.execute(
                    f"SELECT product_id FROM products WHERE product_id IN ({','.join('?' for _ in records)})",
                    tuple(records),
                )
            }
            connection.executemany(
                """
                INSERT INTO products (product_id, product_name)
                VALUES (?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    product_name = excluded.product_name,
                    imported_at = CURRENT_TIMESTAMP
                """,
                records.items(),
            )
        return len(records) - len(existing), len(existing)

    def get_products(self) -> list[tuple[str, str]]:
        with closing(self.connect()) as connection, connection:
            rows = connection.execute(
                "SELECT product_id, product_name FROM products ORDER BY product_id COLLATE NOCASE"
            ).fetchall()
        return [(row["product_id"], row["product_name"]) for row in rows]

    def list_shelves(self) -> list[tuple[int, str, str, str]]:
        with closing(self.connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT shelf_id, floor, side, shelf_code
                FROM shelves
                ORDER BY floor COLLATE NOCASE, side COLLATE NOCASE, shelf_code COLLATE NOCASE
                """
            ).fetchall()
        return [(row["shelf_id"], row["floor"], row["side"], row["shelf_code"]) for row in rows]

    def get_shelf_id(self, floor: str, shelf_code: str, *, side: str = "1") -> int | None:
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT shelf_id FROM shelves WHERE floor = ? AND side = ? AND shelf_code = ?",
                (clean_location_segment(floor), clean_location_segment(side), clean_location_segment(shelf_code)),
            ).fetchone()
        return row["shelf_id"] if row is not None else None

    def get_shelf(self, shelf_id: int) -> tuple[str, str, str, list[int]]:
        with closing(self.connect()) as connection, connection:
            shelf = connection.execute(
                "SELECT floor, side, shelf_code FROM shelves WHERE shelf_id = ?", (shelf_id,)
            ).fetchone()
            if shelf is None:
                raise KeyError(f"Shelf {shelf_id} does not exist.")
            rows = connection.execute(
                """
                SELECT slot_count
                FROM shelf_rows
                WHERE shelf_id = ?
                ORDER BY row_number
                """,
                (shelf_id,),
            ).fetchall()
        return (
            shelf["floor"],
            shelf["side"],
            shelf["shelf_code"],
            [row["slot_count"] for row in rows],
        )

    def get_placements(self) -> dict[str, str]:
        return {product_id: placement.slot_name for product_id, placement in self.get_placement_details().items()}

    def get_placement_details(self) -> dict[str, Placement]:
        with closing(self.connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT placements.product_id, slots.slot_name,
                       placements.stock_qty, placements.assigned_at
                FROM placements
                JOIN slots ON slots.slot_id = placements.slot_id
                """
            ).fetchall()
        return {
            row["product_id"]: Placement(row["slot_name"], row["stock_qty"], row["assigned_at"])
            for row in rows
        }

    def get_product_location(self, product_id: str) -> ProductLocation | None:
        """Locate a saved assignment through table relationships, not its ID format."""
        with closing(self.connect()) as connection:
            row = connection.execute(
                """
                SELECT shelf_rows.shelf_id, shelf_rows.row_number, slots.slot_number,
                       slots.slot_name, placements.stock_qty, placements.assigned_at
                FROM placements
                JOIN slots ON slots.slot_id = placements.slot_id
                JOIN shelf_rows ON shelf_rows.row_id = slots.row_id
                WHERE placements.product_id = ?
                """,
                (product_id,),
            ).fetchone()
        if row is None:
            return None
        return ProductLocation(
            row["shelf_id"], row["row_number"], row["slot_number"],
            Placement(row["slot_name"], row["stock_qty"], row["assigned_at"]),
        )

    def get_shelf_contents(self, shelf_id: int) -> list[tuple[str, str, Placement]]:
        """Return only committed products on one shelf for the read-only viewer."""
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT products.product_id, products.product_name, slots.slot_name,
                       placements.stock_qty, placements.assigned_at
                FROM placements
                JOIN products ON products.product_id = placements.product_id
                JOIN slots ON slots.slot_id = placements.slot_id
                JOIN shelf_rows ON shelf_rows.row_id = slots.row_id
                WHERE shelf_rows.shelf_id = ?
                ORDER BY shelf_rows.row_number, slots.slot_number,
                         products.product_id COLLATE NOCASE
                """,
                (shelf_id,),
            ).fetchall()
        return [
            (row["product_id"], row["product_name"],
             Placement(row["slot_name"], row["stock_qty"], row["assigned_at"]))
            for row in rows
        ]

    @staticmethod
    def _sync_layout(
        connection: sqlite3.Connection,
        shelf_id: int,
        floor: str,
        shelf_code: str,
        layout: list[int],
        *, side: str = "1",
    ) -> None:
        """Add/remove top rows and cells without rebuilding surviving slot IDs."""
        desired = {
            (row_number, cell)
            for row_number, count in enumerate(layout, start=1)
            for cell in range(1, count + 1)
        }
        existing_slots = {
            (row["row_number"], row["slot_number"]): row
            for row in connection.execute(
                """
                SELECT slots.*, shelf_rows.row_number
                FROM slots
                JOIN shelf_rows ON shelf_rows.row_id = slots.row_id
                WHERE shelf_rows.shelf_id = ?
                """,
                (shelf_id,),
            )
        }
        removed = [row for key, row in existing_slots.items() if key not in desired]
        for row in removed:
            if connection.execute(
                "SELECT 1 FROM placements WHERE slot_id = ? LIMIT 1", (row["slot_id"],)
            ).fetchone():
                raise LayoutConflictError(
                    f'{row["slot_name"]} still contains committed products. '
                    "Return or move those products before removing its row or cell."
                )
        connection.executemany(
            "DELETE FROM slots WHERE slot_id = ?",
            ((row["slot_id"],) for row in removed),
        )
        WarehouseDatabase._rename_slots(connection, {
            row["slot_id"]: make_slot_name(floor, shelf_code, row_number, cell, side=side)
            for (row_number, cell), row in existing_slots.items()
            if (row_number, cell) in desired
            and row["slot_name"] != make_slot_name(floor, shelf_code, row_number, cell, side=side)
        })

        existing_rows = {
            row["row_number"]: row["row_id"]
            for row in connection.execute(
                "SELECT row_id, row_number FROM shelf_rows WHERE shelf_id = ?", (shelf_id,)
            )
        }
        # Ascending storage order means new rows extend the top of the shelf.
        for row_number, count in enumerate(layout, start=1):
            row_id = existing_rows.get(row_number)
            if row_id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO shelf_rows (shelf_id, row_number, slot_count)
                    VALUES (?, ?, ?)
                    """,
                    (shelf_id, row_number, count),
                )
                row_id = cursor.lastrowid
            else:
                connection.execute(
                    """
                    UPDATE shelf_rows SET slot_count = ?
                    WHERE row_id = ?
                    """,
                    (count, row_id),
                )
            connection.executemany(
                "INSERT INTO slots (row_id, slot_number, slot_name) VALUES (?, ?, ?)",
                (
                    (row_id, cell, make_slot_name(floor, shelf_code, row_number, cell, side=side))
                    for cell in range(1, count + 1)
                    if (row_number, cell) not in existing_slots
                ),
            )
        connection.execute(
            "DELETE FROM shelf_rows WHERE shelf_id = ? AND row_number > ?",
            (shelf_id, len(layout)),
        )

    def commit_shelf(
        self,
        floor: str,
        shelf_code: str,
        layout: list[int],
        staged_assignments: dict[str, Placement],
        pending_unassignments: set[str],
        *, side: str = "1", shelf_id: int | None = None,
    ) -> int:
        floor = clean_location_segment(floor)
        shelf_code = clean_location_segment(shelf_code)
        side = clean_location_segment(side)
        if not floor or not shelf_code or not side:
            raise ValueError("Floor, side, and shelf code are required.")
        for placement in staged_assignments.values():
            validate_stock_quantity(placement.stock_qty)
            if not placement.assigned_at or datetime.fromisoformat(placement.assigned_at).utcoffset() is None:
                raise ValueError("Each assignment must include the time it was added, with a timezone.")

        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            shelf = connection.execute(
                """
                SELECT shelf_id FROM shelves
                WHERE floor = ? COLLATE NOCASE AND side = ? COLLATE NOCASE AND shelf_code = ? COLLATE NOCASE
                """,
                (floor, side, shelf_code),
            ).fetchone()
            if shelf_id is not None:
                if shelf is not None and shelf["shelf_id"] != shelf_id:
                    raise LayoutConflictError("That floor, side, and shelf code already identify another shelf.")
                cursor = connection.execute(
                    "UPDATE shelves SET floor = ?, side = ?, shelf_code = ?, updated_at = CURRENT_TIMESTAMP WHERE shelf_id = ?",
                    (floor, side, shelf_code, shelf_id),
                )
                if cursor.rowcount != 1:
                    raise KeyError(f"Shelf {shelf_id} does not exist.")
            elif shelf is None:
                cursor = connection.execute(
                    "INSERT INTO shelves (floor, side, shelf_code) VALUES (?, ?, ?)", (floor, side, shelf_code)
                )
                shelf_id = int(cursor.lastrowid)
            else:
                shelf_id = int(shelf["shelf_id"])
                connection.execute(
                    "UPDATE shelves SET updated_at = CURRENT_TIMESTAMP WHERE shelf_id = ?",
                    (shelf_id,),
                )

            # Explicit removals/moves happen in this same transaction, so a product
            # can be moved off a top row and that row removed in one commit.
            connection.executemany(
                "DELETE FROM placements WHERE product_id = ?",
                ((product_id,) for product_id in pending_unassignments | set(staged_assignments)),
            )
            self._sync_layout(connection, shelf_id, floor, shelf_code, layout, side=side)
            slot_ids = {
                row["slot_name"]: row["slot_id"]
                for row in connection.execute(
                    """
                    SELECT slots.slot_id, slots.slot_name
                    FROM slots
                    JOIN shelf_rows ON shelf_rows.row_id = slots.row_id
                    WHERE shelf_rows.shelf_id = ?
                    """,
                    (shelf_id,),
                )
            }
            unknown_slots = sorted({placement.slot_name for placement in staged_assignments.values()} - set(slot_ids))
            if unknown_slots:
                raise ValueError(f"Unknown slot in staged assignments: {unknown_slots[0]}")

            connection.executemany(
                "INSERT INTO placements (product_id, slot_id, stock_qty, assigned_at) VALUES (?, ?, ?, ?)",
                (
                    (product_id, slot_ids[placement.slot_name], placement.stock_qty, placement.assigned_at)
                    for product_id, placement in staged_assignments.items()
                ),
            )
        return shelf_id

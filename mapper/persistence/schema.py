from __future__ import annotations

import sqlite3
from contextlib import closing
from uuid import uuid4

from mapper.core.common import make_slot_name
from .models import LayoutConflictError

class SchemaOperations:
    def initialize(self) -> None:
        with closing(self.connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS products (
                    product_id   TEXT PRIMARY KEY,
                    product_name TEXT NOT NULL,
                    shortened_name TEXT NOT NULL DEFAULT '',
                    imported_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS catalog_products (
                    product_id     TEXT PRIMARY KEY,
                    product_name   TEXT NOT NULL,
                    shortened_name TEXT NOT NULL DEFAULT '',
                    imported_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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

                CREATE TABLE IF NOT EXISTS on_hand_queue (
                    product_id TEXT PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
                    stock_qty  INTEGER CHECK (
                        stock_qty IS NULL OR
                        (stock_qty >= 0 AND typeof(stock_qty) = 'integer')
                    ),
                    queued_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS returned_queue_products (
                    product_id  TEXT PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
                    stock_qty   INTEGER CHECK (
                        stock_qty IS NULL OR
                        (stock_qty >= 0 AND typeof(stock_qty) = 'integer')
                    ),
                    returned_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS queue_origins (
                    product_id TEXT PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
                    snapshot TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS stock_modifications (
                    product_id TEXT PRIMARY KEY,
                    modified_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS exception_placements (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id   TEXT NOT NULL,
                    slot_id      INTEGER NOT NULL REFERENCES slots(slot_id) ON DELETE RESTRICT,
                    stock_qty    INTEGER CHECK (stock_qty IS NULL OR (stock_qty >= 0 AND typeof(stock_qty) = 'integer')),
                    assigned_at  TEXT,
                    committed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (product_id, slot_id)
                );

                CREATE TABLE IF NOT EXISTS wait_to_update_csv (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id   TEXT NOT NULL,
                    product_name TEXT NOT NULL DEFAULT 'Exc - added later',
                    slot_id      INTEGER REFERENCES slots(slot_id) ON DELETE SET NULL,
                    slot_name    TEXT NOT NULL,
                    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    csv_updated  INTEGER NOT NULL DEFAULT 0 CHECK (csv_updated IN (0, 1)),
                    catalog_updated INTEGER NOT NULL DEFAULT 0 CHECK (catalog_updated IN (0, 1)),
                    UNIQUE (product_id, slot_name)
                );

                CREATE INDEX IF NOT EXISTS idx_products_name
                    ON products(product_name COLLATE NOCASE);
                CREATE INDEX IF NOT EXISTS idx_catalog_products_name
                    ON catalog_products(product_name COLLATE NOCASE);
                CREATE INDEX IF NOT EXISTS idx_placements_slot
                    ON placements(slot_id);
                CREATE INDEX IF NOT EXISTS idx_exception_placements_product
                    ON exception_placements(product_id);
                CREATE INDEX IF NOT EXISTS idx_exception_placements_slot
                    ON exception_placements(slot_id);
                CREATE INDEX IF NOT EXISTS idx_wait_csv_product
                    ON wait_to_update_csv(product_id);
                CREATE INDEX IF NOT EXISTS idx_on_hand_queued_at
                    ON on_hand_queue(queued_at);
                CREATE INDEX IF NOT EXISTS idx_returned_queue_returned_at
                    ON returned_queue_products(returned_at);
                """
            )
            product_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(products)")
            }
            if "shortened_name" not in product_columns:
                connection.execute(
                    "ALTER TABLE products ADD COLUMN shortened_name TEXT NOT NULL DEFAULT ''"
                )
            # Older versions called the commit time "assigned_at". Preserve it
            # under its correct name; the actual assignment time is unknown.
            # Rebuilding referenced layout tables needs foreign keys disabled
            # before BEGIN. Check all references before the transaction commits.
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("BEGIN IMMEDIATE")
            # Generated aliases cover existing rows and every write path without rekeying IDs.
            for table in ("products", "catalog_products"):
                columns = {
                    row["name"]
                    for row in connection.execute(f"PRAGMA table_xinfo({table})")
                }
                if "product_id_search" not in columns:
                    connection.execute(
                        f"ALTER TABLE {table} ADD COLUMN product_id_search TEXT "
                        "GENERATED ALWAYS AS (replace(product_id, '-', '')) VIRTUAL"
                    )
            staging_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(wait_to_update_csv)")
            }
            if "csv_updated" not in staging_columns:
                connection.execute(
                    "ALTER TABLE wait_to_update_csv ADD COLUMN csv_updated INTEGER NOT NULL DEFAULT 0"
                )
            if "catalog_updated" not in staging_columns:
                connection.execute(
                    "ALTER TABLE wait_to_update_csv ADD COLUMN catalog_updated INTEGER NOT NULL DEFAULT 0"
                )
                # Historical placeholder catalog rows were created automatically;
                # only a real existing catalog name counts as registered.
                connection.execute(
                    """
                    UPDATE wait_to_update_csv SET catalog_updated = 1
                    WHERE EXISTS (
                        SELECT 1 FROM catalog_products AS catalog
                        WHERE catalog.product_id = wait_to_update_csv.product_id
                          AND catalog.product_name <> 'Exc - added later'
                    )
                    """
                )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(placements)")
            }
            if "committed_at" not in columns:
                connection.execute(
                    "ALTER TABLE placements RENAME COLUMN assigned_at TO committed_at"
                )
                columns.remove("assigned_at")
            if "assigned_at" not in columns:
                connection.execute("ALTER TABLE placements ADD COLUMN assigned_at TEXT")
            if "stock_qty" not in columns:
                connection.execute(
                    "ALTER TABLE placements ADD COLUMN stock_qty INTEGER "
                    "CHECK (stock_qty IS NULL OR (stock_qty >= 0 AND typeof(stock_qty) = 'integer'))"
                )
            connection.execute(
                "DELETE FROM on_hand_queue WHERE product_id IN (SELECT product_id FROM placements)"
            )
            connection.execute(
                "DELETE FROM returned_queue_products WHERE product_id IN (SELECT product_id FROM placements)"
            )
            self._migrate_continuous_cells(connection)
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise sqlite3.IntegrityError(
                    "Database upgrade found invalid location references; changes were rolled back."
                )

    @staticmethod
    def _rename_slots(connection: sqlite3.Connection, names: dict[int, str]) -> None:
        if not names:
            return
        if len(set(names.values())) != len(names):
            raise LayoutConflictError(
                "These shelf codes produce duplicate location IDs. Use distinct shelf codes."
            )
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
            raise LayoutConflictError(
                "A location ID already belongs to another shelf. Use a distinct side or shelf code."
            ) from error

    @staticmethod
    def _migrate_continuous_cells(connection: sqlite3.Connection) -> None:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(shelf_rows)")
        }
        if "left_slot_count" not in columns:
            return

        sequences = dict(
            connection.execute(
                "SELECT name, seq FROM sqlite_sequence WHERE name IN ('shelf_rows', 'slots')"
            ).fetchall()
        )
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
            cell = row["slot_number"] + (
                row["left_slot_count"] if row["side"] == "R" else 0
            )
            connection.execute(
                "INSERT INTO slots_new (slot_id, row_id, slot_number, slot_name) VALUES (?, ?, ?, ?)",
                (
                    row["slot_id"],
                    row["row_id"],
                    cell,
                    make_slot_name(
                        row["floor"],
                        row["shelf_code"],
                        row["row_number"],
                        cell,
                        side=row["shelf_side"],
                    ),
                ),
            )
        connection.execute("DROP TABLE slots")
        connection.execute("DROP TABLE shelf_rows")
        connection.execute("ALTER TABLE shelf_rows_new RENAME TO shelf_rows")
        connection.execute("ALTER TABLE slots_new RENAME TO slots")
        # Preserve AUTOINCREMENT history, including IDs of previously removed
        # top rows/cells, so those old IDs are never reused after the upgrade.
        for table, sequence in sequences.items():
            cursor = connection.execute(
                "UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = ?",
                (sequence, table),
            )
            if cursor.rowcount == 0:
                connection.execute(
                    "INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)",
                    (table, sequence),
                )

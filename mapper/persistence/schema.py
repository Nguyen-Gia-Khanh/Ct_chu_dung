"""Current schema. Existing data upgrades are explicit, backed-up migrations."""
from __future__ import annotations

from contextlib import closing
import sqlite3
from uuid import uuid4
from mapper.core.common import UTC_DEFAULT, EXCEL_ERRORS
from .models import LayoutConflictError

SCHEMA_VERSION = 4
SKU_CHECK = "CHECK (length(product_id) > 0 AND product_id = upper(trim(product_id)) AND instr(product_id, '-') = 0 AND instr(product_id, ' ') = 0)"
NAME_ERRORS = ', '.join("'" + value + "'" for value in sorted(EXCEL_ERRORS))
SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS catalog_products (
    product_id TEXT NOT NULL PRIMARY KEY {SKU_CHECK},
    full_name TEXT CHECK (full_name IS NULL OR upper(trim(full_name)) NOT IN ({NAME_ERRORS})),
    brand_name TEXT CHECK (brand_name IS NULL OR upper(trim(brand_name)) NOT IN ({NAME_ERRORS})),
    imported_at TEXT NOT NULL DEFAULT {UTC_DEFAULT}
);
CREATE TABLE IF NOT EXISTS hot_sellers (
    product_id TEXT NOT NULL PRIMARY KEY REFERENCES catalog_products(product_id) ON DELETE CASCADE {SKU_CHECK},
    imported_at TEXT NOT NULL DEFAULT {UTC_DEFAULT}
);
CREATE TABLE IF NOT EXISTS shelves (
    shelf_id INTEGER PRIMARY KEY AUTOINCREMENT,
    floor TEXT NOT NULL COLLATE NOCASE,
    side TEXT NOT NULL DEFAULT '1' COLLATE NOCASE CHECK (length(trim(side)) > 0),
    shelf_code TEXT NOT NULL COLLATE NOCASE,
    created_at TEXT NOT NULL DEFAULT {UTC_DEFAULT},
    updated_at TEXT NOT NULL DEFAULT {UTC_DEFAULT},
    row_count INTEGER NOT NULL DEFAULT 0 CHECK (row_count >= 0),
    UNIQUE (floor, side, shelf_code)
);
CREATE TABLE IF NOT EXISTS slots (
    slot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    shelf_id INTEGER NOT NULL REFERENCES shelves(shelf_id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL CHECK (row_number > 0),
    slot_number INTEGER NOT NULL CHECK (slot_number > 0),
    slot_name TEXT NOT NULL UNIQUE,
    UNIQUE (shelf_id, row_number, slot_number)
);
CREATE TABLE IF NOT EXISTS placements (
    product_id TEXT NOT NULL PRIMARY KEY REFERENCES catalog_products(product_id) ON DELETE CASCADE {SKU_CHECK},
    slot_id INTEGER NOT NULL REFERENCES slots(slot_id) ON DELETE RESTRICT,
    stock_qty INTEGER NOT NULL DEFAULT 999 CHECK (stock_qty >= 0 AND typeof(stock_qty) = 'integer'),
    assigned_at TEXT,
    committed_at TEXT NOT NULL DEFAULT {UTC_DEFAULT}
);
CREATE TABLE IF NOT EXISTS exception_placements (
    product_id TEXT NOT NULL REFERENCES catalog_products(product_id) ON DELETE CASCADE {SKU_CHECK},
    slot_id INTEGER NOT NULL REFERENCES slots(slot_id) ON DELETE RESTRICT,
    assigned_at TEXT,
    PRIMARY KEY (product_id, slot_id),
    FOREIGN KEY (product_id) REFERENCES placements(product_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE IF NOT EXISTS on_hand_queue (
    product_id TEXT NOT NULL PRIMARY KEY REFERENCES catalog_products(product_id) ON DELETE CASCADE {SKU_CHECK},
    stock_qty INTEGER CHECK (stock_qty IS NULL OR (stock_qty >= 0 AND typeof(stock_qty) = 'integer')),
    queued_at TEXT NOT NULL DEFAULT {UTC_DEFAULT}
);
CREATE TABLE IF NOT EXISTS stock_modifications (
    product_id TEXT NOT NULL PRIMARY KEY REFERENCES catalog_products(product_id) ON DELETE CASCADE {SKU_CHECK},
    modified_at TEXT NOT NULL DEFAULT {UTC_DEFAULT}
);
CREATE TABLE IF NOT EXISTS wait_to_update_csv (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL REFERENCES catalog_products(product_id) ON DELETE CASCADE {SKU_CHECK},
    slot_id INTEGER REFERENCES slots(slot_id) ON DELETE SET NULL,
    slot_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT {UTC_DEFAULT},
    csv_updated INTEGER NOT NULL DEFAULT 0 CHECK (csv_updated IN (0, 1)),
    catalog_updated INTEGER NOT NULL DEFAULT 0 CHECK (catalog_updated IN (0, 1)),
    UNIQUE (product_id, slot_name)
);
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT {UTC_DEFAULT}
);
CREATE INDEX IF NOT EXISTS idx_catalog_full_name ON catalog_products(full_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_catalog_brand_name ON catalog_products(brand_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_placements_slot ON placements(slot_id);
CREATE INDEX IF NOT EXISTS idx_exception_placements_slot ON exception_placements(slot_id);
CREATE INDEX IF NOT EXISTS idx_wait_csv_product ON wait_to_update_csv(product_id);
CREATE INDEX IF NOT EXISTS idx_on_hand_queued_at ON on_hand_queue(queued_at);
"""


def create_schema(connection: sqlite3.Connection) -> None:
    # execute, not executescript: callers may already own the migration transaction.
    for statement in SCHEMA_SQL.split(';'):
        if statement.strip():
            connection.execute(statement)


class SchemaOperations:
    def initialize(self) -> None:
        with closing(self.connect()) as connection, connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            catalog_columns = {row[1] for row in connection.execute('PRAGMA table_info(catalog_products)')}
            if tables & {'products', 'shelf_rows', 'queue_origins'} or (catalog_columns and 'full_name' not in catalog_columns):
                raise RuntimeError(
                    'This database needs the backed-up warehouse cleanup migration. '
                    'Run python -m migrations.warehouse_cleanup --help using the repo .venv.'
                )
            create_schema(connection)
            connection.execute('INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)',(SCHEMA_VERSION,))

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

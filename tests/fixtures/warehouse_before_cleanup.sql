-- Legacy schema only: exercises the migration without operational data.
CREATE TABLE catalog_products (
                    product_id     TEXT PRIMARY KEY,
                    product_name   TEXT NOT NULL,
                    shortened_name TEXT NOT NULL DEFAULT '',
                    imported_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                , product_id_search TEXT GENERATED ALWAYS AS (replace(product_id, '-', '')) VIRTUAL);

CREATE TABLE exception_placements (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id   TEXT NOT NULL,
                    slot_id      INTEGER NOT NULL REFERENCES slots(slot_id) ON DELETE RESTRICT,
                    stock_qty    INTEGER CHECK (stock_qty IS NULL OR (stock_qty >= 0 AND typeof(stock_qty) = 'integer')),
                    assigned_at  TEXT,
                    committed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (product_id, slot_id)
                );

CREATE TABLE on_hand_queue (
                    product_id TEXT PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
                    stock_qty  INTEGER CHECK (
                        stock_qty IS NULL OR
                        (stock_qty >= 0 AND typeof(stock_qty) = 'integer')
                    ),
                    queued_at  TEXT NOT NULL
                );

CREATE TABLE placements (
                    product_id  TEXT PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
                    slot_id     INTEGER NOT NULL REFERENCES slots(slot_id) ON DELETE RESTRICT,
                    stock_qty   INTEGER CHECK (stock_qty IS NULL OR (stock_qty >= 0 AND typeof(stock_qty) = 'integer')),
                    assigned_at TEXT,
                    committed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

CREATE TABLE products (
                    product_id   TEXT PRIMARY KEY,
                    product_name TEXT NOT NULL,
                    shortened_name TEXT NOT NULL DEFAULT '',
                    imported_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                , product_id_search TEXT GENERATED ALWAYS AS (replace(product_id, '-', '')) VIRTUAL);

CREATE TABLE queue_origins (
                    product_id TEXT PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
                    snapshot TEXT NOT NULL
                );

CREATE TABLE returned_queue_products (
                    product_id  TEXT PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
                    stock_qty   INTEGER CHECK (
                        stock_qty IS NULL OR
                        (stock_qty >= 0 AND typeof(stock_qty) = 'integer')
                    ),
                    returned_at TEXT NOT NULL
                );

CREATE TABLE shelf_rows (
                    row_id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    shelf_id          INTEGER NOT NULL REFERENCES shelves(shelf_id) ON DELETE CASCADE,
                    row_number        INTEGER NOT NULL,
                    slot_count        INTEGER NOT NULL CHECK (slot_count >= 0),
                    UNIQUE (shelf_id, row_number)
                );

CREATE TABLE shelves (
                    shelf_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                    floor       TEXT NOT NULL COLLATE NOCASE,
                    side        TEXT NOT NULL DEFAULT '1' COLLATE NOCASE CHECK (length(trim(side)) > 0),
                    shelf_code  TEXT NOT NULL COLLATE NOCASE,
                    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (floor, side, shelf_code)
                );

CREATE TABLE slots (
                    slot_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    row_id       INTEGER NOT NULL REFERENCES shelf_rows(row_id) ON DELETE CASCADE,
                    slot_number  INTEGER NOT NULL CHECK (slot_number > 0),
                    slot_name    TEXT NOT NULL UNIQUE,
                    UNIQUE (row_id, slot_number)
                );

CREATE TABLE stock_modifications (
                    product_id TEXT PRIMARY KEY,
                    modified_at TEXT NOT NULL
                );

CREATE TABLE wait_to_update_csv (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id   TEXT NOT NULL,
                    product_name TEXT NOT NULL DEFAULT 'Exc - added later',
                    slot_id      INTEGER REFERENCES slots(slot_id) ON DELETE SET NULL,
                    slot_name    TEXT NOT NULL,
                    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, csv_updated INTEGER NOT NULL DEFAULT 0, catalog_updated INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (product_id, slot_name)
                );

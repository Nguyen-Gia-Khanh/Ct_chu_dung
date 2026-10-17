-- Frozen version-3 schema for isolated migration tests.
CREATE TABLE IF NOT EXISTS catalog_products (
    product_id TEXT NOT NULL PRIMARY KEY CHECK (length(product_id) > 0 AND product_id = upper(trim(product_id)) AND instr(product_id, '-') = 0 AND instr(product_id, ' ') = 0),
    full_name TEXT CHECK (full_name IS NULL OR upper(trim(full_name)) NOT IN ('#CALC!', '#DIV/0!', '#N/A', '#NAME?', '#NULL!', '#NUM!', '#REF!', '#SPILL!', '#VALUE!')),
    brand_name TEXT CHECK (brand_name IS NULL OR upper(trim(brand_name)) NOT IN ('#CALC!', '#DIV/0!', '#N/A', '#NAME?', '#NULL!', '#NUM!', '#REF!', '#SPILL!', '#VALUE!')),
    imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);
CREATE TABLE IF NOT EXISTS hot_sellers (
    product_id TEXT NOT NULL PRIMARY KEY REFERENCES catalog_products(product_id) ON DELETE CASCADE CHECK (length(product_id) > 0 AND product_id = upper(trim(product_id)) AND instr(product_id, '-') = 0 AND instr(product_id, ' ') = 0),
    imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);
CREATE TABLE IF NOT EXISTS shelves (
    shelf_id INTEGER PRIMARY KEY AUTOINCREMENT,
    floor TEXT NOT NULL COLLATE NOCASE,
    side TEXT NOT NULL DEFAULT '1' COLLATE NOCASE CHECK (length(trim(side)) > 0),
    shelf_code TEXT NOT NULL COLLATE NOCASE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    UNIQUE (floor, side, shelf_code)
);
CREATE TABLE IF NOT EXISTS shelf_rows (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    shelf_id INTEGER NOT NULL REFERENCES shelves(shelf_id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,
    slot_count INTEGER NOT NULL CHECK (slot_count >= 0),
    UNIQUE (shelf_id, row_number)
);
CREATE TABLE IF NOT EXISTS slots (
    slot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    row_id INTEGER NOT NULL REFERENCES shelf_rows(row_id) ON DELETE CASCADE,
    slot_number INTEGER NOT NULL CHECK (slot_number > 0),
    slot_name TEXT NOT NULL UNIQUE,
    UNIQUE (row_id, slot_number)
);
CREATE TABLE IF NOT EXISTS placements (
    product_id TEXT NOT NULL PRIMARY KEY REFERENCES catalog_products(product_id) ON DELETE CASCADE CHECK (length(product_id) > 0 AND product_id = upper(trim(product_id)) AND instr(product_id, '-') = 0 AND instr(product_id, ' ') = 0),
    slot_id INTEGER NOT NULL REFERENCES slots(slot_id) ON DELETE RESTRICT,
    stock_qty INTEGER NOT NULL DEFAULT 999 CHECK (stock_qty >= 0 AND typeof(stock_qty) = 'integer'),
    assigned_at TEXT,
    committed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);
CREATE TABLE IF NOT EXISTS exception_placements (
    product_id TEXT NOT NULL REFERENCES catalog_products(product_id) ON DELETE CASCADE CHECK (length(product_id) > 0 AND product_id = upper(trim(product_id)) AND instr(product_id, '-') = 0 AND instr(product_id, ' ') = 0),
    slot_id INTEGER NOT NULL REFERENCES slots(slot_id) ON DELETE RESTRICT,
    assigned_at TEXT,
    PRIMARY KEY (product_id, slot_id),
    FOREIGN KEY (product_id) REFERENCES placements(product_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE IF NOT EXISTS on_hand_queue (
    product_id TEXT NOT NULL PRIMARY KEY REFERENCES catalog_products(product_id) ON DELETE CASCADE CHECK (length(product_id) > 0 AND product_id = upper(trim(product_id)) AND instr(product_id, '-') = 0 AND instr(product_id, ' ') = 0),
    stock_qty INTEGER CHECK (stock_qty IS NULL OR (stock_qty >= 0 AND typeof(stock_qty) = 'integer')),
    queued_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);
CREATE TABLE IF NOT EXISTS queue_origins (
    product_id TEXT NOT NULL PRIMARY KEY REFERENCES catalog_products(product_id) ON DELETE CASCADE CHECK (length(product_id) > 0 AND product_id = upper(trim(product_id)) AND instr(product_id, '-') = 0 AND instr(product_id, ' ') = 0),
    snapshot TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_modifications (
    product_id TEXT NOT NULL PRIMARY KEY REFERENCES catalog_products(product_id) ON DELETE CASCADE CHECK (length(product_id) > 0 AND product_id = upper(trim(product_id)) AND instr(product_id, '-') = 0 AND instr(product_id, ' ') = 0),
    modified_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);
CREATE TABLE IF NOT EXISTS wait_to_update_csv (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL REFERENCES catalog_products(product_id) ON DELETE CASCADE CHECK (length(product_id) > 0 AND product_id = upper(trim(product_id)) AND instr(product_id, '-') = 0 AND instr(product_id, ' ') = 0),
    slot_id INTEGER REFERENCES slots(slot_id) ON DELETE SET NULL,
    slot_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    csv_updated INTEGER NOT NULL DEFAULT 0 CHECK (csv_updated IN (0, 1)),
    catalog_updated INTEGER NOT NULL DEFAULT 0 CHECK (catalog_updated IN (0, 1)),
    UNIQUE (product_id, slot_name)
);
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_catalog_full_name ON catalog_products(full_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_catalog_brand_name ON catalog_products(brand_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_placements_slot ON placements(slot_id);
CREATE INDEX IF NOT EXISTS idx_exception_placements_slot ON exception_placements(slot_id);
CREATE INDEX IF NOT EXISTS idx_wait_csv_product ON wait_to_update_csv(product_id);
CREATE INDEX IF NOT EXISTS idx_on_hand_queued_at ON on_hand_queue(queued_at);

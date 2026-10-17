# Warehouse schema simplification - 2026-10-18

The user approved removing `shelf_rows` and `queue_origins` and committing
directly to `main`. The earlier verified cleanup branch was first merged with
`--no-ff`; this follow-up is committed on `main`. Nothing was pushed, and the
unrelated OCR notebook edit was excluded.

## Result and migration

`migrations/warehouse_cleanup.py` now applies version 4. It upgrades versions
1-3 and the original legacy schema in one transaction, with foreign keys off
before BEGIN, both SQLite checks before commit, and foreign keys restored in
`finally`. Reruns are checked no-ops. The application refuses an older schema
and requires this explicit backed-up migration.

- `shelf_rows` is removed. Each cell directly references its shelf and stores
  its row number. Row cell counts are derived from cells. A shelf keeps
  `row_count`, so zero-cell rows, including trailing empty rows, survive saving
  and reopening without another table.
- `queue_origins` is removed along with origin writes, UI exclusion filters,
  cached origin state, and origin entries in Shift snapshots. Hot-seller
  membership is read directly from `hot_sellers`. The legacy migration still
  reads origin flags to exclude historical catalog-only placeholders before
  dropping the table. Shift undo retains snapshots of actual membership,
  placements, on-hand stock, and CSV staging.
- Shelf lookup, resizing, deletion, labels, inventory readback, and UI callers
  use the simpler layout. Resizing checks both main and extra locations before
  removing an occupied cell. Renaming/resizing retains surviving cell IDs.

The runtime layout/assignment tables are `shelves`, `slots`, and `placements`;
`exception_placements` continues to hold additional product locations.

## Backups and evidence

The app was closed. A backup preceded all source changes:
`data/backups/warehouse_locations-before-cleanup-20261017T190657368078Z.db`.
The CLI made another backup immediately before the live migration:
`data/backups/warehouse_locations-before-cleanup-20261017T191243755203Z.db`.
Its SHA-256 is `d87e90610499e1fc29d95f0687729b16d5bbdd975e1b23d07a1897c72d504e2b`.
Filename timestamps are UTC; the work date above is Vietnam time.

Local, ignored evidence in `data/schema-review/simplification/`:

- `before.json` and `review.json`: pre-change schema/counts and backup.
- `rehearsal.json`: full-data copy, original-backup upgrade comparison,
  preservation assertions, and repeat-run checks.
- `simplification.json`: applied migration, complete before/after definitions
  and counts, backup path, and hash.
- `last-verification.json`: live checks, unchanged-table comparison, preserved
  layouts/IDs, and proof that rerunning kept the database file hash unchanged.

## Tables, columns, and row counts

| Table | Before version 4 | After version 4 | Column changes |
| --- | ---: | ---: | --- |
| `shelves` | 35 | 35 | Add `row_count INTEGER NOT NULL DEFAULT 0 CHECK (row_count >= 0)` |
| `shelf_rows` | 246 | dropped | Remove `row_id`, `shelf_id`, `row_number`, `slot_count` |
| `slots` | 1,807 | 1,807 | Replace `row_id` with `shelf_id` and `row_number` |
| `queue_origins` | 1,304 | dropped | Remove `product_id`, `snapshot` |
| `schema_migrations` | 3 | 4 | No column changes |
| `sqlite_sequence` (internal) | 4 | 3 | Removed retired `shelf_rows` sequence |
| `catalog_products` | 17,427 | 17,427 | Unchanged |
| `hot_sellers` | 10,125 | 10,125 | Unchanged |
| `placements` | 3,014 | 3,014 | Unchanged |
| `exception_placements` | 26 | 26 | Unchanged |
| `on_hand_queue` | 34 | 34 | Unchanged |
| `wait_to_update_csv` | 95 | 95 | Unchanged; all still await CSV export |
| `stock_modifications` | 0 | 0 | Unchanged |

`shelves` now has `shelf_id`, `floor`, `side`, `shelf_code`, `created_at`,
`updated_at`, and `row_count`. `slots` now has `slot_id`, `shelf_id`,
`row_number`, `slot_number`, and `slot_name`. Its shelf foreign key cascades
deletion of an empty shelf; its cell address is unique on
`(shelf_id,row_number,slot_number)`, and `slot_name` remains unique.

Every cell ID/address and all 35 shelf layouts were verified against the
backup. Every row in the seven inventory/catalog tables above is unchanged.
The surviving sequence high-water marks are shelves 38, slots 2,116, and CSV
staging 131; deleted IDs are not reused by a later insert.

## Verification and limits

- 141 focused checks passed: migrations from original/v1/v2/v3 schemas,
  rollback, repeatability, shelf growth/shrink/rename/deletion, empty rows,
  persistent on-hand, shared stock, catalog-only membership, Shift undo,
  CSV staging, scanner lookup, labels, and desktop refresh.
- Full-data rehearsal preserved all 1,807 cells, 35 layouts, and inventory.
  Upgrading the original pre-cleanup backup directly produces identical final
  table rows to the incremental path, excluding migration execution times.
- Full-data desktop startup, catalog search, cell loading, Tab 3 refresh, and
  exception refresh passed using the migrated scratch copy.
- Live `PRAGMA integrity_check` returned **ok**;
  `PRAGMA foreign_key_check` returned **no rows**;
  `PRAGMA foreign_keys` returned **1**. The repeat migration was a checked
  no-op and did not change the database SHA-256.

No unresolved data ambiguity was found. There were no zero-cell rows in the
live data, but the supported feature remains covered. External ERP import was
not run: any reader that joins `shelf_rows` must instead use `slots.shelf_id`
and `slots.row_number`. Older application versions need their
matching database backup. The earlier proposed test-SKU deletions remain pending.

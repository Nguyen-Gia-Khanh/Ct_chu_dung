# Warehouse schema cleanup - 2026-10-18

This is the historical report for migration versions 1-3. The approved work is
now on `main`; [version 4](warehouse-schema-simplification.md) subsequently
removed `shelf_rows` and `queue_origins` and changed the layout columns below.

Implemented on `feature/warehouse-schema-cleanup`, starting from `main` at
`a89f079`. No merge or push. The unrelated OCR notebook edit is excluded.
The operational database is `data/warehouse_locations.db`.

## Backup and application compatibility

The app was closed before the first backup. Initial backup:
`data/backups/warehouse_locations-before-schema-cleanup-20261017T175012Z.db`.
Its SHA-256 remains `2610db7eee5418cd75e824fe932d7e84e005eb59ad29f3c053671f952549671d`.
A second backup was made immediately before the live migration:
`data\backups\warehouse_locations-before-cleanup-20261017T182313354249Z.db` (SHA-256 `2610db7eee5418cd75e824fe932d7e84e005eb59ad29f3c053671f952549671d`).

Version 2 also made a pre-cleanup backup at `C:\Users\Admin\Desktop\fhs\Auto\DA projects\Ct_chu_dung\data\backups\warehouse_locations-before-cleanup-20261017T182847897138Z.db`
(SHA-256 `66ad2eb355dd25c248f45feb9c8e16eea4e57f6f473067b509609a94ce476d1c`).

The application must run from this feature branch with the upgraded database.
The unchanged `main` application cannot read this schema. Keep application and
database versions together; do not open an original backup directly with an app.

## Review before deletion

| Item | Verified purpose and final decision |
| --- | --- |
| `placements` | Primary location and product stock. Kept; its SKU now references the catalog rather than working-product membership. |
| `exception_placements` | Had independent counts and lone placements. Now contains only extra locations, with stock joined from `placements`. |
| `on_hand_queue` | Persistent holding area after removal of the last location. Kept; original returned rows were moved here. |
| `returned_queue_products` | Second holding state after Dequeue. Removed along with its actions, model, reads, writes, UI button, and indexes. |
| `wait_to_update_csv` | Live Tab 6 CSV export and catalog-confirmation work, not abandoned web-upload storage. Kept with all registration flags; names now join the catalog. |
| `queue_origins` | Retained as membership provenance and for the existing UI/Shift readback. Its 303 `was_in_products=false` records identify catalog-only transfers; 1,001 true records are retained too. Version 3 removes false-marked placeholder rows from `hot_sellers` itself. |
| `stock_modifications` | Drives the manual Modify Stock timestamp in Tab 2. Kept with its empty history; assignment/import/moves do not fabricate edits. |
| Catalog Shift+click | Previously supplied 999 after deleting the previous placement/queue rows. Now reads known stock first, preserves zero, and uses 999 only for unknown counts. |

Before migration, 1,257 queue-origin rows had a primary placement.
No origin rows were deleted based on that condition.

## Hot-seller membership correction

There are two independent exception cases: a SKU with multiple saved locations,
and an unregistered SKU awaiting CSV/catalog registration. Neither condition
creates hot-seller membership. A genuine hot seller may also have multiple
locations and retains its existing membership.

The original `products` table overloaded membership with temporary catalog-only
copies. Version 1 renamed all of it to `hot_sellers`, including 303 hidden
placeholders. This was misleading even though the UI excluded them. Comparing
normalized IDs against the original backup proves that version 1 added no new
memberships. All 91 original exception SKUs were already in `products`: 52 were
genuine working products and 39 were catalog-only placeholders.

Version 3 excludes all 303 placeholders from `hot_sellers`, leaving 10,125
genuine members, exactly the original logical membership. It deletes only
membership rows; every catalog name, location, stock count, queue-origin record,
on-hand record, and CSV-staging row remains unchanged. All 95 staged rows still
await CSV export. The earlier approved catalog registration of 126 missing SKUs
is separate and remains in place; it did not mark their CSV work complete.
Runtime catalog/exception assignment no longer inserts hot-seller membership.
Explicit working-product import remains the action that adds membership.

The four "primary placements missing from catalog" were these existing shelf
assignments in the original backup, not new locations created by this work:

| Normalized SKU | Existing name | Existing slot | Stock |
| --- | --- | --- | ---: |
| `33450K12V81` | bộ xi nhan trước trái lead 2019 | `L1-5B1-3` | 999 |
| `50400KTL740` | quai yên rs,wa,ws | `L1-4E4-3` | 999 |
| `51400KZR701` | phuộc trước phải vision 2014 ( bạc ) | `L1-4B2-5` | 999 |
| `64650KWY860ZA` | Bộ ốp sườn trái Wave RS 100 (2008-2009) đỏ tươi-R263* | `L1-6D6-4` | 999 |

"Primary" means the location stored in `placements`, as opposed to an extra
location in `exception_placements`; it does not refer to a separate feature.
`data/schema-review/live/membership-audit.json` records the original membership
comparison, these four rows, and the rehearsal evidence. Version 3 was backed up
at `data/backups/warehouse_locations-before-cleanup-20261017T184802332257Z.db`.
Its applied report is `data/schema-review/live/hot-seller-membership.json`.
The backup SHA-256 is `004053dfc04ed24ceaab78960a76ad53cedfea5d212371c2359af6d411ae0787`.
Version 3 changes `hot_sellers` from 10,428 to 10,125 rows and
`schema_migrations` from 2 to 3 rows. No table or column is dropped in this step.

## Migration script and choices

`migrations/warehouse_cleanup.py` is the single explicit migration and read-only
review command. `migrations/README.md` contains the exact preview/apply commands.
It was rehearsed on a backup copy and rerun there as a checked no-op before the
live file was changed. All schema/data changes publish in one transaction.
Foreign keys are disabled before BEGIN, every SKU/reference is normalized, all
tables are rebuilt, SQLite checks run before commit, and foreign keys are
restored in `finally`. `schema_migrations` records versions 1 (schema/data) and 2 (retired SQLite
sequence cleanup). Final review caught an unused exception ID sequence left by
version 1; version 2 removed it with another automatic backup and checked
transaction. The script now preserves high-water marks only for surviving
AUTOINCREMENT tables. No inventory rows changed in version 2. Both steps are
repeatable, and a final live rerun was a checked no-op with foreign keys enabled.
The version-2 evidence is in `data/schema-review/live/metadata-cleanup.json`.
Version 3 performs the membership correction described above, with another
backup and checked transaction; it also runs during a fresh legacy upgrade.

Approved choices recorded in this session:

- Keep `H06430-K56-N12`; merge `H0643-0K5-6N12` into canonical `H06430K56N12`.
  The actual two rows had identical names and no inventory references. The
  script also preserves both rows' locations if such references are present.
- Register the 126 missing catalog SKUs using existing names; leave unknown
  brand names NULL. This supersedes the initial report-only/no-new-catalog-row
  restriction for these records. No names or Honda metadata were invented.
- Keep test SKUs `1111` and `111111`, both named `test`. Recommend deleting them
  in a separately approved cleanup; neither was deleted here.

Disagreeing known stock values, returned/on-hand overlaps, an unapproved SKU
collision, or unexpected legacy tables/views/triggers abort without partial
changes. Real data had no stock conflicts and no returned/on-hand overlaps.
There were 69 exception rows missing catalog entries but only 68 distinct SKUs.

## Row counts

| Table | Before | After |
| --- | ---: | ---: |
| `catalog_products` | 17,302 | 17,427 |
| `exception_placements` | 95 | 26 |
| `on_hand_queue` | 0 | 34 |
| `placements` | 2,945 | 3,014 |
| `products` to `hot_sellers` | 10,429 | 10,125 |
| `queue_origins` | 1,304 | 1,304 |
| `returned_queue_products` | 34 | dropped |
| `shelf_rows` | 246 | 246 |
| `shelves` | 35 | 35 |
| `slots` | 1,807 | 1,807 |
| `stock_modifications` | 0 | 0 |
| `wait_to_update_csv` | 95 | 95 |
| `schema_migrations` | absent | 3 |
| `sqlite_sequence` (SQLite internal) | 5 | 4 |

69 products without a primary placement were promoted. 68 now have just one
location and no extra row. The remaining 26 extra rows belong to 23 products.
No saved location was lost: 2,945 + 95 = 3,014 + 26 = 3,040 locations.
The 34 returned rows retained their stock and the same timestamp instant as
`on_hand_queue.queued_at`; existing on-hand rows were not overwritten.

The initial supplied CSV status count was inaccurate: the actual before/after
flags are 93 rows `(csv_updated=0,catalog_updated=0)` and 2 rows `(0,1)`.
Thus all 95 rows await CSV export. Every flag was preserved.
The final hot-seller count excludes one merged alias and 303 catalog-only
placeholders. Immediately before version 3 there were 10,428 physical rows;
the logical hot-seller count was already 10,125. No other table's data changed
in version 3, apart from adding its migration version row.

## Columns before and after

| Table | Before | After |
| --- | --- | --- |
| `catalog_products` | `product_id`, `product_name`, `shortened_name`, `imported_at`, `product_id_search` | `product_id`, `full_name`, `brand_name`, `imported_at` |
| `exception_placements` | `id`, `product_id`, `slot_id`, `stock_qty`, `assigned_at`, `committed_at` | `product_id`, `slot_id`, `assigned_at` |
| `on_hand_queue` | `product_id`, `stock_qty`, `queued_at` | `product_id`, `stock_qty`, `queued_at` |
| `placements` | `product_id`, `slot_id`, `stock_qty`, `assigned_at`, `committed_at` | `product_id`, `slot_id`, `stock_qty`, `assigned_at`, `committed_at` |
| `products` | `product_id`, `product_name`, `shortened_name`, `imported_at`, `product_id_search` | `product_id`, `imported_at` |
| `queue_origins` | `product_id`, `snapshot` | `product_id`, `snapshot` |
| `returned_queue_products` | `product_id`, `stock_qty`, `returned_at` | table dropped |
| `shelf_rows` | `row_id`, `shelf_id`, `row_number`, `slot_count` | `row_id`, `shelf_id`, `row_number`, `slot_count` |
| `shelves` | `shelf_id`, `floor`, `side`, `shelf_code`, `created_at`, `updated_at` | `shelf_id`, `floor`, `side`, `shelf_code`, `created_at`, `updated_at` |
| `slots` | `slot_id`, `row_id`, `slot_number`, `slot_name` | `slot_id`, `row_id`, `slot_number`, `slot_name` |
| `stock_modifications` | `product_id`, `modified_at` | `product_id`, `modified_at` |
| `wait_to_update_csv` | `id`, `product_id`, `product_name`, `slot_id`, `slot_name`, `created_at`, `csv_updated`, `catalog_updated` | `id`, `product_id`, `slot_id`, `slot_name`, `created_at`, `csv_updated`, `catalog_updated` |

`schema_migrations` adds `version INTEGER PRIMARY KEY` and `applied_at TEXT`.
SQLite's internal sequence table remains `(name,seq)`; only the obsolete
exception ID sequence was removed. Surviving ID high-water marks were preserved:
`{'wait_to_update_csv': 131, 'shelves': 38, 'shelf_rows': 274, 'slots': 2116}`.

## Constraints and storage

- Canonical SKU: uppercase, trimmed, no hyphens or spaces. All SKU-bearing
  tables enforce the format with CHECK and non-null primary/foreign keys.
  Both lowercase source codes were normalized. The generated search column
  and its special tuple/query plumbing were removed.
- `exception_placements` has composite primary key `(product_id,slot_id)`,
  catalog and slot references, and a deferred reference to its primary
  placement. The latter prevents extras without a stock owner while allowing
  atomic moves/reversal. `placements.stock_qty` is a nonnegative integer,
  NOT NULL, with 999 as the uncounted sentinel. Zero remains a known count.
- Adding a second location inserts an extra row without changing known stock.
  Removing the primary promotes an extra; removing the last location retains
  stock in on-hand. Combining duplicate locations keeps the one shared count
  instead of summing quantities. Shift reversal restores exact location/queue
  records and assignment timestamps from its snapshot.
- Names are stored only in `catalog_products.full_name` and `brand_name`.
  Brand names were checked against `full_catalogue.csv`: zero mismatches and
  zero existing catalog SKUs missing from that CSV. The Honda source hash is
  `1b0c25311a787b1ea36229069f13132ca252d683ad97dc6d3a1159503fdac2b8`. Full names come from the old working-product name where valid;
  Excel errors become NULL. There are 7,585 NULL full names overall (including
  586 hot sellers whose full-name lookup failed) and 126 NULL brand names for
  the approved missing-catalog registrations. Shortened names were removed;
  their original values remain in the backup and missing-code export.
- All non-null timestamps are UTC ISO 8601 with `+00:00`. Previous naive UTC
  values were given UTC offsets, previous Vietnam-offset times were converted
  without changing their instant. Defaults and writers use the same format;
  desktop assignment, stock-change, and staging times display `+07:00`.
- Desktop searches, scanner input, manual entry, CSV imports, Excel/KiotViet
  imports, database methods, and upload objects use `normalize_sku()`.
  `06410-kfl-850` finds `06410KFL850`. Both names remain searchable.
  Scanner and label database connections remain read-only. Every application
  connection enables foreign keys; only the explicit migration turns them off
  during its checked transaction.

## Dropped objects

`returned_queue_products` and its index/model/actions/UI, `products` under its
old name, both `product_id_search` generated columns, both old name columns in
working products, catalog `product_name`/`shortened_name`, staging `product_name`,
and exception `id`/`stock_qty`/`committed_at` were removed or replaced as shown
above. Catalog name indexes now target `full_name` and `brand_name`; the redundant
extra-location product index is covered by its composite primary key.
No shelf, slot, on-hand, origin, staging, or stock-modification history was pruned.

## Missing-code lists and exact evidence

These local operational exports are ignored by Git and include original and
canonical SKUs, names, and slots. They capture missing catalog membership before
the approved registrations; there are no remaining catalog-orphan references.

- [126 original products-table codes](../data/schema-review/live/missing_catalog_products.csv)
  (88 genuine hot sellers and 38 catalog-only placeholders)
- [4 primary-placement codes](../data/schema-review/live/missing_catalog_placements.csv)
- [69 exception rows / 68 codes](../data/schema-review/live/missing_catalog_exception_placements.csv)
- [Original review and schema definitions](../data/schema-review/live/review.json)
- [Applied migration and before/after definitions/counts](../data/schema-review/live/migration.json)
- [Version-2 metadata cleanup](../data/schema-review/live/metadata-cleanup.json)
- [Live no-op and final verification](../data/schema-review/live/last-verification.json)

The four original primary-placement codes were `50400-KTL-740`, `51400-KZR-701`,
`33450-K12-V81`, and `64650-KWY-860ZA`; their names and slots are in the CSV.

## Verification and remaining limits

- The membership correction passed 99 focused migration, assignment/Shift,
  exception/CSV staging, persistent on-hand, and desktop regression checks,
  including catalog-only names after reopening. A full operational-data copy
  was checked before live application. Comparing the fresh pre-version-3 backup
  with the live database confirms every other table's rows are identical.
  Both the rehearsal and live version-3 reruns were checked no-ops; fresh
  database readback reports 10,125 hot sellers, 3,014 placed SKUs, and 34 on-hand.
- 143 active migration, persistence, import, assignment/Shift, desktop, scanner,
  and Playwright-adapter regression checks passed. Explicit rollback tests cover
  collision decisions, missing-catalog approval, disagreeing counts, and queue
  conflicts. Fresh databases, reopening, and exact Shift reversal are covered.
- The full migrated operational-data copy passed desktop startup/search and
  readback (10,428 working rows, 17,427 catalog rows, 34 on-hand rows). This
  smoke check used the rehearsal copy; live verification was read-only.
- All 16 scanner HTTP checks were exercised. One oversized-frame test initially
  saw Windows socket reset 10053 in the sandbox, then passed outside it; no HTTP
  server behavior was changed for this migration.
- The older stock/UI mock suites already fail on unchanged `main`: the isolated
  baseline ran 53 checks with 26 errors and 1 failure, including obsolete callback
  signatures and incomplete mock controllers. They were not used as the acceptance
  gate; current workflows are covered in the passing active set. Retired returned-
  queue and generated-alias cases were replaced by current-schema coverage.
- KiotViet writes and a real PostgreSQL ERP import were not performed. SQLite
  remains the app database; the ERP importer must use `hot_sellers` and the new
  catalog-name columns. Unknown full/brand names remain NULL rather than guesses.

Live checks: `PRAGMA integrity_check` = **ok**; `PRAGMA foreign_key_check` =
**empty**; `PRAGMA foreign_keys` = **1**. No noncanonical IDs or non-UTC-format
stored timestamps remain. Both proposed test-row deletions remain pending.

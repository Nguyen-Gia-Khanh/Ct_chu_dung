# Warehouse cleanup migration

Close the warehouse app. Run from the repository root with its `.venv`.
The normal app refuses an old schema instead of silently migrating operational data.

Review only (does not modify the database):

```powershell
& .\.venv\Scripts\python.exe -m migrations.warehouse_cleanup --output data/schema-review/before
```

The review exports table definitions/counts, SQLite checks, SKU collisions,
Honda CSV comparison, stock conflicts, and the three missing-catalog CSV lists.
`full_catalogue.csv` is the Honda name source; `--honda-csv` can select it elsewhere.
Existing catalog brand names must match it before the CLI applies the upgrade.

Apply the choices approved for the 2026-10-18 cleanup:

```powershell
& .\.venv\Scripts\python.exe -m migrations.warehouse_cleanup --apply --keep-sku H06430-K56-N12 --register-missing --output data/schema-review/live
```

The script creates a SQLite backup and records its hash. It disables foreign
keys before `BEGIN IMMEDIATE`, normalizes all product IDs, rebuilds the schema,
registers missing catalog SKUs using existing names (unknown brand names stay
NULL), merges the chosen alias, moves the returned queue without overwrites,
and converts all stored timestamps to UTC with `+00:00`. It verifies both
`integrity_check` and `foreign_key_check` before committing, and restores
foreign key enforcement in `finally`. Exceptions without primary locations are
promoted. Known stock wins over NULL/999; disagreeing known counts abort.

One transaction publishes the complete compatible schema; the app never sees
an intermediate schema. Version rows 1 (schema/data) and 2 (retired sequence cleanup) make subsequent runs checked no-ops.
Version-1 databases receive only the version-2 SQLite metadata cleanup.
The original review and applied migration report are preserved on rerun;
`last-verification.json` contains the latest no-op check. Returned/on-hand
collisions or unexpected legacy tables/views/triggers stop the migration.

`--database` selects a scratch copy for rehearsal. Do not run old application
code against the upgraded operational database. Keep the source and database
versions together. Backups and operational reports are local, ignored data.

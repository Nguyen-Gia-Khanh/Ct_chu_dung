# Local data

The active SQLite database is `warehouse_locations.db` in this folder.
`backups/` contains the backup made during its one-time move from the project
root. Close the app before copying the database for another backup.

Inventory CSV/XLSX inputs may remain at the project root.

The warehouse schema cleanup makes an additional timestamped SQLite backup in
`backups/` before migration. `schema-review/` contains the local before/after
JSON reports and missing-catalog CSV lists. These operational files are ignored
by Git. See `../migrations/README.md` before opening an older database.

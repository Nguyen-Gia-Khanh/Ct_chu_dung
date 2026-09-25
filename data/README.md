# Local data

The refactored app stores its SQLite database and generated files here after
activation. Existing root data can be moved with
`python -m utils.migrate_data --apply` while the apps are closed.

Inventory CSV/XLSX inputs may remain at the project root.

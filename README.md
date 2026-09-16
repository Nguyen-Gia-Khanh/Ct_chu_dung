# Warehouse Shelf Mapper

A small local Windows application for assigning a fixed product catalogue to irregular warehouse shelf locations. It tracks **locations only**; your cloud inventory system remains the source of truth for stock quantities.

## What it does

- Imports product IDs and names from CSV.
- Searches product IDs and Vietnamese product names in real time, ignoring case and accents.
- Creates each shelf from floor, shelf code, and row count.
- Gives every row separate **left-half** and **right-half** cell counts.
- Numbers rows from the ground upward in both tabs, with Row 1 at the bottom.
- Adds new rows at the top and removes the highest rows first.
- Renders a clickable 2D front view with a fixed center divider.
- Allows multiple product IDs in the same slot.
- Removes staged products from the unassigned queue.
- Writes the shelf and all staged assignments to SQLite only when **Commit shelf + assignments** is pressed.
- Loads previously saved shelves and supports correcting assignments.

## Run on Windows 11

Extract the files together, keeping the `mapper` folder beside `warehouse_mapper.py`.
Open the script in VS Code, select your existing venv, and run it. From an activated
venv in the project folder, the equivalent command is:

```powershell
python warehouse_mapper.py
```

No Docker, JavaScript, database server, or third-party Python package is required.
The previous BAT launcher is optional; it is not needed to edit or run the Python source.

## Editing the source

| File | What to change here |
| --- | --- |
| `warehouse_mapper.py` | Entry point: starts the application. |
| `mapper/app.py` | Shelf loading, search, staging assignments, and commit actions. |
| `mapper/designer.py` | Metadata form and left/right cell inputs for each row. |
| `mapper/assignment_view.py` | Queue table, clickable shelf, and slot contents display. |
| `mapper/database.py` | SQLite schema and database operations. |
| `mapper/csv_import.py` | CSV reading and column selection. |
| `mapper/common.py` | Slot names, search normalization, and default database path. |
| `mapper/widgets.py` | Shared scrollable container. |

The entry point is intentionally small; the editable application code is in these modules.

## CSV format

Use `products_template.csv` as an example. The app asks which columns contain the product ID and product name, so additional columns are allowed and ignored.

```csv
product_id,product_name
P00001,Example Product One
P00002,Example Product Two
```

Export an Excel workbook as **CSV UTF-8** before importing it. Re-importing the same product ID updates its name without deleting its location.

## Workflow

1. Press **Import products CSV**.
2. Enter the floor, shelf code, and number of rows.
3. Press **Apply row count**, or use **Add row at top** / **Remove top row**.
4. For each row, enter the number of left-side and right-side cells.
5. Press **Build / refresh 2D shelf**.
6. Click a slot in the shelf view.
7. Search and select one or several products.
8. Press **Assign selected to clicked slot**. They leave the working queue immediately.
9. Repeat as needed.
10. Press **Commit shelf + assignments** to save everything in one SQLite transaction.

Yellow slots contain uncommitted assignments. Green slots contain saved assignments. Select products inside a slot and press **Return selected products to queue** to correct a location; commit again to make the correction permanent.

## Ground-up row numbering

In both tabs, a shelf with four rows displays Row 4 at the top, then Row 3, Row 2,
and Row 1 at ground level. Row lists and SQLite row numbers still use ascending
order internally: Row 1, Row 2, Row 3, Row 4.

**Add row at top** appends a new highest row (initially two cells on each side).
**Remove top row** removes only the highest row. Typing a smaller row count
removes the highest rows until the requested count is reached. Lower rows keep
their left/right values, slot IDs, and product assignments. Once a preview is
built, row-count changes also refresh the assignment tab.

Removing a row or cell that still has assigned products is blocked. Return or
move those products first; the removal and product changes can then be saved
together with **Commit shelf + assignments**. Changing the layout still requires
a commit, even when no products were changed.

## Location names

For Floor `1`, Shelf `A`, Row `3`, left-side cell `2`, the generated location is:

```text
1-A-R03-L02
```

The equivalent right-side cell ends in `R02`.

## Data and backup

The application creates `warehouse_locations.db` beside the script. This is a normal SQLite database and can be queried with SQLite tools or Python. Close the application and copy this file somewhere safe to make a complete backup.

The data model enforces one designated slot per product while allowing any number of different products in a slot.

The application expects `warehouse_locations.db` to use the current schema,
including shelf sides. If the database is from an older schema, delete it and
let the application create a fresh database. The download does not contain a
database that would replace your data.

## Checks

```powershell
python -m unittest -v test_warehouse_mapper test_mapper_rows
```

These checks cover database transactions, preserving placements and slot IDs,
adding/removing top rows, and both tabs' grid ordering. The UI checks use real Tcl
variables with recorded widget commands; they do not verify native Windows rendering.

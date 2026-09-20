# Warehouse Shelf Mapper

A local Windows/Tkinter application for mapping products to irregular warehouse
shelves. SQLite lives beside the Python entry point, so no Docker or database
server is required.

## Four focused tabs

1. **Shelf Designer** — import CSV files, create or edit a shelf, and commit its
   structure. Rows count upward from the ground and may contain different cell
   counts.
2. **Assign Locations** — search the total queue and full catalog, prepare a
   persistent on-hand batch, enter an exact floor/side/shelf/row/cell address,
   and move the batch into that address.
3. **Find Product** — search the full catalog by product ID or name and display
   the product's committed shelf location.
4. **Browse Shelves** — choose a committed shelf, view its 2D front layout, and
   click cells to inspect their products.

The total queue, on-hand queue, and assigned shelf locations are separate
states. A working product is in exactly one of them at a time.

## Run on Windows 11

Keep `warehouse_mapper.py`, the `mapper` folder, and the `utils` folder together.
From the activated virtual environment in the project folder:

```powershell
python warehouse_mapper.py
```

Selenium is only needed for the optional Chrome/KiotViet integration. The local
warehouse mapper itself uses Python's standard library.

## Main workflow

### Create the shelf structure

1. On tab 1, import the working product CSV and full catalog CSV as needed.
2. Enter floor, side, shelf code, and row count.
3. Enter the number of cells in every row. Row 1 is at ground level; adding or
   removing rows always changes the top of the shelf first.
4. Press **Build / refresh 2D shelf** to inspect the preview on tab 4.
5. Return to tab 1 and press **Commit shelf design**.

### Assign products by address

1. On tab 2, search the total unassigned queue.
2. Select one or more products and press **Move selected → on-hand**.
3. Enter each product's stock quantity. The on-hand batch is written to SQLite
   immediately and survives closing or restarting the app.
4. Enter Floor, Side, Shelf, Row, and Cell, then press **Load address →**.
5. Check the current address contents in the right pane.
6. Press **Assign all on-hand → loaded address**. This move is saved immediately
   in one SQLite transaction; the shelf-design Commit button is not involved.

Use **Dequeue all → total queue** to clear the on-hand batch without assigning
it. Use **Shelf → on-hand (all)** to remove every product from the loaded address
while preserving its recorded stock quantity for reassignment.

## Search and catalog behavior

One search box filters both the total queue and the full catalog. It searches
product ID, full name, and shortened name without case or Vietnamese accents.
An exact product ID also reports whether the product is on-hand or already at a
shelf address.

The full catalog is a permanent reference list. **Transfer selected to total
queue** copies catalog-only products into the working product list without
removing their catalog rows. Products already assigned or on-hand stay in their
current state.

An 11-character barcode such as `06410KFL850` is normalized to
`06410-KFL-850` in the search field.

## Location names

The location rule is centralized in `mapper/common.py`. For Floor `1`, Side
`1`, Shelf `A`, Row `8`, Cell `10`, the generated ID is:

```text
L1-1A8-10
```

## CSV behavior

The import dialog asks which columns contain product ID, full name, and
shortened name. Extra CSV columns are allowed. Re-importing an existing product
ID updates its names; it does not delete its shelf placement or historical
assignment time.

## Files

| File | Responsibility |
| --- | --- |
| `warehouse_mapper.py` | Small application entry point. |
| `mapper/app.py` | Coordinates tabs, searches, assignment actions, and optional web upload. |
| `mapper/designer.py` | Shelf metadata and irregular row editor. |
| `mapper/location_assignment_view.py` | Tab 2 total queue, on-hand batch, address form, and address contents. |
| `mapper/lookup_view.py` | Tab 3 product-to-location lookup. |
| `mapper/shelf_browser.py` | Tab 4 read-only shelf selector and front view. |
| `mapper/assignment_view.py` | Shared shelf renderer plus stock quantity dialog. |
| `mapper/database.py` | SQLite schema and atomic queue/location operations. |
| `mapper/csv_import.py` | CSV parsing and column mapping. |
| `mapper/common.py` | Location IDs, search normalization, and database path. |
| `mapper/web_upload.py` | Optional Selenium/KiotViet integration. |

## Data and backup

The app creates `warehouse_locations.db` beside `warehouse_mapper.py`. Close the
app and copy this one file to make a complete backup. Existing current-schema
databases are upgraded automatically with the new `on_hand_queue` table; shelves,
placements, quantities, and timestamps are not rewritten.

Deleting the database intentionally starts from an empty schema the next time
the app runs.

## Checks

```powershell
python -m unittest testers.test_on_hand_queue -v
python -m unittest testers.test_mapper_stock testers.test_web_upload testers.test_widgets -v
```

The on-hand tests cover persistence, exact-address assignment, shelf-to-on-hand
returns, stock preservation, and transaction safety.

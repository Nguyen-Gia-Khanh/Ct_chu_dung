# Warehouse Shelf Mapper

A local Windows/Tkinter application for mapping products to irregular warehouse
shelves. SQLite is local, so no Docker or database server is required.

## Even-side shelf orientation

Tkinter shelf views show each even-side row in descending cell order. Existing
shelves start with `switched_state = 0`; new even-side shelves start at `1`.
Changing a shelf between odd and even sides updates this state on commit.

To add the column to an older database once, run `py test_flip/add_switched_state.py` in
the project folder. The app also adds the missing column on startup. This does
not move any products. To test the one-time location switch on a separate copy,
run `py test_flip/flip_even_locations.py`. Re-running it on that copy skips
already switched shelves. When ready to switch the main database, run
`py test_flip/flip_even_locations.py --apply-to-main`.

## Seven tabs

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
5. **Switch / Combine Cells** — load two shelves independently, select one cell
   on each side, then atomically switch their contents or combine one complete
   cell into the other.
6. **Special Exceptions** — assign products to multiple shelf locations and
   register staged exceptions in the CSV and full catalog separately.
7. **Web Location Sync** — import a KiotViet Excel export, inspect location
   differences, resync mismatched products, and export a comparison workbook.

The total queue, on-hand queue, and assigned shelf locations are separate
states. A working product is in exactly one of them at a time.

## Run on Windows 11

Double-click `warehouse_mapper.exe` in the project folder to open the desktop
app without VS Code or a Python installation. The executable is committed at
the project root beside `warehouse_mapper.py`. Double-click
`warehouse_label_printer.exe` there to open the label printer.

To run the source instead, from the project folder with Python installed:

```powershell
python warehouse_mapper.py
```

`py warehouse_mapper.py` also works on Windows. Both launchers use
`data/warehouse_locations.db`. To choose another database, run
`python warehouse_mapper.py --db path/to/file.db`.

The executable contains its own Python runtime and libraries. It does not load
newly installed packages from a venv when you double-click it. To rebuild it
with the packages from the shared `Auto/.venv`, install the build tool in that
venv, then run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pip install pyinstaller
py utils/build_exe.py
```

Use `py utils/build_exe.py --app mapper` or `--app labels` to rebuild just one.
The build script selects `Auto/.venv` when present. Pass `--python` followed by
another `python.exe` path to select a different environment. The mapper build
includes Selenium's Chrome modules for the optional KiotViet connection.
The builds create single-file executables at the project root, so opening them
takes a few seconds while they unpack their runtimes.

Selenium is only needed for the optional Chrome/KiotViet integration. Tab 7
uses `openpyxl` to read and write `.xlsx` workbooks.

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
6. Ctrl-click one or more on-hand rows, then press **Assign selected on-hand →
   loaded address**. Only that selected subset moves; the rest stays on-hand.
   The move is saved immediately in one SQLite transaction.

Ctrl-click one or more on-hand rows and use **Dequeue selected → total queue**
to return only that subset without assigning it. Returned products keep their
stock in the total queue and appear first in bold yellow; moving them to on-hand
again prefills that stock and removes the highlight. In the loaded address,
Ctrl-click one or more rows and use **Selected product(s) → on-hand** for a
partial transfer. **Shelf → on-hand (all)** remains available when the complete
address must be emptied. These actions preserve each product's recorded stock
quantity for reassignment.

Web actions default to one product: click exactly one row in the loaded address,
then press **Modify selected product's web location**. Turn on **Process and save
all products in loaded address** to ignore row selection and update the complete
address sequentially. The batch saves each product before opening the next one,
reports its current position, and stops at the first failed SKU so the browser is
not advanced from an uncertain state. The temporarily hidden stock-upload action
uses the same single/all-products switch.

### Switch or combine cells

1. Open tab 5 and use each side's Floor → Side → Shelf → Row → Cell selectors,
   or find a cell by exact product ID/location ID.
2. Check the product list beneath each selected cell.
3. Use **Switch cells ↔** to exchange both complete contents, or either
   **Combine** button to empty its source into the other cell while keeping the
   target's existing products.

Each action asks for confirmation and writes one immediate SQLite transaction.
Stock quantities and original shelf-added timestamps are preserved. The two
shelves may be the same shelf or different shelves, but the selected cells must
be different. Pending Shelf Designer changes must be committed or discarded
first. This tab changes local SQLite locations only; use the tab 2 web action
afterward when KiotViet must receive the new location IDs.

### Compare and resync KiotViet locations

1. On tab 7, press **Import Web's Data** and choose the KiotViet `.xlsx` export.
   Import, comparison, and export run in the background while a thin loading bar
   shows activity.
2. Confirm the worksheet and columns. The supplied KiotViet headers **Mã hàng**
   and **Vị trí** are selected automatically.
3. Review website and local locations side by side. A website location with no
   saved local location is queued to be cleared on the website. Local IDs absent
   from the export are shown separately and are not uploaded.
4. Connect Chrome on tab 2, then press **Web resync** on tab 7. The app saves
   each comparable mismatch in sequence using tab 2's location-only
   upload; an empty local location clears the website selection without
   creating a location. Stock quantities are untouched. Successfully resynced
   rows are excluded from another upload until a new export is imported.
5. Press **Export comparison excel** to save the remaining mismatches under
   `data/exports/location_comparison/` as an `.xlsx` file with exactly `product_id`,
   `wrong_location`, and `true_location`.

Products with several local locations appear in the comparison and export,
but need manual web review because the current website uploader sets one
location per product. Import a new KiotViet export to verify completed updates.

## Search and catalog behavior

One search box filters both the total queue and the full catalog. It searches
product ID, full name, and shortened name without case or Vietnamese accents.
An exact product ID also reports whether the product is on-hand, returned to the
total queue, or already at a shelf address.

The full catalog is a permanent reference list. **Transfer selected to total
queue** copies catalog-only products into the working product list without
removing their catalog rows. Products already assigned or on-hand stay in their
current state.

An 11-character barcode such as `06410KFL850` is normalized to
`06410-KFL-850` in the search field.

## Location names

The location rule is centralized in `mapper/core/common.py`. For Floor `1`, Side
`1`, Shelf `A`, Row `8`, Cell `10`, the generated ID is:

```text
L1-1A8-10
```

## Special exceptions

On tab 6, enter a product ID and optional name, load a cell, then assign it.
The staged row remains visible while you register the product with **Append
back to CSV** and **Add to catalog**. Select a row to register one product;
clear the selection to process every product still waiting for that target.
The Staged Status column shows the remaining destinations or **Updated**.
Changing a staged name reopens both registrations so the new name can be saved.

**Wipe from treeview** removes the selected product from staging and the full
catalog, and deletes its regular and exception shelf placements. The working
product record and any CSV file remain. The app asks for confirmation first.

## CSV behavior

The import dialog asks which columns contain product ID, full name, and
shortened name. Extra CSV columns are allowed. Re-importing an existing product
ID updates its names; it does not delete its shelf placement or historical
assignment time.

## Code layout

| Path | Responsibility |
| --- | --- |
| `warehouse_mapper.py`, `warehouse_mapper.exe` | Root desktop launchers. Rebuild the executable after source changes. |
| `warehouse_label_printer.py`, `warehouse_label_printer.exe` | Root label printer launchers. |
| `warehouse_web.py` | Root launcher for the deprecated web UI. |
| `ui/desktop/` | Tkinter window, tabs, widgets, and action handlers. |
| `mapper/persistence/` | SQLite schema and catalog, shelf, inventory, and exception operations. |
| `mapper/features/` | CSV import, location comparison, and optional KiotViet integration. |
| `mapper/core/` | Shared location and search rules. |
| `mapper/api/` | Local HTTP API for the deprecated web UI. |
| `ui/web/` | Deprecated React/TypeScript UI, retained for reference. |
| `utils/labels/` | Label printer implementation. |
| `utils/laya/` | Laya extraction tools. |
| `utils/icsparts/` | ICS Parts catalog and part master scrapers. |
| `utils/build_exe.py` | Rebuilds the desktop executables. |
| `data/` | Local database and generated output, ignored by Git. |

The supported interface is Tkinter. The web UI and its API remain available as
deprecated code. Package `__init__.py` files identify Python packages; they
are not launchers.

## Data and backup

The active database is `data/warehouse_locations.db`. Close the app before
copying it for backup. The one-time move from the project root left a backup
under `data/backups/`. Input CSV and XLSX files remain where they are.

## Checks

```powershell
python -m unittest discover -s tests -v
```

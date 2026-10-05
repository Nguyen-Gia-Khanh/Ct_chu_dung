# Warehouse Shelf Mapper

A local Windows/Tkinter application for mapping products to irregular warehouse
shelves. SQLite is local, so no Docker or database server is required.

For source changes, see [instruction.md](instruction.md): it maps each desktop
tab to its view, action handlers, persistence methods, and verification steps.

## Seven tabs

1. [**Shelf Designer**](#tab-1-shelf-designer) — import CSV files, create or edit a shelf, and commit its
   structure. Rows count upward from the ground and may contain different cell
   counts.
2. [**Assign Locations**](#tab-2-assign-locations) — assign from the total queue or full catalog
   directly to an exact shelf address; hold removed shelf products on-hand
   for reassignment or return to their original list.
3. [**Primal Queue / Shelves**](#tab-3-primal-queue--shelves) — search working products and the full catalog,
   inspect queue/on-hand/assigned state and stock, and navigate to saved shelves.
4. [**Browse Shelves**](#tab-4-browse-shelves) — choose a committed shelf, view its 2D front layout, and
   click cells to inspect their products.
5. [**Switch / Combine Cells**](#tab-5-switch--combine-cells) — load two shelves independently, select one cell
   on each side, then atomically switch their contents or combine one complete
   cell into the other.
6. [**Special Exceptions**](#tab-6-special-exceptions) — assign products to multiple shelf locations and
   register staged exceptions in the CSV and full catalog separately.
7. [**Web Location Sync**](#tab-7-web-location-sync) — import a KiotViet Excel export, inspect location
   differences, resync mismatched products, and export a comparison workbook.

The total queue, on-hand queue, and assigned shelf locations are separate
states. Tab 6 supports the explicit exception of multiple shelf locations for
one product.

## Run on Windows 11

Double-click `warehouse_mapper.exe` in the project folder to open the desktop
app without VS Code. The small executable launches `warehouse_mapper.py` with
`../../.venv/Scripts/python.exe` and loads the UI, features, libraries, and
database from their existing folders. The project venv and source files must
remain in place. `warehouse_label_printer.exe` works the same way for the label
printer.

To run the source directly from the project folder:

```powershell
& '..\..\.venv\Scripts\python.exe' warehouse_mapper.py
```

Both launchers use `data/warehouse_locations.db`. To choose another database,
run `warehouse_mapper.exe --db path/to/file.db` or pass the same argument to
`warehouse_mapper.py`.

Changes to the Python source or packages in the venv take effect on the next
launch. To rebuild the small executables themselves, use MinGW-w64 GCC:

```powershell
py utils/build_exe.py
```

Use `py utils/build_exe.py --app mapper` or `--app labels` to rebuild just one.
The executables contain only the Windows launcher, not Python, Playwright, UI
code, or other app resources.

Playwright is only needed for the optional Chrome/KiotViet integration. Install
it in the launcher's venv with `python -m pip install playwright`. The existing
Chrome connection uses port 9222 and does not need ChromeDriver or a downloaded
Playwright browser. Tab 7 uses `openpyxl` to read and write `.xlsx` workbooks.

Start a separate debugging Chrome with its own profile (adjust the Chrome path
if needed), then log in to your store:

```powershell
& 'C:\Program Files\Google\Chrome\Application\chrome.exe' --remote-debugging-port=9222 --user-data-dir="$env:LOCALAPPDATA\WarehouseMapper\Chrome"
```

In Tab 7, paste your full store URL, such as
`https://hondaminhdung.kiotviet.vn/man/#/Products`, and press **Save settings**.
The URL and **Upload tabs** count are remembered in `data/kiotviet_settings.json`.
Valid edits also save when you leave a field, connect Chrome, or close the app.
Changing stores requires reconnecting Chrome.

## Tab 1: Shelf Designer

1. On tab 1, import the working product CSV and full catalog CSV as needed.
2. Enter floor, side, shelf code, and row count.
3. Enter the number of cells in every row. Row 1 is at ground level; adding or
   removing rows always changes the top of the shelf first.
4. Press **Build / refresh 2D shelf** to inspect the preview on tab 4.
5. Return to tab 1 and press **Commit shelf design**.

To delete a saved shelf, select it under **Edit existing shelf**, press
**Delete shelf**, and confirm. Deletion saves immediately and removes the shelf's
rows and cells. Move all regular and exception products off the shelf first.
Commit pending designer changes or discard them with **New shelf** before deleting.

### CSV imports

The import dialog asks which columns contain product ID, full name, and
shortened name. Extra CSV columns are allowed. Re-importing an existing product
ID updates its names; it does not delete its shelf placement, stock, or
historical assignment time. IDs absent from a later CSV remain in the database.
Re-importing the full catalog updates its stored names; queue names continue
to take precedence in the combined view for IDs still in the working queue.

View: [designer.py](ui/desktop/designer.py). Shelf creation, preview, and
commit: [shelf_actions.py](ui/desktop/shelf_actions.py). CSV imports:
`CatalogActions.import_csv` / `import_catalog_csv` in
[catalog_actions.py](ui/desktop/catalog_actions.py). Preview drawing is shared
with Tab 4; see the [source guide](instruction.md#tab-1-shelf-designer).

## Tab 2: Assign Locations

### Assign products by address

1. On tab 2, search the product queue. Unassigned matches appear first; assigned
   matches remain visible in gray below them. Gray applies only to this queue.
   The **Location ID** column shows assigned shelf addresses and is blank for
   unassigned products.
   Only ready rows can move through the queue transfer buttons.
2. Enter Floor, Side, and Shelf in the middle pane. Select **Shelf Selection
   Pane** to view that shelf, then click a cell to fill Row and Col and load it.
   You can also enter Row and Col manually and press **Load address →**.
3. Check the current address contents in the right pane.
4. Select products from the total queue or full catalog and press
   **Assign selected queue → loaded address** or
   **Assign selected catalog → loaded address**. Enter each product's stock
   quantity and confirm. Assignment saves immediately without passing through
   on-hand. Catalog-only products are never added to the total queue.
5. On-hand holds products removed from a shelf. To reassign those products,
   select on-hand rows and use **Assign selected on-hand → loaded address**.
   The batch survives restarting the app; **Edit selected quantity** adjusts
   its stock before reassignment.

**Quick move to location**, beside the search status, is available when the
search matches exactly one distinct product across the queue and full catalog.
It fills Floor / Side / Shelf / Row / Col, opens the Shelf Selection Pane,
and loads that product's saved cell without moving inventory. Products with
multiple locations open their primary saved cell (or first exception cell).

### Shift shortcuts

Normal clicks assign selected products directly. Hold **Shift** to enable
the direct-transfer/whole-batch shortcuts; the button labels change while it
is held.

| Button/source | Normal click | Hold Shift and click |
| --- | --- | --- |
| Full catalog assignment | Selected products → loaded cell, with manually entered quantities and no total-queue copy. | One selected product → loaded cell, with stock **999**. |
| Total queue assignment | Selected ready products → loaded cell, with manually entered quantities. | All visible ready queue search results → loaded cell, with stock **999**. |
| On-hand assignment | Selected on-hand rows → loaded cell, retaining quantities. | All on-hand products → loaded cell, retaining quantities. |

The queue shortcut requires IDs with the same first five characters after
removing hyphens, trimming, and uppercasing. One visible result moves with one
Shift-click. Multiple results need three clicks while holding Shift; each
pending click restarts a three-second timeout. Releasing Shift or changing the
queue search resets the count. Lists show at most 750 results, so narrow the
search and inspect the visible queue before using this shortcut.

Direct/whole-batch assignment requires a loaded saved address. **Revert shift
transfer** asks for confirmation and reverses the latest successful Shift
transfer. This is a single in-memory snapshot, cleared by reversal and lost
when the app closes.

### Return products and modify stock

Removing products from a shelf moves them to on-hand first. Ctrl-click one or
more on-hand rows and use **Dequeue selected → queue / catalog** to remove
that subset from the batch. Total-queue products return to the total queue with
stock retained; catalog-only products return to the full catalog, even after
being assigned and removed from a shelf. Dequeue does not restore a shelf
assignment. Returned queue rows use ordinary styling, with no yellow or bold
highlight; moving them to on-hand again prefills their stock. Queue/catalog
membership survives restarting the app.
Transfers made before source tracking was added return to the total queue.
In the loaded address,
Ctrl-click one or more rows and use **Selected product(s) → on-hand** for a
partial transfer. **Shelf → on-hand (all)** remains available when the complete
address must be emptied. These actions preserve each product's recorded stock
quantity for reassignment.

All these Tab 2 moves and stock edits save immediately; **Commit shelf design**
is for the Shelf Designer's pending changes. To move a product while preserving
its actual stock, use normal assignment with the prefilled quantities. Catalog/queue Shift
transfers use stock **999**.

### Update website locations

**Connect Chrome** on the main tab bar starts the browser connection and returns
to the current tab. Web actions default to one product: click
exactly one row in the loaded address, then press **Modify selected product's
web location**. Turn on **Process and save
all products in loaded address** to ignore row selection and update the complete
address sequentially. The batch saves each product before opening the next one,
reports its current position, and stops at the first failed SKU so the browser is
not advanced from an uncertain state. The temporarily hidden stock-upload action
uses the same single/all-products switch.

### Search and catalog behavior

One search box filters both the total queue and the full catalog. It searches
product ID, full name, and shortened name without case or Vietnamese accents.
An exact product ID also reports whether the product is on-hand, returned to the
total queue, or already at a shelf address.

The full catalog view combines the working queue and warehouse catalog by
product ID. Queue names take precedence for matching IDs; other products use
their warehouse catalog names. The two CSV imports remain separate, so
re-importing the queue does not overwrite stored warehouse catalog names.
**Assign selected catalog → loaded address** assigns catalog products directly
to the loaded shelf with entered stock. Catalog-only products remain outside
the total queue throughout assignment and shelf removal. Shelf removal holds
them on-hand until reassignment or Dequeue returns them to the catalog.
Double-clicking a catalog or total-queue product only fills and selects its ID
in the search field; it does not transfer the product.

An 11-character barcode such as `06410KFL850` is normalized to
`06410-KFL-850` in the search field.

View: [location_assignment_view.py](ui/desktop/location_assignment_view.py).
Moves and stock/address actions: [assignment_actions.py](ui/desktop/assignment_actions.py).
Search and catalog transfers: [catalog_actions.py](ui/desktop/catalog_actions.py).
Quantity entry uses `StockQuantityDialog` in the shared `assignment_view.py`;
[source sections and callbacks](instruction.md#tab-2-assign-locations) are listed
in the source guide.

## Tab 3: Primal Queue / Shelves

Search the working product list and full catalog by product ID, full name, or
shortened name. Working products remain in this view after assignment: their
rows report assigned location, on-hand state, returned state, or unassigned
state and any recorded stock. Exact-ID search or selecting an assigned product
navigates to its saved shelf and cell.

Double-click a working/catalog result or a cell-content row to fill and select
its ID in the search field. Use the saved-shelf selector or Floor/Side/Shelf
lookup to browse a shelf, then click a cell to inspect its products. These
search and selection actions do not move inventory.

View and handlers: [primal_queue_view.py](ui/desktop/primal_queue_view.py).
Shelf lookup uses `ShelfAddressLookup`; cell styling and row refresh use
`shelf_cell_visual` / `sync_tree_rows` in `widgets.py`. The older `lookup_view.py`
is not the active numbered tab. See [Tab 3 source sections](instruction.md#tab-3-primal-queue--shelves).

## Tab 4: Browse Shelves

Choose a saved shelf from the list or load it by Floor/Side/Shelf. Click a cell
to see its saved products, quantities, and added-to-shelf times. Browsing does
not change assignments.

Tab 1 also sends its unsaved layout preview here. Check the summary:
**Committed SQLite data** describes a saved shelf; **Uncommitted shelf preview**
describes pending designer changes. Return to Tab 1 and commit to save a preview.

View: [shelf_browser.py](ui/desktop/shelf_browser.py). The common shelf renderer
is `AssignmentView.render_shelf` / `refresh_cell` in
[assignment_view.py](ui/desktop/assignment_view.py), while the preview producer
is `ShelfActions.render_shelf`. This renderer is separate from the stock dialog
used by Tab 2. See [Tab 4 source sections](instruction.md#tab-4-browse-shelves).

## Tab 5: Switch / Combine Cells

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
first. Switch/combine changes local SQLite locations. To update KiotViet afterward,
use the explicit **Modify location ID on web** action on this tab or the
location action on Tab 2.

View and local actions: [cell_transfer_view.py](ui/desktop/cell_transfer_view.py),
`CellTransferPane` / `CellTransferView`. `swap_slot_contents` / `combine_slot_contents`
in `mapper/persistence/inventory.py` handle transactions. Pending-change checks
come from `ShelfActions.can_change_cells`; web requests use
`WebActions.modify_cell_transfer_locations`. See [Tab 5 source sections](instruction.md#tab-5-switch--combine-cells).

## Tab 6: Special Exceptions

On tab 6, enter a product ID and optional name, load a cell, then assign it.
New exceptions appear in the full catalog view and stay out of the total/primal
queue. Adding an exception for an existing queue product keeps its membership.
The staged row remains visible while you register the product with **Append
back to CSV** and **Add to catalog**. Select a row to register one product;
clear the selection to process every product still waiting for that target.
The Staged Status column shows the remaining destinations or **Updated**.
Changing a staged name reopens both registrations so the new name can be saved.

**Wipe from treeview** removes the selected product from staging and the full
catalog, and deletes its regular and exception shelf placements. The working
product record and any CSV file remain. The app asks for confirmation first.

To remove only one location, load that cell and use the remove-from-cell action.
Other locations and registration remain. Catalog double-click fills the product
ID and looks it up without assigning it.

View: [exceptions_view.py](ui/desktop/exceptions_view.py). Assignment, staging,
registration, and removal use `ExceptionOperations` in
[mapper/persistence/exceptions.py](mapper/persistence/exceptions.py).
`StateActions.on_exception_data_changed` refreshes app caches after these writes.
See [Tab 6 source sections](instruction.md#tab-6-special-exceptions).

## Tab 7: Web Location Sync

1. On tab 7, press **Import Web's Data** and choose the KiotViet `.xlsx` export.
   Import, comparison, and export run in the background while a thin loading bar
   shows activity.
2. Confirm the worksheet and columns. The supplied KiotViet headers **Mã hàng**
   and **Vị trí** are selected automatically.
3. Review website and local locations side by side. A website location with no
   saved local location is queued to be cleared on the website. Local IDs absent
   from the export are shown separately and are not uploaded.
4. Save your store URL in Tab 7, choose **Upload tabs** (1-10), and press
   **Connect Chrome** on the main tab bar. Then press **Web resync** on Tab 7. The app saves
   each comparable mismatch using the selected number of location-only
   browser worker; an empty local location clears the website selection without
   creating a location. Stock quantities are untouched. Successfully resynced
   rows are excluded from another upload until a new export is imported.
5. Press **Export comparison excel** to save the remaining mismatches under
   `data/exports/location_comparison/` as an `.xlsx` file with exactly `product_id`,
   `wrong_location`, and `true_location`.

Products with several local locations are compared and uploaded as complete
location sets, including exception placements. Commas, semicolons, pipes, and
newlines in the website export are accepted as location separators. Import a
new KiotViet export to verify completed updates.

With more than one upload tab, resync creates separate tabs in your logged-in
Chrome context and processes different products concurrently. Location creation
is coordinated to avoid duplicate shelf names. Successful batches close their
worker tabs; failed batches leave tabs open for inspection. An error stops new
products while those already running finish; completed products remain marked as synced. Leave the
store tabs untouched during resync. Tabs 2 and 5 continue processing sequentially.

View: [location_comparison_view.py](ui/desktop/location_comparison_view.py).
Excel parsing/comparison/export: [location_comparison.py](mapper/features/location_comparison.py).
Browser requests: `WebActions.resync_web_locations`, sharing the worker and
`WebsiteUploader` with Tabs 2 and 5. See [Tab 7 source sections](instruction.md#tab-7-web-location-sync).

## Shared behavior and function ownership

A shared file can contain sections serving different tabs. Use the named class
or method to find the relevant section; the [full function-to-tab map](instruction.md#shared-files-function-sections-and-tab-consumers)
includes persistence and retained handlers.

| Shared file / section | Tabs using it |
| --- | --- |
| `app.py`: `_build_ui`, `on_tab_changed`, `on_global_barcode_scan` | All tabs: wiring, activation, scans. |
| `catalog_actions.py`: import methods vs. search/transfer methods | Imports on 1; search/transfers on 2. Imported data is also read by 3 and 6. |
| `assignment_view.py`: `StockQuantityDialog` vs. `AssignmentView.render_shelf` / `refresh_cell` | Quantity dialog on 2; shelf rendering on 4, including previews from 1. |
| `shelf_actions.py`: preview/commit vs. `can_change_cells` | Editor/preview on 1 and 4; pending-change guard on 5. |
| `state_actions.py`: `reconcile_inventory_products`, `refresh_visible_cells`, `on_exception_data_changed` | Writes from 2/5; visible cells on 2/3/4/5; exception callback from 6. |
| `widgets.py`: `ScrollableFrame`, `sync_tree_rows`, `shelf_cell_visual` | Scrolling on 1-5; row updates on 2-5; common cell styling on 3-5. Tab 2 has its own compact styling. |
| `shelf_address_lookup.py`: `ShelfAddressLookup` | 3, 4, 5. Tabs 2/6 use their own address fields. |
| `mapper/core/common.py`: `clean_location_segment`, `make_slot_name`, `normalize_search` | Address/search consumers in 1-6; 7 reads saved location names and has separate comparison rules. |
| `utils/barcode_scanner.py`: scan detection and ID/entry helpers | Main scan/search flows on 2, 3, 5, 6. |
| `web_actions.py`: selected-cell methods, `modify_cell_transfer_locations`, `resync_web_locations`, worker methods | Requests from 2, 5, 7 respectively; shared Chrome/worker code. |

### Shelf orientation

Tkinter shelf views show each even-side row in descending cell order. The
one-time remap of existing product locations is complete. New products use the
current location IDs directly, so shelves no longer store a switching flag.

### Location names

The location rule is centralized in `mapper/core/common.py`. For Floor `1`, Side
`1`, Shelf `A`, Row `8`, Cell `10`, the generated ID is:

```text
L1-1A8-10
```

## Code layout

| Path | Responsibility |
| --- | --- |
| `warehouse_mapper.py`, `warehouse_mapper.exe` | Root desktop script and small launcher; Python changes load on the next run. |
| `warehouse_label_printer.py`, `warehouse_label_printer.exe` | Root label printer script and small launcher. |
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
| `utils/build_exe.py`, `utils/launcher.c` | Rebuild the small desktop launchers. |
| `data/` | Local database and generated output, ignored by Git. |

The supported interface is Tkinter. The web UI and its API remain available as
deprecated code. Package `__init__.py` files identify Python packages; they
are not launchers.

## Data and backup

The active database is `data/warehouse_locations.db`. Close the app before
copying it for backup. The one-time move from the project root left a backup
under `data/backups/`. Input CSV and XLSX files remain where they are.

## Checks

Run from the project root using the launcher's Python environment:

```powershell
& '..\..\.venv\Scripts\python.exe' -m unittest discover -s tests -v
```

For manual checks with sample data, create a separate database so testing does
not change your working inventory:

```powershell
New-Item -ItemType Directory -Force tmp | Out-Null
& '..\..\.venv\Scripts\python.exe' warehouse_mapper.py --db tmp/manual-check.db
```

Import sample products and commit a sample shelf in that database before
testing address transfers. See [instruction.md](instruction.md) for the tab
file map and the specific behaviors to check after a source change.

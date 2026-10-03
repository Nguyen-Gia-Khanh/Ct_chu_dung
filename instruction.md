# Desktop source and behavior guide

Use this file to locate the code for a requested desktop change. [README.md](README.md)
explains how to launch the app and perform warehouse workflows. The supported UI
is Tkinter; `ui/web/` and `mapper/api/` are retained as deprecated code.

## Tab index

- [Tab 1: Shelf Designer](#tab-1-shelf-designer)
- [Tab 2: Assign Locations](#tab-2-assign-locations)
- [Tab 3: Primal Queue / Shelves](#tab-3-primal-queue--shelves)
- [Tab 4: Browse Shelves](#tab-4-browse-shelves)
- [Tab 5: Switch / Combine Cells](#tab-5-switch--combine-cells)
- [Tab 6: Special Exceptions](#tab-6-special-exceptions)
- [Tab 7: Web Location Sync](#tab-7-web-location-sync)
- [Shared files: function sections and tab consumers](#shared-files-function-sections-and-tab-consumers)

Each tab section identifies its view, action methods, shared dependencies, save
boundary, and checks. Shared files below are divided by named classes/functions
so a file used by several tabs can be edited at the relevant section.

## Entry points and tab wiring

`warehouse_mapper.py` parses `--db`, creates the Tk root, and starts
`WarehouseMapperApp` in [ui/desktop/app.py](ui/desktop/app.py). The root `.exe`
launchers load the Python source at runtime, so source edits take effect after
restarting the app without rebuilding the launcher.

Start with `WarehouseMapperApp._build_ui` to identify a tab's view and callbacks.
`on_tab_changed` refreshes the selected tab and resets Tab 2's Shift mode.
`on_global_barcode_scan` routes scans to the current view. The extra **Connect
Chrome** tab triggers a connection and returns to the previous content tab.

| Tab | View file | Related logic and responsibilities |
| --- | --- | --- |
| 1. Shelf Designer | [designer.py](ui/desktop/designer.py) | [shelf_actions.py](ui/desktop/shelf_actions.py): new/load shelf, row resizing, preview, pending-change checks, and explicit commit. CSV imports are in `catalog_actions.py`. |
| 2. Assign Locations | [location_assignment_view.py](ui/desktop/location_assignment_view.py) | `assignment_actions.py`: address loading, on-hand moves, quantities, assignment, Shift shortcuts, and revert. `catalog_actions.py`: searches, catalog transfers, and imports. |
| 3. Primal Queue / Shelves | [primal_queue_view.py](ui/desktop/primal_queue_view.py) | Working-product and full-catalog search, state/stock display, exact-ID navigation, shelf cells, and their contents. |
| 4. Browse Shelves | [shelf_browser.py](ui/desktop/shelf_browser.py) | Saved-shelf selection and designer previews. Uses `AssignmentView` in `assignment_view.py` for the shelf drawing and cell visuals. |
| 5. Switch / Combine Cells | [cell_transfer_view.py](ui/desktop/cell_transfer_view.py) | `CellTransferPane` owns each side's search, selectors, shelf, and contents. `CellTransferView` validates the pair, confirms operations, and calls database switch/combine methods. |
| 6. Special Exceptions | [exceptions_view.py](ui/desktop/exceptions_view.py) | Existing-ID lookup, extra locations, unregistered-product assignment, staged name edits, separate CSV/catalog registration, and removal. Persistence is in `mapper/persistence/exceptions.py`. |
| 7. Web Location Sync | [location_comparison_view.py](ui/desktop/location_comparison_view.py) | Excel column selection, comparison, background progress, export, and resync requests. Comparison rules are in `mapper/features/location_comparison.py`; browser operations are in `web_actions.py`. |

`lookup_view.py` contains the older `ProductLookupView`. The current numbered
Tab 3 is built from `PrimalQueueView`; `app.lookup` is an alias for that view.
Check the app wiring before editing an older view with a similar purpose.

## Tab 1: Shelf Designer

**View:** [designer.py](ui/desktop/designer.py), `ShelfDesigner`.
`prepare_row_inputs`, `add_row`, `remove_top_row`, and `validated_layout` own
the structure controls. Row 1 is the ground row; new rows are added at the top.

**Actions:** [shelf_actions.py](ui/desktop/shelf_actions.py), `ShelfActions`.
`new_shelf` / `load_selected_shelf` manage editor state; `can_resize_rows` and
`_slots_are_empty` guard removal of occupied cells; `build_shelf_preview` and
`render_shelf` send the preview to Tab 4; `commit_changes` saves it.
`has_pending_changes` / `confirm_discard_pending` also protect navigation and
Tab 5 operations. Previewing is unsaved; **Commit shelf design** is explicit.
`delete_selected_shelf` deletes the shelf chosen in the existing-shelf selector
after confirmation, blocks pending designer changes, and refreshes saved-shelf
views. It calls `ShelfOperations.delete_shelf`, which rejects shelves containing
regular or exception placements. Deletion saves immediately.

**Shared sections:** `CatalogActions.import_csv` / `import_catalog_csv` and
`ColumnMappingDialog` handle this tab's two import buttons. Imports write
immediately through `catalog.py` rather than waiting for the shelf commit.
`ShelfOperations.commit_shelf` / `_sync_layout` in `shelves.py` save layouts.
`StateActions.reload_database_state`, `remember_imported_products`, and
`refresh_shelf_selector` in `ShelfActions` keep caches/selectors current.
`ScrollableFrame` scrolls the row editor; `clean_location_segment` and
`make_slot_name` provide naming shared with the other tabs.

**Check:** preview then commit a new shelf; reload it for editing; verify that
occupied cells cannot be removed and even-side display keeps the saved IDs.
CSV reimport preservation is covered by `tests/test_persistence.py`.

## Tab 2: Assign Locations

### Layout

The left pane contains **Total unassigned product queue** and **Full product
catalog**, filtered by one search field. The middle pane switches between
**On-hand queue** and **Shelf Selection Pane**, with Floor / Side / Shelf / Row /
Col address fields below. The right pane displays the loaded cell's products,
stock, added-to-shelf time, and local/web actions.

Selecting a preview cell calls `_select_shelf_cell`, fills Row and Col, and calls
`on_load_address`. Typing address fields alone does not load a new destination;
`load_assignment_address` must resolve a saved `SlotAddress`.

### Normal clicks and Shift clicks

The original Shift behavior is intentional: normal clicks prepare selected
products in a queue; holding Shift enables direct or whole-batch transfers.

| Source/button | Normal click | Hold Shift and click |
| --- | --- | --- |
| Catalog transfer | Selected catalog products go to the total queue. Existing shelf/on-hand products are pulled back to the queue with their stock retained. | Exactly one selected catalog product goes directly to the loaded cell with stock `999`. |
| Total queue transfer | Selected queue products go to on-hand after entering each quantity in `StockQuantityDialog`. | All currently visible queue rows go directly to the loaded cell with stock `999`; this uses the displayed search results, not just the selected rows. |
| On-hand assignment | Only selected on-hand rows go to the loaded cell with their recorded quantities. | The entire on-hand batch goes to the loaded cell with its recorded quantities. |

Direct transfers require a loaded saved cell. For the queue shortcut, IDs must
share the first five characters after removing hyphens, trimming, and uppercasing;
shorter prefixes are rejected. One visible product transfers in one click.
Multiple products require three clicks while holding Shift. Each pending click
restarts a three-second timeout. Releasing Shift or refreshing queue search
results resets that click count.

`Revert shift transfer` remembers the latest successful Shift transfer from the
catalog, queue, or whole on-hand batch. It asks for confirmation and restores
captured product state through `WarehouseDatabase.revert_shift_transfer`.
The snapshot lives in `app.last_shift_transfer` and is lost on restart; this is
one-step reversal, not a general history of all inventory edits.

### Files and methods to read before changing Tab 2

| Change | Read these methods/files together |
| --- | --- |
| Shift behavior or changing button labels | `LocationAssignmentView.set_whole_mode`, `_on_shift_press`, `_on_shift_release`, the three `_on_*_button_press` / `_handle_*_click` pairs, and the corresponding action methods. |
| Queue to on-hand or direct cell transfer | `AssignmentActions.move_selected_to_on_hand`, `_start_queue_shift_timer`, `_reset_queue_shift_clicks`, and `LocationAssignmentView.set_queue_button_clicks`. |
| Catalog to queue or direct cell transfer | `CatalogActions.transfer_catalog_selection_to_queue`; database `import_products`, `force_pull_to_queue`, and `assign_catalog_direct_to_slot`. |
| Selected/all on-hand assignment | `AssignmentActions.assign_on_hand_to_address`; database `assign_on_hand_to_slot`. |
| Returning products from a cell | `move_selected_address_to_on_hand` and `move_address_to_on_hand`; database `move_slot_to_on_hand`. |
| Returning on-hand products to total queue | `dequeue_selected_on_hand`; database `dequeue_on_hand`. Returned products retain stock and appear first in bold yellow. |
| Stock entry or modification | `StockQuantityDialog` in `assignment_view.py`, `modify_on_hand_stock`, `_modify_loaded_address_stock`, and `validate_stock_quantity`. |
| Search, location status, catalog double-click | `CatalogActions.schedule_queue_refresh`, `refresh_product_queue`, `refresh_catalog`, `refresh_search_location`, and `activate_catalog_product`. |
| Queue double-click | `LocationAssignmentView._on_queue_double_click` fills and selects the search field; it does not move inventory. |
| Compact shelf text, count, color, selection | `render_shelf_preview`, `refresh_shelf_cell`, `highlight_shelf_cell`, and `WarehouseMapperApp.refresh_assignment_shelf_preview`. |
| Web action scope and labels | `LocationAssignmentView._refresh_web_action_labels`; `WebActions._web_placements`, `_saved_location_sets`, and `_location_updates`. |

Shift state is stored in `view.whole_mode`. Mouse press handlers also capture
the event's Shift bit in `_shift_clicked`, which click handlers consume. The
action layer checks the requested flag and the view's current mode. A modifier
change must keep labels, click routing, action routing, and timer resets aligned.

Search normalization is case- and Vietnamese-accent-insensitive. An exact ID
reports its queue/on-hand/shelf state. Tab 2 catalog filtering also matches saved
location text. Each product list displays at most `MAX_VISIBLE_PRODUCTS` (750),
so narrow the search before using the visible-queue Shift shortcut.

### Shelf display conventions

Row 1 is the ground row. Layout arrays are ordered from the ground upward;
renderers position the highest row first on screen. Even-side rows display cells
in descending order without renumbering the stored cell IDs.

The compact Tab 2 cell label uses bold row/column text and a numeric product
count on the following line. Empty cells are gray, occupied cells are green,
and the selected cell is blue. Both initial rendering and `refresh_shelf_cell`
must preserve the same numeric count format. Other shelf views use their own
label format; changing Tab 2 does not require changing every renderer.

**Refresh dependencies:** `StateActions.apply_inventory_changes` and
`reconcile_inventory_products` update the queue/catalog/on-hand caches after
writes. `refresh_visible_cells` routes changed cells to the active view.
`StockQuantityDialog` belongs to the quantity-entry section of
`assignment_view.py`; that file's shelf renderer primarily serves Tab 4.

**Save boundary:** the current address/on-hand actions save immediately.
**Check:** selected moves, all three Shift shortcuts, prefix rejection, timer
reset, reversal, restart persistence, and unchanged stock in ordinary moves.
`tests/test_incremental_desktop.py` checks the numeric count format and widget
reuse; `tests/test_persistence.py` checks the underlying inventory moves.

## Tab 3: Primal Queue / Shelves

**View and local handlers:** [primal_queue_view.py](ui/desktop/primal_queue_view.py),
`PrimalQueueView`. `refresh` reads working/catalog products and inventory state;
`refresh_results` / `_update_search_status` filter the two lists and report
assigned, on-hand, returned, and unassigned products. Exact-ID search and row
selection use `_highlight_product_location` to navigate to a saved shelf.
The three `_on_*_double_click` handlers fill/select the search field.

**Shelf section:** `_load_shelf_by_id`, `_render_shelf`, `select_slot`,
`_refresh_slot_contents`, and `refresh_cell` own the shelf and selected contents.
This is a read-only inspection tab; searching/selecting does not move products.

**Shared sections:** `ShelfAddressLookup` handles Floor/Side/Shelf lookup;
`ScrollableFrame`, `shelf_cell_visual`, and `sync_tree_rows` handle display and
updates. `normalize_search` / `MAX_VISIBLE_PRODUCTS` apply to the lists;
`make_slot_name` labels the cells. Database reads use `get_product_location`,
`get_placement_details`, `get_shelf`, and `get_shelf_contents`.
`StateActions.refresh_visible_cells` can update this tab's changed cells.

**Check:** search a working ID and a catalog-only ID, inspect each state, follow
an assigned ID to its cell, and double-click a result or cell-content row.
`tests/test_incremental_desktop.py` covers source/destination cell refreshes.
The older `lookup_view.py` is not the active Tab 3 implementation.

## Tab 4: Browse Shelves

**View:** [shelf_browser.py](ui/desktop/shelf_browser.py), `ShelfBrowserView`.
`show_saved_shelf` loads committed data; `show_preview` displays Tab 1's
uncommitted layout; `_show_layout` feeds the common renderer. `select_slot`,
`refresh_cell`, and `refresh_loaded_contents` update the selected contents.
The summary distinguishes **Committed SQLite data** from **Uncommitted shelf
preview**. Browsing and selecting cells do not write to SQLite.

**Shared sections:** [assignment_view.py](ui/desktop/assignment_view.py),
`AssignmentView.render_shelf`, `_cell_visual`, `refresh_cell`, and
`mark_selected` draw and highlight cells. These are separate from that file's
`StockQuantityDialog` used by Tab 2. `ShelfActions.render_shelf` is the Tab 1
preview producer; `ShelfAddressLookup` selects saved shelves. Rendering uses
`ScrollableFrame` / `shelf_cell_visual`; contents use `sync_tree_rows`.
Persistence reads come from `shelves.py`; `StateActions.refresh_visible_cells`
refreshes committed cells here after inventory changes.

**Check:** load a saved shelf and inspect cells, then preview a changed layout
from Tab 1 and confirm it is marked uncommitted. Check count/color/selection
after a move. Relevant refresh tests are in `tests/test_incremental_desktop.py`.

## Tab 5: Switch / Combine Cells

**View and handlers:** [cell_transfer_view.py](ui/desktop/cell_transfer_view.py).
`CellTransferPane.find`, `load_shelf`, `select_address`, `_render_shelf`,
`_refresh_contents`, and `refresh_cell` own each pane. `CellTransferView`
owns `_selected_pair`, `swap_cells`, `combine_cells`, and the optional explicit
`modify_location_on_web` action. Switch exchanges both complete cells; combine
moves all source contents into the destination while retaining its contents.

**Shared sections:** `ShelfActions.can_change_cells` checks pending designer
changes before a mutation. `InventoryOperations.swap_slot_contents` /
`combine_slot_contents` in `inventory.py` perform immediate transactions after
confirmation, retaining quantities and original assignment timestamps.
`WarehouseMapperApp.on_cell_transfer_changed` reconciles affected products
through `StateActions.reconcile_inventory_products` / `refresh_visible_cells`.
`ShelfAddressLookup`, `ScrollableFrame`, `shelf_cell_visual`, and `sync_tree_rows`
serve both panes. Explicit web updates use
`WebActions.modify_cell_transfer_locations` and the shared upload worker.

**Check:** switch and both combine directions, same-cell rejection, pending
designer-change rejection, and source/destination counts after a move.
`tests/test_persistence.py` checks quantity/time preservation;
`tests/test_incremental_desktop.py` checks that only changed cells refresh.

## Tab 6: Special Exceptions

**View and handlers:** [exceptions_view.py](ui/desktop/exceptions_view.py),
`ExceptionsView`. `find_product`, `load_address`, and `assign_exception` add
locations for existing or unregistered products. `save_name` updates staging;
`append_to_csv` and `add_to_catalog` register each target separately.
`refresh_pending_tree`, `refresh_multi_location_tree`, and
`_filter_catalog_tree` update its three product views. Catalog double-click
fills the ID and calls `find_product`; it does not assign the product.

**Shared sections:** `ExceptionOperations` in `mapper/persistence/exceptions.py`
owns `find_product_locations`, `assign_exception`,
`update_staged_exception_name`, `append_pending_to_csv`, `add_staged_to_catalog`,
`remove_exception_from_slot`, and `wipe_staged_exception`.
`remove_from_loaded_cell` removes only the chosen location; `wipe_selected`
removes staging/catalog entries and all shelf placements after confirmation.
The latter preserves the working product record and existing CSV file.
`WarehouseMapperApp` wires the refresh callback to
`StateActions.on_exception_data_changed`, which reloads caches and views.
`clean_location_segment`, `make_slot_name`, `normalize_search`, and barcode
formatting are shared helpers; this tab builds its own address fields.

**Save boundary:** placement is immediate; CSV and catalog registration are
separate saves tracked by staging status. **Check:** add a second location,
remove just one location, edit/register a staged name, and distinguish removal
from wipe. `tests/test_multi_locations.py` and `tests/test_persistence.py`
cover multiple locations and independent registration targets.

## Tab 7: Web Location Sync

**View and handlers:** [location_comparison_view.py](ui/desktop/location_comparison_view.py).
`save_browser_settings` persists the validated store Products URL and 1?10
upload tabs through `mapper/features/kiotviet_settings.py`. `WebActions` captures
settings on the Tk thread before connecting or uploading. `WebsiteUploader`
uses Playwright CDP attachments owned by each worker thread; `run_batch` gives
concurrent Tab 7 workers separate tabs and coordinates location creation.
Browser errors stop scheduling, preserve successful item events, and never
retry an uncertain Save. Tabs 2/5 use one worker. Browser tests are in
`tests/test_playwright_upload.py`.
`WorkbookColumnDialog` maps worksheet/header/columns. `LocationComparisonView`
uses `import_excel`, `_start_comparison`, `_run_comparison`, `_poll_comparison`,
and `_render_comparison_rows` to load/compare data without blocking Tk.
`pending_updates`, `resync`, `mark_resynced`, and `export_excel` handle results.

**Shared sections:** `suggested_columns`, `read_web_locations`, `location_parts`,
`compare_locations`, and `export_comparison` in
`mapper/features/location_comparison.py` supply the data rules. `_local_locations`
uses database `get_all_placement_items` to include exception locations.
`WebActions.resync_web_locations` starts the common browser worker and reports
completion/progress back to this view. `LocationUpdate` and
`WebsiteUploader.modify_location` in `mapper/features/web_upload.py` are shared
with Tabs 2 and 5. `data_directory` supplies the export destination.

**Save boundary:** import/compare does not change local placements. Export writes
an XLSX; explicit resync changes website locations, leaving stock untouched.
Missing export IDs cannot be compared. Multi-location sets and comma/semicolon/
pipe/newline separators are supported. **Check:** matching/mismatched sets,
empty local locations, missing IDs, successful-row exclusion, and fresh-export
verification. `tests/test_multi_locations.py` covers comparison and upload sets.

## Shared files: function sections and tab consumers

A shared function can serve several tabs. The consumers below describe the
current desktop wiring, including indirect use through a wrapper. Method names
identify the relevant code section without depending on changing line numbers.

### Application and action files

| File / function section | Tabs served | Purpose |
| --- | --- | --- |
| `app.py`: `_build_ui`, `on_tab_changed`, `on_global_barcode_scan` | All tabs | Callback wiring, activation refresh, and scan routing. |
| `app.py`: `refresh_assignment_shelf_preview` | 2 | Compact shelf count updates. |
| `app.py`: `on_cell_transfer_changed` | 5; refreshes inventory consumers | Readback after switch/combine. |
| `catalog_actions.py`: `import_csv`, `import_catalog_csv` | Buttons on 1; data consumed by 2, 3, 6 | Import into the separate working/catalog stores. |
| `catalog_actions.py`: `schedule_queue_refresh`, `refresh_product_queue`, `refresh_catalog`, `refresh_search_location`, `activate_catalog_product`, `transfer_catalog_selection_to_queue` | 2 | Search, location status, catalog activation and transfers. Tab 3 has its own search handlers. |
| `assignment_actions.py`: `move_selected_to_on_hand`, `assign_on_hand_to_address`, `dequeue_selected_on_hand`, `move_address_to_on_hand`, `move_selected_address_to_on_hand`, stock/address/Shift handlers | 2 | Current address-first workflow. |
| `assignment_actions.py`: `assign_selected_products`, `refresh_slot_contents`, `transfer_selected_products`; `catalog_actions.py`: `preassign_queue_stock`, `return_selected_to_queue` | Older staged workflow | Retained methods; not the current Tab 2 button callbacks in `_build_ui`. |
| `assignment_view.py`: `StockQuantityDialog` | 2; retained staged assignment code | Per-product quantity entry. |
| `assignment_view.py`: `AssignmentView.render_shelf`, `_cell_visual`, `refresh_cell`, `mark_selected` | 4; previews produced by 1 | Shared full-size shelf renderer. Tab 2 has its own compact renderer. |
| `shelf_actions.py`: new/load/resize/preview/commit methods | 1 → 4 for preview | Shelf editor operations. |
| `shelf_actions.py`: `can_change_cells`, `has_pending_changes` | 1 and 5; app close | Prevent saved-cell changes while editor changes are pending. |
| `state_actions.py`: `remember_imported_products`, `reload_database_state`, `refresh_all_views` | App-wide caches; directly refresh 2, 6, and optionally 3 | Import/startup/exception refresh. Tabs also refresh on activation. |
| `state_actions.py`: `apply_inventory_changes`, `reconcile_inventory_products`, `refresh_visible_cells` | Writes from 2, 5; visible cells in 2, 3, 4, 5 | Narrow product readback and in-place list/cell refresh. |
| `state_actions.py`: `on_exception_data_changed` | 6 → app caches / other consumers | Exception mutation callback. |
| `web_actions.py`: `_web_placements`, `_upload_products`, `_location_updates`, `upload_selected_product`, `modify_selected_location` | 2 | Selected/all-loaded-cell browser requests. |
| `web_actions.py`: `modify_cell_transfer_locations` | 5 | Browser request for products in the selected cells. |
| `web_actions.py`: `resync_web_locations` | 7 | Browser requests from comparison results. |
| `web_actions.py`: `connect_chrome`, `_saved_location_sets`, `_start_web_update`, `_run_web_upload`, `_poll_web_upload` | Connect Chrome; 2, 5, 7 | Shared browser lifecycle, complete location sets, workers, and progress. |

### Common helpers and widgets

| File / function section | Tabs served | Purpose |
| --- | --- | --- |
| `mapper/core/common.py`: `APP_TITLE`, `application_directory`, `default_database_path` | Entire app | Window identity and database path resolution. |
| `mapper/core/common.py`: `data_directory` | App storage; 7 export | Runtime output paths. |
| `mapper/core/common.py`: `clean_location_segment` | 1, 2, 3, 4, 5, 6 through their fields/lookups/rendering | Normalize address components. |
| `mapper/core/common.py`: `make_slot_name` | 1, 2, 3, 4, 5, 6; 7 consumes saved names | One location naming rule. Do not change naming in one renderer alone. |
| `mapper/core/common.py`: `normalize_search` | 1–6 via address normalization and product search | Case/accent-insensitive normalization. Tab 7 Excel comparison has separate rules in `location_comparison.py`. |
| `mapper/core/common.py`: `MAX_VISIBLE_PRODUCTS` | 2, 3; older lookup view | Limit displayed queue/catalog results to 750. |
| `widgets.py`: `ScrollableFrame` and its scrolling methods | 1, 2, 3, 4, 5 | Row editor, quantity dialog, and shelf scroll areas. |
| `widgets.py`: `sync_tree_rows` | 2, 3, 4, 5 | Reconcile rows in place; Tab 6/7 have their own rendering paths. |
| `widgets.py`: `shelf_cell_visual` | 3, 4, 5 | Full-size cell count/color/selection styling. Tab 2 styles its compact cells separately. |
| `shelf_address_lookup.py`: `find_shelf_id`, `ShelfAddressLookup.load` / `set_address` | 3, 4, 5 | Shared Floor/Side/Shelf lookup. Tabs 2/6 use their own address fields. |
| `utils/barcode_scanner.py`: `BarcodeScanner`, `format_product_id`, `bind_auto_highlight`, `select_all_entry_text` | Main scan/search flows in 2, 3, 5, 6 | Scanner detection, ID formatting, and entry selection; app routes scans to the active view. |

### Persistence and feature functions

| File / function section | Tabs served | Purpose |
| --- | --- | --- |
| `catalog.py`: `import_products`, `import_catalog_products`, `get_display_catalog_products` | Imports on 1; transfers on 2; reads on 2, 3, 6 | Product stores and combined display names. |
| `shelves.py`: `commit_shelf`, `_sync_layout` | 1 | Save structure; other tabs read the committed result. |
| `shelves.py`: `get_shelf`, `get_slot_address`, `get_slot_contents`, `get_shelf_contents` | 1–6 through editor/view/actions | Resolve saved addresses and render contents. |
| `inventory.py`: queue/on-hand/direct/stock/revert methods | 2 | Immediate inventory changes and Shift reversal. |
| `inventory.py`: `swap_slot_contents`, `combine_slot_contents` | 5 | Atomic cell transfers. |
| `inventory.py`: `get_product_inventory_states` | Writes on 2/5 through state reconciliation | Read back only affected product state. |
| `inventory.py`: `get_product_location`, `get_placement_details`, `get_all_placement_items` | Product/shelf consumers; 7 reads all placements; 2/5 web requests read location sets | Regular and exception placement reads. |
| `exceptions.py`: lookup/assignment/staging/registration/removal methods | 6; placement consumers in 2–5 and 7 | Extra locations and independent registration targets. |
| `schema.py`, `models.py`, `database.py` | Entire app | Schema, record/validation types, and composed database facade. |
| `mapper/features/csv_import.py`: `read_csv`; `csv_dialog.py`: `ColumnMappingDialog` | 1 | CSV parsing and import column selection. |
| `mapper/features/location_comparison.py`: import/compare/export functions | 7 | Website-export data rules. |
| `mapper/features/web_upload.py`: `LocationUpdate`, `WebsiteUploader.modify_location` and connection/save helpers | 2, 5, 7 | Browser updates and verification of complete location sets. |

## State, save boundaries, and persistence

| Data/action | Save boundary |
| --- | --- |
| Shelf Designer structure and staged editor changes | Explicit **Commit shelf design** on Tab 1. Previewing alone does not save. |
| CSV imports | Database upserts during import; existing placement/stock/time are retained. |
| Tab 2 on-hand moves, quantity edits, assignments, dequeue, and Shift transfers | Saved immediately by the database operation. No Tab 1 commit is required. |
| Tab 5 switch/combine | Saved immediately after confirmation, preserving stock and original assignment timestamps. Pending designer changes must be resolved first. |
| Tab 6 exception placement and registration | Placement and CSV/catalog registration are separate operations; staged registration status tracks the remaining targets. |
| Web modification/resync | Explicit browser action; local assignment alone does not update KiotViet. |

`products` is the working product set, including assigned and on-hand products;
it is not the same as the visible unassigned queue. `catalog_products` is the
combined display catalog. Queue names take precedence over catalog names for
matching IDs, while both import stores remain separate.

`committed_placements`, `on_hand_products`, and `returned_queue_products` mirror
saved inventory state. `staged_assignments`, `pending_unassignments`, and
`transferred_stock` also support editor/staged workflows. Normal queue, on-hand,
and assigned states are distinct; Tab 6 explicitly permits multiple shelf
locations for a product.

[mapper/persistence/database.py](mapper/persistence/database.py) composes the
`WarehouseDatabase` facade from these domain files:

| File | Responsibility |
| --- | --- |
| `schema.py` | Database initialization and schema migrations. |
| `models.py` | `Placement`, `SlotAddress`, on-hand/returned records, and stock validation. |
| `catalog.py` | Working/catalog imports and the combined display catalog. |
| `shelves.py` | Shelf layouts, address resolution, cell contents, and shelf commit. |
| `inventory.py` | Queue/on-hand/placement moves, direct assignments, stock edits, switch/combine, and Shift reversal. |
| `exceptions.py` | Extra locations, exception staging, and separate CSV/catalog registration. |

For a mutation, follow the path from `_build_ui` callback to the action handler
to the database method, then check how the successful write refreshes caches
and visible widgets. Put transactional inventory changes in persistence rather
than modifying only a tree row or in-memory dictionary.

## Refreshes and shared controls

[state_actions.py](ui/desktop/state_actions.py) owns desktop cache reconciliation:

- `apply_inventory_changes` mirrors known post-write records and refreshes the
  affected lists/cells.
- `reconcile_inventory_products` reads back only affected product IDs, including
  exception placements, then applies those changes.
- `refresh_visible_cells` updates affected cells in the active tab, including
  their count, color, and selected contents.
- `reload_database_state` reloads caches; `refresh_all_views` updates widgets.
  Keep those responsibilities distinct to avoid duplicate redraws.

[widgets.py](ui/desktop/widgets.py) provides `sync_tree_rows`, `shelf_cell_visual`,
and `ScrollableFrame`. Reuse existing rows/buttons when only contents change;
rebuild a shelf when its structure changes. A partial refresh must preserve
selection, cell styling, and count text just as a full render does.

[shelf_address_lookup.py](ui/desktop/shelf_address_lookup.py) provides shared
floor/side/shelf lookup. [utils/barcode_scanner.py](utils/barcode_scanner.py)
handles scan detection, ID formatting, and entry highlighting.
[mapper/core/common.py](mapper/core/common.py) centralizes search normalization,
location naming (`make_slot_name`), and application/data paths.

## Web sync ownership

`web_actions.py` collects selected or whole-cell products and launches browser
work. `mapper/features/web_upload.py` owns Chrome connection, product identity
checks, location selection, save, and verification. `LocationUpdate` carries
the complete local location set, including exception locations; an empty set
clears the website locations. Location-only updates leave stock untouched.

Tab 7 imports and compares Excel data in background workers and polls results
back onto the Tk thread. Exported mismatches go under
`data/exports/location_comparison/`. Website exports accept comma, semicolon,
pipe, and newline separators for location sets. Local IDs missing from an
export cannot be compared/uploaded by that comparison. Import a fresh website
export to verify the result after resync.

## Verification workflow

Run from the project root using the same environment as the launcher:

```powershell
& '..\..\.venv\Scripts\python.exe' -m unittest discover -s tests -v
```

Relevant existing tests are:

| Test file | Coverage |
| --- | --- |
| `tests/test_incremental_desktop.py` | Widget reuse, changed-cell refreshes, visual state, and Tab 2 numeric count formatting. |
| `tests/test_desktop_state.py` | Cache reload and view-refresh responsibilities. |
| `tests/test_persistence.py` | Atomic moves, quantities/timestamps, reimports, and exception registration. |
| `tests/test_multi_locations.py` | Multiple-location comparison and complete website location sets. |
| `tests/test_shelf_address_lookup.py` | Floor/side/shelf address matching. |
| `tests/test_paths.py` | Legacy database path handling. |

For manual UI checks, create a separate scratch database under `tmp/` and
launch with `--db`; import sample products and commit a sample shelf there.

```powershell
New-Item -ItemType Directory -Force tmp | Out-Null
& '..\..\.venv\Scripts\python.exe' warehouse_mapper.py --db tmp/manual-check.db
```

For Tab 2, check normal selected-product moves, all three Shift shortcuts,
loaded-address validation, queue prefix rejection, the three-click timeout,
Shift release/tab changes, reversal, and unchanged stock during ordinary moves.
Compare a freshly rendered shelf with counts updated after a transfer. Queue
and catalog double-clicks should search without moving products. Restart with
the same scratch database to check on-hand persistence; the Shift-revert
snapshot should not survive restart.

The normal database is `data/warehouse_locations.db`. If legacy root databases
also exist, `default_database_path` may require explicit `--db` selection.
Close the app before copying the database for backup. Runtime data and `tmp/`
are ignored by Git; do not add local inventory or generated files to a source
change.

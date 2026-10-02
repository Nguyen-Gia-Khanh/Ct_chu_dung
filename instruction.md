# Desktop source and behavior guide

Use this file to locate the code for a requested desktop change. [README.md](README.md)
explains how to launch the app and perform warehouse workflows. The supported UI
is Tkinter; `ui/web/` and `mapper/api/` are retained as deprecated code.

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

## Tab 2: controls and transfer rules

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

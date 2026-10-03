# Graph Report - repository-graph  (2026-10-03)

## Corpus Check
- 106 files · ~77,698 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 7 file(s) not represented in the graph (top: (none) 2, .css 2, .exe 2)

## Summary
- 1208 nodes · 2787 edges · 57 communities (23 shown, 34 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 104 edges (avg confidence: 0.92)
- Token cost: unavailable for the Codex semantic pass (usage metrics are not exposed); AST extraction uses no LLM tokens. Zero counters in cost.json are placeholders, not measured usage.

## Graph Freshness
- Built from commit: `8f730edb`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Deprecated React Interface
- ICS Catalog Scraping
- Label Printing PDF
- KiotViet Browser Uploads
- Database Facade Tests
- Assignment Rendering Tests
- Cell Switch Combine
- Assignment Catalog Actions
- Barcode Search Formatting
- Location Assignment Interface
- Desktop App Shelf Designer
- Documented Warehouse Workflows
- Special Exceptions Interface
- Primal Queue Shelf Lookup
- Shared Location Naming
- Laya Name Extraction
- Excel Comparison Interface
- Persistence Models Validation
- Web Build Dependencies
- Inventory Transfer Persistence
- Exception Placement Persistence
- Multi Location Comparison
- Shelf Editing Actions
- Incremental Desktop Refresh
- TypeScript App Configuration
- Runtime Database Paths
- Shelf Address Search
- Windows Executable Launcher
- Offline Web Bundling
- Deprecated HTTP Server
- Shelf Address Persistence
- Read Only Shelf Browser
- HTTP Request Handling
- Product Placement Queries
- Shelf Address Widget
- TypeScript Build Configuration
- Catalog Application Text
- HTTP Static Files
- Product State Reconciliation
- Label Printer Entry

## God Nodes (most connected - your core abstractions)
1. `WarehouseDatabase` - 45 edges
2. `LocationAssignmentView` - 42 edges
3. `PrimalQueueView` - 38 edges
4. `CellTransferPane` - 37 edges
5. `WebsiteUploader` - 36 edges
6. `ExceptionsView` - 36 edges
7. `LocationUpdate` - 33 edges
8. `Placement` - 33 edges
9. `format_product_id()` - 33 edges
10. `WarehouseMapperApp` - 30 edges

## Surprising Connections (you probably didn't know these)
- `Desktop tab callback and scan wiring` --references--> `WarehouseMapperApp`  [EXTRACTED]
  instruction.md → ui/desktop/app.py
- `Complete location-set web update` --references--> `LocationUpdate`  [EXTRACTED]
  instruction.md → mapper/features/web_upload.py
- `Complete location-set web update` --references--> `WebsiteUploader`  [EXTRACTED]
  instruction.md → mapper/features/web_upload.py
- `WarehouseDatabase persistence facade` --references--> `WarehouseDatabase`  [EXTRACTED]
  instruction.md → mapper/persistence/database.py
- `Incremental cache and widget refresh` --references--> `StateActions`  [EXTRACTED]
  instruction.md → ui/desktop/state_actions.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Shared browser worker and complete location sets across Tabs 2, 5, and 7** — readme_assign_locations, readme_switch_combine_cells, readme_web_location_sync, instruction_location_update [EXTRACTED 1.00]
- **Inventory mutations reconcile affected products and shelf cells** — readme_assign_locations, readme_primal_queue_shelves, readme_browse_shelves, readme_switch_combine_cells, instruction_incremental_refresh [EXTRACTED 1.00]
- **Separate queue, on-hand, and assigned states with explicit multi-location exceptions** — readme_inventory_states, readme_assign_locations, readme_primal_queue_shelves, readme_special_exceptions [EXTRACTED 1.00]

## Communities (57 total, 34 thin omitted)

### Community 0 - "Deprecated React Interface"
Cohesion: 0.06
Nodes (64): react, react-dom, App(), screens, ColumnMappingDialog(), ColumnMappingDialogProps, NavbarProps, ShelfCanvas() (+56 more)

### Community 1 - "ICS Catalog Scraping"
Cohesion: 0.06
Nodes (50): absolute_url(), dedupe_by_url(), discover_catalog_pages(), discover_figure_pages(), discover_model_pages(), discover_with_retries(), error_record(), extract_catalog_model_codes() (+42 more)

### Community 2 - "Label Printing PDF"
Cohesion: 0.06
Nodes (21): cells_for_printing(), LabelDatabase, LabelPrinterApp, _location_key(), _pdf_created_at(), PrintedPdfHit, scan_printed_pdfs(), Shelf (+13 more)

### Community 3 - "KiotViet Browser Uploads"
Cohesion: 0.09
Nodes (8): _location_ids(), LocationUpdate, UploadError, UploadProduct, WaitExpired, WebsiteUploader, WebSelectionTests, WebActions

### Community 4 - "Database Facade Tests"
Cohesion: 0.06
Nodes (9): ReadRoutes, WriteRoutes, CatalogOperations, WarehouseDatabase, WorkspaceTestCase, MultiLocationTests, DatabasePathTests, PersistenceTests (+1 more)

### Community 5 - "Assignment Rendering Tests"
Cohesion: 0.06
Nodes (5): Button, IncrementalDesktopTests, Tree, AssignmentView, ProductLookupView

### Community 7 - "Assignment Catalog Actions"
Cohesion: 0.06
Nodes (6): CSVData, read_csv(), AssignmentActions, StockQuantityDialog, CatalogActions, ColumnMappingDialog

### Community 8 - "Barcode Search Formatting"
Cohesion: 0.11
Nodes (8): normalize_search(), shelf_cell_visual(), sync_tree_rows(), BarcodeScanner, bind_auto_highlight(), format_product_id(), process_entry_return(), select_all_entry_text()

### Community 10 - "Desktop App Shelf Designer"
Cohesion: 0.07
Nodes (3): WarehouseMapperApp, ShelfDesigner, ScrollableFrame

### Community 11 - "Documented Warehouse Workflows"
Cohesion: 0.07
Nodes (19): data/warehouse_locations.db, Desktop source and behavior guide, Existing warehouse verification suite, Complete location-set web update, WarehouseDatabase persistence facade, Assign Locations, Browse Shelves, Primal Queue / Shelves (+11 more)

### Community 14 - "Shared Location Naming"
Cohesion: 0.11
Nodes (3): _get_database(), _get_uploader(), make_slot_name()

### Community 15 - "Laya Name Extraction"
Cohesion: 0.13
Nodes (24): parse_paths(), classify_air(), extract_models(), find_model_mentions(), get_laya_agent(), main(), normalize_text(), overlaps() (+16 more)

### Community 16 - "Excel Comparison Interface"
Cohesion: 0.12
Nodes (4): _plain_header(), suggested_columns(), LocationComparisonView, WorkbookColumnDialog

### Community 17 - "Persistence Models Validation"
Cohesion: 0.14
Nodes (5): LayoutConflictError, OnHandProduct, ProductLocation, validate_stock_quantity(), SchemaOperations

### Community 18 - "Web Build Dependencies"
Cohesion: 0.08
Nodes (25): @types/react, @types/react-dom, typescript, vite, @vitejs/plugin-react, dependencies, react, react-dom (+17 more)

### Community 21 - "Multi Location Comparison"
Cohesion: 0.19
Nodes (5): compare_locations(), export_comparison(), location_parts(), LocationDifference, read_web_locations()

### Community 24 - "TypeScript App Configuration"
Cohesion: 0.11
Nodes (17): compilerOptions, allowImportingTsExtensions, isolatedModules, jsx, lib, module, moduleResolution, noEmit (+9 more)

### Community 25 - "Runtime Database Paths"
Cohesion: 0.17
Nodes (6): application_directory(), data_directory(), default_database_path(), resolve_output_dir(), main(), main()

### Community 26 - "Shelf Address Search"
Cohesion: 0.15
Nodes (3): clean_location_segment(), ShelfAddressLookupTests, find_shelf_id()

### Community 27 - "Windows Executable Launcher"
Cohesion: 0.18
Nodes (5): collect_available(), keep_output(), path_exists(), show_error(), wWinMain()

### Community 28 - "Offline Web Bundling"
Cohesion: 0.15
Nodes (10): addModule(), compiler, dependencies, distRoot, factories, modules, resolveImport(), srcRoot (+2 more)

### Community 29 - "Deprecated HTTP Server"
Cohesion: 0.19
Nodes (5): configure_database(), _is_port_in_use(), _launch_app_mode(), run_desktop_app(), run_server()

### Community 36 - "TypeScript Build Configuration"
Cohesion: 0.25
Nodes (7): compilerOptions, allowSyntheticDefaultImports, composite, module, moduleResolution, skipLibCheck, include

## Knowledge Gaps
- **63 isolated node(s):** `name`, `version`, `private`, `description`, `type` (+58 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 379 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **34 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `WarehouseDatabase` connect `Database Facade Tests` to `Desktop Controller Dependencies`, `Assignment Rendering Tests`, `Cell Switch Combine`, `Barcode Search Formatting`, `Desktop App Shelf Designer`, `Documented Warehouse Workflows`, `Special Exceptions Interface`, `Primal Queue Shelf Lookup`, `Shared Location Naming`, `Excel Comparison Interface`, `Persistence Models Validation`, `Inventory Transfer Persistence`, `Exception Placement Persistence`, `Multi Location Comparison`, `Shelf Address Persistence`, `Read Only Shelf Browser`?**
  _High betweenness centrality (0.119) - this node is a cross-community bridge._
- **Why does `WarehouseMapperApp` connect `Desktop App Shelf Designer` to `Desktop Controller Dependencies`, `KiotViet Browser Uploads`, `Database Facade Tests`, `Cell Switch Combine`, `Assignment Catalog Actions`, `Barcode Search Formatting`, `Location Assignment Interface`, `Documented Warehouse Workflows`, `Special Exceptions Interface`, `Primal Queue Shelf Lookup`, `Excel Comparison Interface`, `Shelf Editing Actions`, `Incremental Desktop Refresh`, `Runtime Database Paths`, `Read Only Shelf Browser`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Why does `InventoryOperations` connect `Inventory Transfer Persistence` to `Product Placement Queries`, `Database Facade Tests`, `On Hand Queue Return`, `Product State Reconciliation`, `Persistence Models Validation`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Are the 11 inferred relationships involving `WarehouseDatabase` (e.g. with `MultiLocationTests` and `PersistenceTests`) actually correct?**
  _`WarehouseDatabase` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `LocationAssignmentView` (e.g. with `IncrementalDesktopTests` and `WarehouseMapperApp`) actually correct?**
  _`LocationAssignmentView` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `PrimalQueueView` (e.g. with `IncrementalDesktopTests` and `WarehouseMapperApp`) actually correct?**
  _`PrimalQueueView` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `CellTransferPane` (e.g. with `IncrementalDesktopTests` and `WarehouseDatabase`) actually correct?**
  _`CellTransferPane` has 5 INFERRED edges - model-reasoned connections that need verification._
## Graph Health

- dangling_endpoint_edges: 205
- self_loop_edges: 17
- undirected_same_endpoint_collapsed_edges: 41

This is the default undirected graph. Multiple extracted relationships between the same endpoints can collapse into a single exported edge; edge directions are not preserved. See health.json for the complete diagnostic counts.

## Build Provenance

- Graphify 0.9.74; code and documentation from `8f730edbff5edf50150ca0840865fd10fd317eee` (local main at build start).
- Uncommitted changes and other feature worktrees were excluded.

## Verification

- Exported graph: unique node IDs, valid endpoints for every edge, named communities, and relative source paths.
- Incremental manifest: all 106 files recorded, including semantic hashes for all five documentation files.
- Navigation smoke check: `WarehouseDatabase` reaches `StateActions` through `ui/desktop/app.py` in two undirected hops.
- HTML contains graph data and interactive network initialization; rendering was not tested in a browser. The visualization library loads from the unpkg CDN and requires internet access.
- Graphify benchmark estimates 5.5x fewer tokens per query (14,624 average versus 80,533 naive); this is an estimate rather than measured LLM billing.

# Warehouse Shelf Mapper - TypeScript UI

A modern, responsive React + TypeScript user interface for the Warehouse Shelf Mapper system. Located at `/ui`, this application can run as a web dashboard or be embedded into a desktop wrapper (such as Tauri or Electron).

---

## Features & Navigation

The application follows the six tabs of the Tkinter warehouse mapping workflow:

### 1. Tab 1: Shelf Designer (`ShelfDesignerView.tsx`)
- Configure warehouse physical shelf metadata: Floor (`L1`, `L2`, ...), Side (`1`, `2`), Shelf Code (`A`, `B`, ...), Row count, and default columns per row.
- **Per-Row Customizer**: Configure different column counts for specific shelf levels.
- **2D Front-View Preview**: Real-time visualization of the shelf grid with ground-up row inversion (Row 1 is at ground level, highest row on top; columns from left to right).
- Save shelf definitions to the database.

### 2. Tab 2: Assign Locations (`LocationAssignmentView.tsx`)
- **Product Lists**:
  - **Pending Queue**: Unassigned items or items imported from CSV.
  - **Full Catalog**: Complete product catalog with a database join to display existing `loc_id` placements (with short name dropped per requirements).
  - **Work Batch Queue**: Select items to stage for assignment.
- **Target Address Builder**:
  - Direct selector for Floor, Side, Shelf, Row, and Column.
  - Automatic Location ID generator (e.g., `L1-1A8-10`).
  - Quick jump / manual input field with parser.
- **Stock Quantity Assignment**: Modal dialog (`StockQuantityDialog`) to assign exact stock quantities per unit.
- **Direct Move**: Reposition items already placed in the catalog directly to new locations.
- **KiotViet Web Sync**: Checkbox toggle for automated web upload.
- **CSV Imports**: Built-in support for importing new inventory and returned stock with interactive column auto-mapping (`ColumnMappingDialog`).

### 3. Tab 3: Primal Queue / Shelves (`PrimalQueueView.tsx`)
- Combines hot-seller queue and catalog search with a live 2D shelf viewer.
- **Smart Barcode Search**: Auto-formats 11-digit barcode scans into standard 5-3-3 IDs (`06410KFL850` -> `06410-KFL-850`).
- **Auto-Clear / Focus Selection**: Auto-cleans search input on focus for fast continuous barcode scanning.
- **Auto-Jump to Shelf**: Selecting or scanning a placed product automatically loads its shelf and highlights its cell.
- **Cell Occupancy Badges**: Color-coded cells showing occupancy count and cell contents list.

### 4. Tab 4: Browse Shelves (`ShelfBrowserView.tsx`)
- Select any configured warehouse shelf from a dropdown.
- Front-view 2D interactive canvas showing occupied vs empty cells.
- Inspect cell contents: product codes, names, barcodes, quantities, and placement timestamps.
- Warehouse shelf capacity and occupancy statistics.

### 5. Tab 5: Switch / Combine Cells (`CellTransferView.tsx`)
- **Dual-Shelf Workspace**: Side-by-side view of Source Shelf A and Destination Shelf B.
- **Product Quick Jump**: Search or scan a product ID to automatically select its current cell on Shelf A (with auto-focus wipe).
- **Atomic Operations**:
  - **Switch Cells**: Swaps all contents between Cell A and Cell B atomically.
  - **Combine Cells**: Merges all contents from Cell A into Cell B.

---

### 6. Tab 6: Special Exceptions (`ExceptionsView.tsx`)
- Assign an unregistered or multi-location product to an existing cell.
- Inspect the shared on-hand batch and stage catalog CSV updates.

---

## UI Structure

- `src/App.tsx` selects and retains visited tabs; `components/WorkbenchChrome.tsx` renders the shared Tkinter-style frame.
- `src/views/` contains screen markup, tables, forms, and reusable shelf visuals.
- `src/controllers/` owns screen state, selection, refresh, and event handlers.
- `src/services/api.ts` calls the local Python API; `backendStatus.ts` reports availability.
- `src/utils/` contains location/barcode helpers and CSV parsing.
- `scripts/build-offline.mjs` compiles the TypeScript UI into `dist/app.js` using the local build compiler.

---

## Getting Started

### Prerequisites
- Node.js 18+ and npm (or pnpm / yarn)

### Installation
```bash
cd ui
npm install
```

### Running Development Server
```bash
npm run dev
```
The Vite server starts at `http://localhost:3000` and proxies `/api` to the local Python server on port 8000. The UI uses the SQLite-backed Python API; it does not substitute demo records when the backend is unavailable.

### Production Build
```bash
npm run build
```
The checked TypeScript source is compiled to `ui/dist/app.js` and served by `mapper/web_server.py`. The desktop page loads local React files and the prebuilt bundle, with no browser-time Babel compilation or network font dependency. If dependencies are not installed, `node scripts/build-offline.mjs` builds the same bundle using the checked-in Babel compiler.

`src/views/` contains presentation, `src/controllers/` contains screen state and event handling, and `src/services/` owns backend calls and connection status. The Python database and other functional modules are unchanged.

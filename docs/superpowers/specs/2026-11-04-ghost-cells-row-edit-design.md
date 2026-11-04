# Ghost cells and middle-row insert/remove — design

Date: 2026-11-04. Branch: `feature/ghost-cells-row-edit`. Desktop (Tkinter) only.

## Why

Tab 1 refuses to commit a layout that removes a cell or row still holding
products, and says so in a popup. When reshaping a shelf (for example: shrink
Row 2, widen Row 3, then move a block of products up in Tab 5), the new design
cannot be saved first, and the user loses track of the planned cell counts.
Tab 1 can also only add or remove rows at the top, so making room in the
middle means shifting every upper row by hand in Tab 5.

## What the user gets

1. **Ghost cells.** Committing a layout that removes occupied cells or rows
   always succeeds. Removed cells that still hold products become *ghost cells*:
   they keep their products and stock and are drawn red on every shelf canvas
   until emptied.
2. **Red warning line in Tab 1** instead of popups for occupied removals.
3. **Insert a row anywhere** with a draggable insert bar; rows above it move up
   by 1 together with their products.
4. **Remove any row** with a per-row ✕ button; rows above it move down by 1
   together with their products. A removed row that still holds products becomes
   a ghost row above the top row.

## Terms

- **Designed width** `W` of a row: the number of cells the design gives it.
- **Position** `p`: a cell's left-to-right place in its row, 1-based.
- **Ghost cell**: a saved cell that is no longer part of the design. Ghost cells
  of a designed row sit at positions `p > W`. A **ghost row** is a row above
  `shelves.row_count`; all its cells are ghosts.
- **Spacer ghost**: an empty ghost cell kept so that a ghost further right stays
  at its physical position.
- **Occupied**: the cell has a primary placement or an exception placement.
- **Visible ghosts**: ghost cells at or left of the last occupied ghost in their row.

## Rules

### R1 — Which removed cells become ghosts

On Commit, for every row of the new layout (and every leftover row, see R3):
let `G` be the highest position among *removed* cells (`p > W`) that are
occupied. Removed cells with `p <= G` become ghost cells (occupied or spacer).
Removed cells with `p > G` are deleted; they are empty by construction.
Empty removed cells are therefore deleted exactly as today when nothing
further right is occupied.

Example: Row 2 goes 10 → 8 and only cell 10 is occupied → cells 9 (spacer) and
10 stay as ghosts; Tab 5 moving the block up lands cell 10 at position 10 of
Row 3.

### R2 — Ghost cell numbers and names

- A ghost's `slot_number` equals its position `p` (left to right).
- Non-reversed rows: real cell numbers equal positions, so a ghost keeps its
  number and location ID.
- Reverse-location-ID rows: leftover numbers would clash with the renumbered
  row, so ghosts are renumbered to their position (e.g. 9, 10, drawn right of
  cell 1). Reversed rows already renumber whenever their width changes.
- Names come from `make_slot_name(floor, shelf_code, row, number, side=side)`.
- Real cells keep `number = shelf_cell_number(p, W, reverse)` as today.

### R3 — Row moves, removed rows and ghost rows

Tab 1 records, for each editor row, which saved row it came from
(`row_origins`, see "Tab 1" below). On Commit:

- A kept saved row moves to its new row number with all its cells, products and
  ghosts. Location IDs (and Tab 6 staged names) follow the new row number,
  e.g. `L1-1A3-5` → `L1-1A4-5`.
- **Leftover rows** are saved rows that were removed in the editor plus existing
  ghost rows. Leftover rows with at least one occupied cell are stacked directly
  above the new top row in their old row order: new row numbers
  `len(layout)+1, len(layout)+2, …`. All their cells are ghost candidates
  (`W = 0`), so R1 keeps positions `1..G`. Leftover rows with no occupied cell
  are deleted.
- `shelves.row_count = len(layout)` (designed rows only).

### R4 — Ghosts turn back into normal cells

If a later commit makes a designed row wide enough to include a ghost's
position, that cell becomes a normal cell again: it is removed from
`ghost_slots` and renamed by the normal rule. No new cell is created where an
old ghost already covers the position. Ghost rows never become designed rows
again: they always sit above the top row (adding a row at the top pushes them
up by one), and their products are moved back down in Tab 5.

### R5 — Nothing goes *into* a ghost cell

These are refused with `GhostCellError` (a `ValueError` subclass) and nothing changes:

- `assign_on_hand_to_slot`, `assign_catalog_direct_to_slot` (Tab 2 queue,
  catalog and on-hand buttons), `assign_exception` (Tab 6);
- `combine_slot_contents` when the target is a ghost;
- `swap_slot_contents` when a ghost would receive products (switching a full
  ghost with an empty normal cell is allowed — that empties the ghost);
- `shift_slot_contents` when an occupied source's target is a ghost
  (Tab 5 block move and block switch);
- `commit_shelf` staged placements into a ghost (legacy path).

Taking products out of a ghost works through every existing path.
`revert_shift_transfer` (one-step undo) is not guarded: it restores products to
where they were, which may be a ghost.

### R6 — Ghosts vanish once empty (lazy cleanup)

- Views show only visible ghosts, so an emptied ghost (with nothing occupied to
  its right) disappears on the next refresh of that shelf.
- The emptied ghost's database rows stay until that shelf's next Commit,
  which deletes them through R1. Address lookups (`get_slot_address`,
  `get_slot_by_name`) still resolve them; assigning to them is refused by R5.

## Data model

New table, created by `create_schema` on startup (`CREATE TABLE IF NOT EXISTS`);
no migration script, `SCHEMA_VERSION` stays 5:

```sql
CREATE TABLE IF NOT EXISTS ghost_slots (
    slot_id INTEGER NOT NULL PRIMARY KEY REFERENCES slots(slot_id) ON DELETE CASCADE
);
```

Older app copies ignore the table and show ghost cells as normal cells. The
cleanup migration only lists tables, so it is unaffected.

## Components

### Layout planner — `mapper/services/layout_plan.py` (new, pure)

One function plans where every saved cell ends up. Both the Tab 4 preview and
`sync_layout` use it, so the preview always matches what Commit saves.

Input: saved cells as `(slot_id, row, position, ghost, occupied)`, the saved row
count, `row_origins: list[int | None]`, the new `layout`, floor, side, shelf
code and the reverse flag. `row_origins=None` means today's behavior: rows
`1..min(old, new)` keep their numbers; rows are added or removed at the top.

Output (`LayoutPlan`): for each kept saved cell its new
`(row, slot_number, slot_name, ghost)`; the slot ids to delete; the new cells to
create `(row, slot_number, slot_name)`; and helpers for the old-name → new-name
map and the occupied ghost list used by the Tab 1 warning.

Validation (`ValueError`): `row_origins` has `len(layout)` entries; the non-None
entries are strictly increasing and each lies in `1..old_row_count`.

### Persistence — `mapper/persistence/`

- `schema.py`: add `ghost_slots`.
- `models.py`: `GhostCellError(ValueError)`; `SlotAddress` gains `ghost: bool = False`
  (filled by `SLOT_ADDRESS_SQL`). Export through `database.py`.
- `shelves.py`:
  - `sync_layout` reads saved slots, ghost flags and occupancy, computes each
    cell's position (real: `shelf_cell_number(number, W_real, previous_reverse)`
    where `W_real` counts non-ghost cells; ghost: `number`), calls the planner,
    then applies it: delete, rename, update `ghost_slots`, insert new cells,
    update `row_count` / `revert_location_id`.
  - `rename_slots` also updates `row_number` (rows can now move). It keeps the
    temporary-name step so swaps and Tab 6 staged names stay consistent.
  - `commit_shelf(..., row_origins=None)` passes `row_origins` to `sync_layout`;
    `_place_staged` refuses ghost targets.
  - `get_shelf` counts only non-ghost cells (signature unchanged).
  - New `get_shelf_ghosts(shelf_id) -> list[(row_number, slot_number, slot_name)]`
    returns visible ghosts only (R6).
- `shared.py`: `refuse_ghost_targets(connection, slot_ids)` raises
  `GhostCellError` naming the first ghost: "L1-1A2-10 is a ghost cell (removed
  from the shelf design). Move its products out; nothing can be added to it."
- `inventory.py`, `exceptions.py`: call it in the R5 paths.

### Grid model — `mapper/services/shelf_grid.py`

- `GridCell` gains `ghost: bool = False`.
- `build_grid(..., ghosts=())` takes `(row, number, slot_name)` entries. Ghost
  cells of designed rows are appended after the real cells in position order;
  ghost rows are drawn above the top row (a ghost row with nothing visible is
  drawn as an empty row when a higher ghost row is visible).
- `ShelfGrid.layout` keeps meaning the designed layout; ghost cells are exposed
  separately (`ShelfGrid.ghosts`). Tab 4's summary, Tab 5's row selector and the
  RPC keep using the designed layout.
- `load_grid` passes `db.get_shelf_ghosts(shelf_id)`.
- `cell_color(..., ghost=False)`: occupied ghost `GHOST_COLOR` (solid red,
  readable dark text), spacer ghost `GHOST_SPACER_COLOR` (pale red).
- `next_cell` skips ghost cells.
- `plan_block_shift`: ghost cells can be sources; an occupied source whose
  target is a ghost is reported in a new `BlockShift.ghosts` field and the move
  is refused.

### Canvas — `ui/desktop/widgets.py` `ShelfGridCanvas`

- Ghost cells: ghost fill, "⚠ " before the label. A selected ghost keeps its red
  fill and gets the usual thick blue outline. Drag-marked cells keep
  `MARKED_COLOR`.
- The redraw key includes the visible ghost names, so ghosts appearing or
  vanishing trigger a full redraw.
- Views that update one cell in place (`set_count` paths in Tabs 2, 4, 5)
  reload the shelf grid when the changed cell is a ghost, so an emptied ghost
  vanishes right away.

## Tab behavior

### Tab 1 — Shelf Designer (`designer.py`, `shelf_actions.py`)

- **Row origins.** `ShelfDesigner` keeps `row_origins` beside `row_inputs`
  (bottom first). Loading a saved shelf sets `[1..n]`; a new shelf uses `None`
  for every row. Adding at the top (row-count box) appends `None`; lowering it
  pops from the top. `_editor_state` includes `row_origins`, so an insert or
  remove counts as a pending change. After Commit, origins reset to `[1..n]`.
- **Insert bar.** A blue bar with a ▶ arrow sits in a gap of the row list
  (gap `k` = between Row `k` and Row `k+1`; gap `n` = above the top; gap `0` =
  below Row 1, which makes the new row the ground row). It starts at the top gap. Dragging it with the mouse snaps it to the nearest gap. **Insert row
  at bar** (replaces "Add row at top") inserts a 4-cell row there with origin
  `None`; the bar then sits above the new row.
- **✕ per row.** Removes that row (its origin is dropped) and drops the rows
  above by 1. It replaces "Remove top row". Disabled when only one row is left.
- **Labels.** "Row 4 (was 3)" when a saved row's number changed; "Row 3 (new)"
  for an inserted row of a saved shelf; Row 1 keeps "— ground".
- **Red warning line** (no popup) under the row buttons, dark red text, wraps.
  Built from the planner's occupied ghosts, grouped by new row, e.g.
  "⚠ Ghost cells still hold products: Row 2 cells 9–10; Row 6 (was Row 3)
  cells 1–5. They stay red on every shelf view until you move the products
  out." Updates shortly after any row edit (debounced cell-count edits, insert,
  ✕, row-count changes), shows on load when the shelf already has ghosts, and
  hides when there are none. Invalid input (non-number) leaves it unchanged.
- **Popups removed:** `can_resize_rows` / `_slots_are_empty` no longer refuse
  occupied removals. Other validation popups (missing floor, invalid numbers,
  duplicate shelf) stay.
- **Preview and Commit.** `build_shelf_preview` uses the planner with the
  working occupancy (committed locations minus pending removals plus staged
  assignments). It renames the working location caches from the saved names via
  the plan, not by chaining from the previous preview. `commit_changes` passes
  `row_origins`; the existing "Commit complete" message adds
  "Ghost cells kept: N" when N > 0.

### Tab 2 — Assign Locations

- Ghost cells are drawn red/pale red with ⚠ and can be clicked and loaded.
  Loading one sets the status bar to "Ghost cell — move these products out;
  nothing can be added here." Return-to-on-hand works.
- The queue, catalog and on-hand assign buttons on a loaded ghost cell play
  `play_error_sound`, show the reason in the status bar, and move nothing. The
  check uses the loaded `SlotAddress.ghost` before the click-count logic, and
  the database guard backs it up.
- Right-click "next cell" skips ghost cells.

### Tab 3 and Tab 4

Their canvases show ghosts through `load_grid`. Tab 4's summary adds
"· N ghost cells" when any are visible. The Tab 4 preview shows planned ghosts.

### Tab 5 — Switch / Combine Cells

Ghost cells can be selected, switched with an empty cell, combined into a
normal cell, and moved as part of a dragged block. Any move that would put
products into a ghost plays the error sound, shows the reason in the status
bar, and moves nothing (no popup). Block switch is covered by the same
database guard.

### Tab 6 — Special Exceptions

No canvas. Assigning an exception to a ghost address is refused with the error
sound and a status message.

## Out of scope

- Tauri UI (`ui/tauri`, on hold). `mapper/rpc` keeps working; Tauri shows ghost
  cells as plain cells.
- Tab 7: products in ghost cells sync like any other location.
- Dragging rows to reorder them; the bar only marks where to insert.
- Automatically moving ghost products anywhere.

## Testing

New `tests/test_ghost_cells.py` (planner, persistence, grid) and
`tests/test_tab1_row_edit.py` (Tk designer):

- Planner: lower width with spacer tail; nothing occupied → plain delete;
  reversed rows renumber ghosts; leftover rows stack above the top in old order;
  insert in the middle bumps rows and products; remove in the middle drops rows;
  ghost turns normal when widened; `row_origins` validation; `None` origins match
  today's behavior.
- Persistence: commit keeps ghosts and products; `get_shelf` ignores ghosts;
  every R5 path raises `GhostCellError` and changes nothing; swapping a full
  ghost with an empty cell is allowed; emptied ghosts are hidden by
  `get_shelf_ghosts` and deleted at the next commit; row moves rename products
  and Tab 6 staged names.
- Grid/canvas: ghost colors and ⚠ label; selected ghost keeps red fill;
  `next_cell` skips ghosts; `plan_block_shift` moves ghosts up and refuses ghost
  targets; redraw when ghosts change.
- Tab 1: insert bar snaps to gaps; Insert row at bar; ✕ removal; "was" labels;
  red line text, live update and hiding; no popup for occupied removals.
- Existing tests for the touched areas while working (`test_persistence`,
  `test_shelf_direction`, `test_tab5_block_shift`, `test_shelf_next_cell`,
  `test_incremental_desktop`, `test_designer_resources`, `test_shelf_deletion`,
  `test_rpc`, `test_tab2_*`, `test_cell_transfer`), then the full suite once at
  the end.

## Docs

README (Tab 1, ghost cells) and instruction.md (Tab 1 section, shelf display
conventions, persistence notes, file map for `layout_plan.py`).

## Risks to check during planning

- Tab 1's working caches are currently renamed by chaining preview to preview;
  switching to saved-name → planned-name needs care so repeated previews stay
  correct.
- `mapper/rpc/api.py` serializes `grid.rows`; the new `GridCell.ghost` field
  must not break `test_rpc`.
- Every `set_count` caller must reload the grid for ghost cells, or an emptied
  ghost lingers until the next full refresh.

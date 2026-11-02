"""Front view of a shelf: rows top-down, cells in walking order, with product counts.

Layouts are stored from the ground up (index 0 is Row 1). The saved shelf setting
controls cell ID direction independently of its side. Both UIs use this model.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from mapper.core.common import shelf_prefix

EMPTY_COLOR = "#f7f7f7"
FILLED_COLOR = "#d9ead3"
STAGED_COLOR = "#fff2b2"
SELECTED_COLOR = "#cfe8ff"


@dataclass(frozen=True)
class GridCell:
    row: int
    cell: int
    slot_name: str
    count: int


@dataclass(frozen=True)
class ShelfGrid:
    floor: str
    side: str
    shelf_code: str
    rows: tuple[tuple[GridCell, ...], ...]   # screen order: top row first
    revert_location_id: bool = False

    @property
    def key(self) -> tuple[str, str, str]:
        return self.floor, self.side, self.shelf_code

    @property
    def layout(self) -> tuple[int, ...]:
        """Cells per row from the ground up, i.e. the stored layout."""
        return tuple(len(row) for row in reversed(self.rows))

    def cells(self) -> Iterable[GridCell]:
        return (cell for row in self.rows for cell in row)


def next_cell(grid: ShelfGrid, current: GridCell | None) -> GridCell | None:
    """The cell after `current` in ascending cell ID order, whatever side it is drawn on:
    the next cell in its row, or cell 1 of the next row up when the row ends.
    With nothing selected it is Row 1's first cell; after the top row's last cell, None."""
    by_position = {(cell.row, cell.cell): cell for cell in grid.cells()}
    row, cell = (1, 0) if current is None else (current.row, current.cell)
    if (row, cell + 1) in by_position:
        return by_position[row, cell + 1]
    return next((by_position[upper, 1] for upper in range(row + 1, len(grid.rows) + 1)
                 if (upper, 1) in by_position), None)


@dataclass(frozen=True)
class BlockShift:
    moves: dict[str, str]          # occupied source cell -> target cell
    selection: tuple[str, ...]     # where the selected cells land, for the next press
    missing: tuple[str, ...]       # occupied cells whose target is off the shelf
    blocked: tuple[str, ...]       # occupied targets that are not moving out of the way


def plan_block_shift(grid: ShelfGrid, selected: Iterable[str], rows_up: int, cells_right: int) -> BlockShift:
    """Move selected cells by screen direction: up raises the row number, right follows the drawing.

    A cell keeps its left-to-right position in the new row. Empty cells carry nothing,
    so they never block a move even when their target is off the shelf.
    """
    chosen = set(selected)
    by_position = {(cell.row, column): cell for row in grid.rows for column, cell in enumerate(row, 1)}
    moves, landing, missing = {}, [], []
    for (row, column), cell in by_position.items():
        if cell.slot_name not in chosen:
            continue
        target = by_position.get((row + rows_up, column + cells_right))
        if target is not None:
            landing.append(target.slot_name)
        if cell.count:
            if target is None:
                missing.append(cell.slot_name)
            else:
                moves[cell.slot_name] = target.slot_name
    counts = {cell.slot_name: cell.count for cell in by_position.values()}
    blocked = tuple(target for target in moves.values() if counts[target] and target not in moves)
    return BlockShift(moves, tuple(landing), tuple(missing), blocked)


def cell_color(count: int, *, staged: bool = False, selected: bool = False) -> str:
    if selected:
        return SELECTED_COLOR
    return STAGED_COLOR if staged else FILLED_COLOR if count else EMPTY_COLOR


def build_grid(floor: str, side: str, shelf_code: str, layout: list[int],
               slot_names: Iterable[str] = (), *, revert_location_id: bool = False) -> ShelfGrid:
    """slot_names holds one entry per product location (e.g. from get_shelf_contents)."""
    counts = Counter(slot_names)
    prefix = shelf_prefix(floor, shelf_code, side=side)
    rows = []
    for row_number in range(len(layout), 0, -1):
        width = layout[row_number - 1]
        cells = []
        for cell in (range(width, 0, -1) if revert_location_id else range(1, width + 1)):
            name = f"{prefix}{row_number}-{cell}"
            cells.append(GridCell(row_number, cell, name, counts.get(name, 0)))
        rows.append(tuple(cells))
    return ShelfGrid(floor, side, shelf_code, tuple(rows), revert_location_id)


def load_grid(db, shelf_id: int) -> tuple[ShelfGrid, list]:
    """The saved shelf's grid and its contents rows (product_id, name, Placement)."""
    floor, side, shelf_code, layout = db.get_shelf(shelf_id)
    contents = db.get_shelf_contents(shelf_id)
    return build_grid(floor, side, shelf_code, layout, (placement.slot_name for _, _, placement in contents),
                      revert_location_id=db.get_shelf_revert_location_id(shelf_id)), contents

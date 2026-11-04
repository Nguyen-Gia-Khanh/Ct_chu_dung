"""Plan a shelf layout change: where each saved cell goes and which cells become ghosts.

A position counts left to right from 1. Real cells take their number from
shelf_cell_number; a ghost cell's number is its position. Removed cells up to the
last one still holding products stay as ghost cells, so every ghost keeps its
physical spot. Saved rows the editor dropped (and older ghost rows) that still hold
products are stacked above the new top row in their old order.

Both the Tab 1 preview and the database commit use this one plan.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from mapper.core.common import make_slot_name, shelf_cell_number


@dataclass(frozen=True)
class SavedCell:
    key: int              # slot_id in the database
    row: int
    position: int
    ghost: bool = False
    occupied: bool = False
    name: str = ""        # saved location ID


@dataclass(frozen=True)
class PlannedCell:
    row: int
    position: int
    number: int
    name: str
    ghost: bool = False
    occupied: bool = False


@dataclass(frozen=True)
class LayoutPlan:
    kept: dict[int, PlannedCell]       # saved cell key -> where it ends up
    deleted: frozenset[int]            # saved cells that go away (always empty)
    created: tuple[PlannedCell, ...]   # cells the new layout adds
    row_sources: dict[int, int]        # new row -> saved row it came from

    @property
    def ghosts(self) -> list[PlannedCell]:
        return sorted((cell for cell in self.kept.values() if cell.ghost), key=lambda c: (c.row, c.position))


def _number_ranges(numbers: Iterable[int]) -> str:
    """[8, 10] -> "8, 10"; [1, 2, 3] -> "1\u20133"."""
    numbers = sorted(numbers)
    parts, start = [], None
    for index, number in enumerate(numbers):
        start = number if start is None else start
        if index + 1 == len(numbers) or numbers[index + 1] != number + 1:
            parts.append(str(number) if start == number else f"{start}\u2013{number}")
            start = None
    return ", ".join(parts)


def ghost_warning(plan: LayoutPlan) -> str:
    """Tab 1's red line: ghost cells that still hold products, by row (spacers left out)."""
    by_row: dict[int, list[int]] = defaultdict(list)
    for cell in plan.ghosts:
        if cell.occupied:
            by_row[cell.row].append(cell.number)
    if not by_row:
        return ""
    parts = []
    for row, numbers in sorted(by_row.items()):
        source = plan.row_sources.get(row)
        was = f" (was Row {source})" if source not in (None, row) else ""
        parts.append(f"Row {row}{was} {'cell' if len(numbers) == 1 else 'cells'} {_number_ranges(numbers)}")
    return ("\u26a0 Ghost cells still hold products: " + "; ".join(parts)
            + ". They stay red on every shelf view until you move the products out.")


def default_row_origins(saved_row_count: int, row_count: int) -> list[int | None]:
    """Rows keep their numbers; rows are added or removed at the top."""
    return [row if row <= saved_row_count else None for row in range(1, row_count + 1)]


def _check_origins(origins: Sequence[int | None], saved_row_count: int, row_count: int) -> None:
    if len(origins) != row_count:
        raise ValueError("Each shelf row needs one origin entry.")
    kept = [origin for origin in origins if origin is not None]
    if any(type(origin) is not int or not 1 <= origin <= saved_row_count for origin in kept):
        raise ValueError("A row origin must be a saved row of this shelf.")
    if any(lower >= upper for lower, upper in zip(kept, kept[1:])):
        raise ValueError("Saved rows must keep their order.")


def plan_layout(saved: Iterable[SavedCell], saved_row_count: int, layout: Sequence[int], *,
                floor: str, side: str, shelf_code: str, revert_location_id: bool = False,
                row_origins: Sequence[int | None] | None = None) -> LayoutPlan:
    """row_origins[i] is the saved row that becomes row i + 1, or None for a new row."""
    layout = list(layout)
    origins = default_row_origins(saved_row_count, len(layout)) if row_origins is None else list(row_origins)
    _check_origins(origins, saved_row_count, len(layout))

    by_row: dict[int, list[SavedCell]] = defaultdict(list)
    for cell in saved:
        by_row[cell.row].append(cell)
    new_row_of = {origin: row for row, origin in enumerate(origins, 1) if origin is not None}
    leftovers = sorted(row for row, cells in by_row.items()
                       if row not in new_row_of and any(cell.occupied for cell in cells))
    for offset, saved_row in enumerate(leftovers, 1):
        new_row_of[saved_row] = len(layout) + offset

    kept: dict[int, PlannedCell] = {}
    deleted: set[int] = set()
    for saved_row, cells in by_row.items():
        new_row = new_row_of.get(saved_row)
        if new_row is None:
            deleted.update(cell.key for cell in cells)
            continue
        width = layout[new_row - 1] if new_row <= len(layout) else 0
        last = max((cell.position for cell in cells if cell.position > width and cell.occupied), default=0)
        for cell in cells:
            if cell.position <= width:
                number, ghost = shelf_cell_number(cell.position, width, revert_location_id), False
            elif cell.position <= last:
                number, ghost = cell.position, True
            else:
                deleted.add(cell.key)
                continue
            kept[cell.key] = PlannedCell(new_row, cell.position, number,
                                         make_slot_name(floor, shelf_code, new_row, number, side=side),
                                         ghost, cell.occupied)

    covered = {(cell.row, cell.position) for cell in kept.values()}
    created = tuple(
        PlannedCell(row, position, number, make_slot_name(floor, shelf_code, row, number, side=side))
        for row, width in enumerate(layout, 1) for position in range(1, width + 1)
        if (row, position) not in covered
        for number in (shelf_cell_number(position, width, revert_location_id),))
    row_sources = {new_row: saved_row for saved_row, new_row in sorted(new_row_of.items(), key=lambda item: item[1])}
    return LayoutPlan(kept, frozenset(deleted), created, row_sources)

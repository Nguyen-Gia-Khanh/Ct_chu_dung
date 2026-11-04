"""Shelf layouts, their cells (slots), and the explicit commit from the shelf designer."""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Sequence
from contextlib import closing
from uuid import uuid4

from mapper.core.common import UTC_DEFAULT, clean_location_segment, iso_timestamp, normalize_sku, shelf_cell_number
from mapper.services.layout_plan import LayoutPlan, SavedCell, plan_layout
from .models import GhostCellError, LayoutConflictError, Placement, SlotAddress, validate_stock_quantity
from .shared import IN_IDS, LOCATION_SQL, PRODUCT_NAME_SQL, ids_param

SLOT_ADDRESS_SQL = """SELECT slots.slot_id, shelves.shelf_id, shelves.floor, shelves.side, shelves.shelf_code,
                             slots.row_number, slots.slot_number, slots.slot_name,
                             EXISTS (SELECT 1 FROM ghost_slots g WHERE g.slot_id = slots.slot_id) AS ghost
                      FROM slots JOIN shelves ON shelves.shelf_id = slots.shelf_id"""
OCCUPIED_SQL = """(EXISTS (SELECT 1 FROM placements p WHERE p.slot_id = {cell}.slot_id)
                  OR EXISTS (SELECT 1 FROM exception_placements e WHERE e.slot_id = {cell}.slot_id))"""


def rename_slots(connection: sqlite3.Connection, changes: dict[int, tuple[int, int, str]]) -> None:
    """Move cells to a new (row, number, name), including the exception table's copied location IDs."""
    if not changes:
        return
    if len({name for _row, _number, name in changes.values()}) != len(changes):
        raise LayoutConflictError("These shelf codes produce duplicate location IDs. Use distinct shelf codes.")
    prefix = f"__location_update_{uuid4().hex}_"
    highest = connection.execute("SELECT COALESCE(MAX(slot_number), 0) FROM slots").fetchone()[0]
    staged = connection.execute(f"SELECT id, slot_id FROM wait_to_update_csv WHERE slot_id {IN_IDS}",
                                (ids_param(changes),)).fetchall()
    # Both UNIQUE constraints need temporary values while the two ends trade names.
    connection.executemany("UPDATE wait_to_update_csv SET slot_name = ? WHERE id = ?",
                           [(f"{prefix}staged_{row['id']}", row['id']) for row in staged])
    connection.executemany("UPDATE slots SET slot_number = ?, slot_name = ? WHERE slot_id = ?",
                           [(highest + sid + 1, f"{prefix}{sid}", sid) for sid in changes])
    try:
        connection.executemany("UPDATE slots SET row_number = ?, slot_number = ?, slot_name = ? WHERE slot_id = ?",
                               [(row, number, name, sid) for sid, (row, number, name) in changes.items()])
        connection.executemany("UPDATE wait_to_update_csv SET slot_name = ? WHERE id = ?",
                               [(changes[row['slot_id']][2], row['id']) for row in staged])
    except sqlite3.IntegrityError as error:
        raise LayoutConflictError(
            "A renamed location ID conflicts with another shelf or staged exception. Nothing was saved."
        ) from error


def saved_cells(connection: sqlite3.Connection, shelf_id: int) -> tuple[int, bool, list[SavedCell]]:
    """(row count, reverse flag, cells): each cell's left-to-right position, ghost flag,
    occupancy and location ID. A ghost's position is its number."""
    shelf = connection.execute("SELECT revert_location_id, row_count FROM shelves WHERE shelf_id = ?",
                               (shelf_id,)).fetchone()
    if shelf is None:
        raise KeyError(f"Shelf {shelf_id} does not exist.")
    reverse = bool(shelf["revert_location_id"])
    rows = connection.execute(f"""SELECT s.slot_id, s.row_number, s.slot_number, s.slot_name,
                                         EXISTS (SELECT 1 FROM ghost_slots g WHERE g.slot_id = s.slot_id) AS ghost,
                                         {OCCUPIED_SQL.format(cell="s")} AS occupied
                                  FROM slots s WHERE s.shelf_id = ?""", (shelf_id,)).fetchall()
    widths = Counter(row["row_number"] for row in rows if not row["ghost"])
    return shelf["row_count"], reverse, [
        SavedCell(row["slot_id"], row["row_number"],
                  row["slot_number"] if row["ghost"] else
                  shelf_cell_number(row["slot_number"], widths[row["row_number"]], reverse),
                  bool(row["ghost"]), bool(row["occupied"]), row["slot_name"]) for row in rows]


def sync_layout(connection: sqlite3.Connection, shelf_id: int, floor: str, shelf_code: str,
                layout: list[int], *, side: str = "1", revert_location_id: bool | None = None,
                row_origins: Sequence[int | None] | None = None) -> LayoutPlan:
    """Keep cell IDs and products at their physical positions while labels change.

    Removed cells that still hold products stay as ghost cells, and rows follow
    row_origins (see mapper.services.layout_plan).
    """
    row_count, previous_reverse, saved = saved_cells(connection, shelf_id)
    if revert_location_id is None:
        revert_location_id = previous_reverse
    plan = plan_layout(saved, row_count, layout, floor=floor, side=side, shelf_code=shelf_code,
                       revert_location_id=revert_location_id, row_origins=row_origins)
    if plan.deleted:
        connection.execute(f"DELETE FROM slots WHERE slot_id {IN_IDS}", (ids_param(plan.deleted),))
    current = {cell.key: (cell.row, cell.name) for cell in saved}
    rename_slots(connection, {sid: (cell.row, cell.number, cell.name) for sid, cell in plan.kept.items()
                              if current[sid] != (cell.row, cell.name)})
    connection.execute(f"DELETE FROM ghost_slots WHERE slot_id {IN_IDS}",
                       (ids_param(sid for sid, cell in plan.kept.items() if not cell.ghost),))
    connection.executemany("INSERT OR IGNORE INTO ghost_slots (slot_id) VALUES (?)",
                           [(sid,) for sid, cell in plan.kept.items() if cell.ghost])
    connection.executemany("INSERT INTO slots (shelf_id, row_number, slot_number, slot_name) VALUES (?, ?, ?, ?)",
                           [(shelf_id, cell.row, cell.number, cell.name) for cell in plan.created])
    connection.execute("UPDATE shelves SET row_count = ?, revert_location_id = ? WHERE shelf_id = ?",
                       (len(layout), int(revert_location_id), shelf_id))
    return plan


def _validated_staging(staged_assignments: dict[str, Placement]) -> dict[str, Placement]:
    staged = {}
    for pid, placement in staged_assignments.items():
        if not placement.assigned_at:
            raise ValueError('Each assignment must include a timezone-aware assignment time.')
        validate_stock_quantity(placement.stock_qty)
        staged[normalize_sku(pid)] = Placement(placement.slot_name, placement.stock_qty, iso_timestamp(placement.assigned_at))
    return staged


class ShelfOperations:
    def list_shelves(self) -> list[tuple[int, str, str, str]]:
        with closing(self.connect()) as connection:
            return [tuple(row) for row in connection.execute(
                """SELECT shelf_id, floor, side, shelf_code FROM shelves
                   ORDER BY floor COLLATE NOCASE, side COLLATE NOCASE, shelf_code COLLATE NOCASE""")]

    def get_shelf_id(self, floor: str, shelf_code: str, *, side: str = "1") -> int | None:
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT shelf_id FROM shelves WHERE floor = ? AND side = ? AND shelf_code = ?",
                (clean_location_segment(floor), clean_location_segment(side), clean_location_segment(shelf_code)),
            ).fetchone()
        return row["shelf_id"] if row is not None else None

    def get_shelf(self, shelf_id: int) -> tuple[str, str, str, list[int]]:
        """(floor, side, shelf code, cells per row from the ground up)."""
        with closing(self.connect()) as connection:
            shelf = connection.execute("SELECT floor, side, shelf_code, row_count FROM shelves WHERE shelf_id = ?",
                                       (shelf_id,)).fetchone()
            if shelf is None:
                raise KeyError(f"Shelf {shelf_id} does not exist.")
            counts = dict(connection.execute(
                """SELECT row_number, COUNT(*) FROM slots WHERE shelf_id = ?
                   AND slot_id NOT IN (SELECT slot_id FROM ghost_slots) GROUP BY row_number""", (shelf_id,)))
        return shelf["floor"], shelf["side"], shelf["shelf_code"], [counts.get(n, 0) for n in range(1, shelf["row_count"] + 1)]

    def get_layout_cells(self, shelf_id: int) -> tuple[int, list[SavedCell]]:
        """The saved row count and cells, as the layout planner reads them."""
        with closing(self.connect()) as connection:
            row_count, _reverse, cells = saved_cells(connection, shelf_id)
        return row_count, cells

    def get_shelf_ghosts(self, shelf_id: int) -> list[tuple[int, int, str]]:
        """Ghost cells to draw as (row, number, location ID): in each row, those up to the
        last ghost still holding products. Emptied ones stay saved until the next commit."""
        with closing(self.connect()) as connection:
            rows = connection.execute(f"""
                SELECT s.row_number, s.slot_number, s.slot_name FROM slots s JOIN ghost_slots USING(slot_id)
                WHERE s.shelf_id = ? AND EXISTS (
                    SELECT 1 FROM slots o JOIN ghost_slots USING(slot_id)
                    WHERE o.shelf_id = s.shelf_id AND o.row_number = s.row_number
                      AND o.slot_number >= s.slot_number AND {OCCUPIED_SQL.format(cell="o")})
                ORDER BY s.row_number, s.slot_number""", (shelf_id,)).fetchall()
        return [tuple(row) for row in rows]

    def get_shelf_revert_location_id(self, shelf_id: int) -> bool:
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT revert_location_id FROM shelves WHERE shelf_id = ?", (shelf_id,)).fetchone()
        if row is None:
            raise KeyError(f"Shelf {shelf_id} does not exist.")
        return bool(row[0])

    def _fetch_slot(self, where: str, params: tuple) -> SlotAddress | None:
        with closing(self.connect()) as connection:
            row = connection.execute(f"{SLOT_ADDRESS_SQL} WHERE {where}", params).fetchone()
        return SlotAddress(**{**dict(row), "ghost": bool(row["ghost"])}) if row is not None else None

    def get_slot_address(self, floor: str, side: str, shelf_code: str, row_number: int, slot_number: int) -> SlotAddress | None:
        return self._fetch_slot(
            """shelves.floor = ? COLLATE NOCASE AND shelves.side = ? COLLATE NOCASE
               AND shelves.shelf_code = ? COLLATE NOCASE AND slots.row_number = ? AND slots.slot_number = ?""",
            (clean_location_segment(floor), clean_location_segment(side), clean_location_segment(shelf_code),
             row_number, slot_number))

    def get_slot_by_name(self, slot_name: str) -> SlotAddress | None:
        """Resolve an exact location ID without relying on its display format."""
        return self._fetch_slot("slots.slot_name = ? COLLATE NOCASE", (slot_name.strip(),))

    def get_slot_by_id(self, slot_id: int) -> SlotAddress | None:
        return self._fetch_slot("slots.slot_id = ?", (slot_id,))

    def get_slot_in_shelf(self, shelf_id: int, row_number: int, slot_number: int) -> SlotAddress | None:
        return self._fetch_slot("slots.shelf_id = ? AND slots.row_number = ? AND slots.slot_number = ?",
                                (shelf_id, row_number, slot_number))

    def _read_contents(self, where, parameter):
        with closing(self.connect()) as connection:
            rows = connection.execute(f"""
                SELECT l.product_id, {PRODUCT_NAME_SQL} AS product_name, s.slot_name, l.stock_qty, l.assigned_at
                FROM ({LOCATION_SQL}) l JOIN catalog_products c USING(product_id) JOIN slots s USING(slot_id)
                WHERE {where} ORDER BY s.row_number, s.slot_number, l.product_id COLLATE NOCASE""", (parameter,)).fetchall()
        return [(r['product_id'], r['product_name'], Placement(r['slot_name'], r['stock_qty'], r['assigned_at'])) for r in rows]

    def get_slot_contents(self, slot_id):
        return self._read_contents('l.slot_id=?', slot_id)

    def get_shelf_contents(self, shelf_id):
        return self._read_contents('s.shelf_id=?', shelf_id)

    def commit_shelf(
        self,
        floor: str,
        shelf_code: str,
        layout: list[int],
        staged_assignments: dict[str, Placement],
        pending_unassignments: set[str],
        *,
        side: str = "1",
        shelf_id: int | None = None,
        revert_location_id: bool | None = None,
        row_origins: Sequence[int | None] | None = None,
    ) -> int:
        """Save a layout plus the designer's staged moves and removals in one transaction.

        row_origins[i] is the saved row that becomes row i + 1 (None for a new row);
        omitted, rows keep their numbers and change only at the top."""
        if any(type(count) is not int or count < 0 for count in layout):
            raise ValueError('Each shelf row needs a nonnegative whole-number cell count.')
        if revert_location_id is not None and type(revert_location_id) is not bool:
            raise ValueError("Reverse location ID must be true or false.")
        staged = _validated_staging(staged_assignments)
        unassigned = {normalize_sku(pid) for pid in pending_unassignments}
        floor, shelf_code, side = (clean_location_segment(value) for value in (floor, shelf_code, side))
        if not floor or not shelf_code or not side:
            raise ValueError("Floor, side, and shelf code are required.")

        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            shelf_id = self._upsert_shelf(connection, floor, side, shelf_code, shelf_id)
            self._return_unassigned(connection, unassigned - staged.keys())
            # Explicit removals/moves happen in this same transaction, so a product
            # can be moved off a top row and that row removed in one commit.
            connection.execute(f"DELETE FROM placements WHERE product_id {IN_IDS}", (ids_param(unassigned | staged.keys()),))
            connection.execute(f"DELETE FROM on_hand_queue WHERE product_id {IN_IDS}", (ids_param(staged),))
            sync_layout(connection, shelf_id, floor, shelf_code, layout, side=side,
                        revert_location_id=revert_location_id, row_origins=row_origins)
            self._place_staged(connection, shelf_id, staged)
        return shelf_id

    @staticmethod
    def _upsert_shelf(connection, floor: str, side: str, shelf_code: str, shelf_id: int | None) -> int:
        shelf = connection.execute(
            """SELECT shelf_id FROM shelves
               WHERE floor = ? COLLATE NOCASE AND side = ? COLLATE NOCASE AND shelf_code = ? COLLATE NOCASE""",
            (floor, side, shelf_code)).fetchone()
        if shelf_id is not None:
            if shelf is not None and shelf["shelf_id"] != shelf_id:
                raise LayoutConflictError("That floor, side, and shelf code already identify another shelf.")
            cursor = connection.execute(
                f"UPDATE shelves SET floor = ?, side = ?, shelf_code = ?, updated_at = {UTC_DEFAULT} WHERE shelf_id = ?",
                (floor, side, shelf_code, shelf_id))
            if cursor.rowcount != 1:
                raise KeyError(f"Shelf {shelf_id} does not exist.")
            return shelf_id
        if shelf is None:
            return int(connection.execute("INSERT INTO shelves (floor, side, shelf_code) VALUES (?, ?, ?)",
                                          (floor, side, shelf_code)).lastrowid)
        connection.execute(f"UPDATE shelves SET updated_at = {UTC_DEFAULT} WHERE shelf_id = ?", (shelf["shelf_id"],))
        return int(shelf["shelf_id"])

    @staticmethod
    def _return_unassigned(connection, product_ids: set[str]) -> None:
        """Products removed in the designer go back to the on-hand queue with their stock."""
        batch = ids_param(product_ids)
        connection.execute(f"""INSERT INTO on_hand_queue(product_id, stock_qty, queued_at)
                               SELECT product_id, stock_qty, ? FROM placements WHERE product_id {IN_IDS}""",
                           (iso_timestamp(), batch))
        connection.execute(f"DELETE FROM exception_placements WHERE product_id {IN_IDS}", (batch,))

    @staticmethod
    def _place_staged(connection, shelf_id: int, staged: dict[str, Placement]) -> None:
        slot_ids = dict(connection.execute("SELECT slot_name, slot_id FROM slots WHERE shelf_id = ?", (shelf_id,)))
        unknown = sorted({placement.slot_name for placement in staged.values()} - slot_ids.keys())
        if unknown:
            raise ValueError(f"Unknown slot in staged assignments: {unknown[0]}")
        ghosts = {row[0] for row in connection.execute(
            "SELECT slot_name FROM slots JOIN ghost_slots USING(slot_id) WHERE shelf_id = ?", (shelf_id,))}
        into_ghost = sorted({placement.slot_name for placement in staged.values()} & ghosts)
        if into_ghost:
            raise GhostCellError(into_ghost[0])
        connection.executemany("DELETE FROM exception_placements WHERE product_id = ? AND slot_id = ?",
                               [(pid, slot_ids[p.slot_name]) for pid, p in staged.items()])
        connection.executemany("INSERT INTO placements (product_id, slot_id, stock_qty, assigned_at) VALUES (?, ?, ?, ?)",
                               [(pid, slot_ids[p.slot_name], p.stock_qty, p.assigned_at) for pid, p in staged.items()])

    def save_shelf(self, floor: str, shelf_code: str, row_counts: list[int], *, side: str = "1",
                   shelf_id: int | None = None, revert_location_id: bool | None = None) -> int:
        """Create or update a shelf layout; row_counts[0] is physical Row 1."""
        return self.commit_shelf(floor, shelf_code, row_counts, {}, set(), side=side, shelf_id=shelf_id,
                                 revert_location_id=revert_location_id)

    def delete_shelf(self, shelf_id: int) -> None:
        """Delete an empty shelf definition and its slots."""
        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            shelf = connection.execute("SELECT shelf_code FROM shelves WHERE shelf_id = ?", (shelf_id,)).fetchone()
            if not shelf:
                raise KeyError(f"Shelf {shelf_id} not found.")
            stored = connection.execute(f"""SELECT COUNT(*) FROM ({LOCATION_SQL}) l JOIN slots s USING(slot_id)
                                            WHERE s.shelf_id = ?""", (shelf_id,)).fetchone()[0]
            if stored:
                raise ValueError(f"Cannot delete Shelf {shelf['shelf_code']}: {stored} product(s) are stored on this shelf.")
            connection.execute("DELETE FROM shelves WHERE shelf_id = ?", (shelf_id,))

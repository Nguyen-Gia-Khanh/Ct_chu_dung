"""Shelf layouts, their cells (slots), and the explicit commit from the shelf designer."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from uuid import uuid4

from mapper.core.common import UTC_DEFAULT, clean_location_segment, iso_timestamp, normalize_sku, shelf_prefix
from .models import LayoutConflictError, Placement, SlotAddress, validate_stock_quantity
from .shared import IN_IDS, LOCATION_SQL, PRODUCT_NAME_SQL, ids_param

SLOT_ADDRESS_SQL = """SELECT slots.slot_id, shelves.shelf_id, shelves.floor, shelves.side, shelves.shelf_code,
                             slots.row_number, slots.slot_number, slots.slot_name
                      FROM slots JOIN shelves ON shelves.shelf_id = slots.shelf_id"""


def rename_slots(connection: sqlite3.Connection, names: dict[int, str]) -> None:
    """Give slots new location IDs without tripping UNIQUE between old and new labels."""
    if not names:
        return
    if len(set(names.values())) != len(names):
        raise LayoutConflictError("These shelf codes produce duplicate location IDs. Use distinct shelf codes.")
    prefix = f"__location_update_{uuid4().hex}_"
    connection.executemany("UPDATE slots SET slot_name = ? WHERE slot_id = ?",
                           ((f"{prefix}{slot_id}", slot_id) for slot_id in names))
    try:
        connection.executemany("UPDATE slots SET slot_name = ? WHERE slot_id = ?",
                               ((name, slot_id) for slot_id, name in names.items()))
    except sqlite3.IntegrityError as error:
        raise LayoutConflictError(
            "A location ID already belongs to another shelf. Use a distinct side or shelf code."
        ) from error


def sync_layout(connection: sqlite3.Connection, shelf_id: int, floor: str, shelf_code: str,
                layout: list[int], *, side: str = "1") -> None:
    """Add/remove top rows and cells without rebuilding surviving slot IDs."""
    prefix = shelf_prefix(floor, shelf_code, side=side)
    names = {(row_number, cell): f"{prefix}{row_number}-{cell}"
             for row_number, count in enumerate(layout, start=1) for cell in range(1, count + 1)}
    existing = {(row["row_number"], row["slot_number"]): row
                for row in connection.execute("SELECT * FROM slots WHERE shelf_id = ?", (shelf_id,))}
    removed = [row["slot_id"] for key, row in existing.items() if key not in names]
    if removed:
        occupied = connection.execute(f"""SELECT slot_name FROM slots WHERE slot_id {IN_IDS}
            AND (EXISTS (SELECT 1 FROM placements p WHERE p.slot_id = slots.slot_id)
                 OR EXISTS (SELECT 1 FROM exception_placements e WHERE e.slot_id = slots.slot_id))
            ORDER BY row_number, slot_number LIMIT 1""", (ids_param(removed),)).fetchone()
        if occupied:
            raise LayoutConflictError(f"{occupied[0]} still contains committed products. "
                                      "Return or move those products before removing its row or cell.")
        connection.execute(f"DELETE FROM slots WHERE slot_id {IN_IDS}", (ids_param(removed),))
    rename_slots(connection, {row["slot_id"]: names[key] for key, row in existing.items()
                              if key in names and row["slot_name"] != names[key]})
    # Ascending storage order means new rows extend the top of the shelf.
    connection.executemany("INSERT INTO slots (shelf_id, row_number, slot_number, slot_name) VALUES (?, ?, ?, ?)",
                           [(shelf_id, row_number, cell, name) for (row_number, cell), name in names.items()
                            if (row_number, cell) not in existing])
    connection.execute("UPDATE shelves SET row_count = ? WHERE shelf_id = ?", (len(layout), shelf_id))


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
                "SELECT row_number, COUNT(*) FROM slots WHERE shelf_id = ? GROUP BY row_number", (shelf_id,)))
        return shelf["floor"], shelf["side"], shelf["shelf_code"], [counts.get(n, 0) for n in range(1, shelf["row_count"] + 1)]

    def get_shelf_revert_location_id(self, shelf_id: int) -> bool:
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT revert_location_id FROM shelves WHERE shelf_id = ?", (shelf_id,)).fetchone()
        if row is None:
            raise KeyError(f"Shelf {shelf_id} does not exist.")
        return bool(row[0])

    def _fetch_slot(self, where: str, params: tuple) -> SlotAddress | None:
        with closing(self.connect()) as connection:
            row = connection.execute(f"{SLOT_ADDRESS_SQL} WHERE {where}", params).fetchone()
        return SlotAddress(**row) if row is not None else None

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
    ) -> int:
        """Save a layout plus the designer's staged moves and removals in one transaction."""
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
            if revert_location_id is not None:
                connection.execute("UPDATE shelves SET revert_location_id = ? WHERE shelf_id = ?",
                                   (int(revert_location_id), shelf_id))
            self._return_unassigned(connection, unassigned - staged.keys())
            # Explicit removals/moves happen in this same transaction, so a product
            # can be moved off a top row and that row removed in one commit.
            connection.execute(f"DELETE FROM placements WHERE product_id {IN_IDS}", (ids_param(unassigned | staged.keys()),))
            connection.execute(f"DELETE FROM on_hand_queue WHERE product_id {IN_IDS}", (ids_param(staged),))
            sync_layout(connection, shelf_id, floor, shelf_code, layout, side=side)
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

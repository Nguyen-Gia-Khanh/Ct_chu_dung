from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime

from mapper.core.common import clean_location_segment, make_slot_name
from .models import LayoutConflictError, Placement, SlotAddress, validate_stock_quantity

class ShelfOperations:
    def list_shelves(self) -> list[tuple[int, str, str, str]]:
        with closing(self.connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT shelf_id, floor, side, shelf_code
                FROM shelves
                ORDER BY floor COLLATE NOCASE, side COLLATE NOCASE, shelf_code COLLATE NOCASE
                """
            ).fetchall()
        return [
            (row["shelf_id"], row["floor"], row["side"], row["shelf_code"])
            for row in rows
        ]

    def get_shelf_id(
        self, floor: str, shelf_code: str, *, side: str = "1"
    ) -> int | None:
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT shelf_id FROM shelves WHERE floor = ? AND side = ? AND shelf_code = ?",
                (
                    clean_location_segment(floor),
                    clean_location_segment(side),
                    clean_location_segment(shelf_code),
                ),
            ).fetchone()
        return row["shelf_id"] if row is not None else None

    def get_shelf(self, shelf_id: int) -> tuple[str, str, str, list[int]]:
        with closing(self.connect()) as connection, connection:
            shelf = connection.execute(
                "SELECT floor, side, shelf_code FROM shelves WHERE shelf_id = ?",
                (shelf_id,),
            ).fetchone()
            if shelf is None:
                raise KeyError(f"Shelf {shelf_id} does not exist.")
            rows = connection.execute(
                """
                SELECT slot_count
                FROM shelf_rows
                WHERE shelf_id = ?
                ORDER BY row_number
                """,
                (shelf_id,),
            ).fetchall()
        return (
            shelf["floor"],
            shelf["side"],
            shelf["shelf_code"],
            [row["slot_count"] for row in rows],
        )

    def get_slot_address(
        self,
        floor: str,
        side: str,
        shelf_code: str,
        row_number: int,
        slot_number: int,
    ) -> SlotAddress | None:
        floor = clean_location_segment(floor)
        side = clean_location_segment(side)
        shelf_code = clean_location_segment(shelf_code)
        with closing(self.connect()) as connection:
            row = connection.execute(
                """
                SELECT slots.slot_id, shelves.shelf_id, shelves.floor, shelves.side,
                       shelves.shelf_code, shelf_rows.row_number,
                       slots.slot_number, slots.slot_name
                FROM slots
                JOIN shelf_rows ON shelf_rows.row_id = slots.row_id
                JOIN shelves ON shelves.shelf_id = shelf_rows.shelf_id
                WHERE shelves.floor = ? COLLATE NOCASE
                  AND shelves.side = ? COLLATE NOCASE
                  AND shelves.shelf_code = ? COLLATE NOCASE
                  AND shelf_rows.row_number = ?
                  AND slots.slot_number = ?
                """,
                (floor, side, shelf_code, row_number, slot_number),
            ).fetchone()
        if row is None:
            return None
        return SlotAddress(
            row["slot_id"],
            row["shelf_id"],
            row["floor"],
            row["side"],
            row["shelf_code"],
            row["row_number"],
            row["slot_number"],
            row["slot_name"],
        )

    def get_slot_by_name(self, slot_name: str) -> SlotAddress | None:
        """Resolve an exact location ID without relying on its display format."""
        with closing(self.connect()) as connection:
            row = connection.execute(
                """
                SELECT slots.slot_id, shelves.shelf_id, shelves.floor, shelves.side,
                       shelves.shelf_code, shelf_rows.row_number,
                       slots.slot_number, slots.slot_name
                FROM slots
                JOIN shelf_rows ON shelf_rows.row_id = slots.row_id
                JOIN shelves ON shelves.shelf_id = shelf_rows.shelf_id
                WHERE slots.slot_name = ? COLLATE NOCASE
                """,
                (slot_name.strip(),),
            ).fetchone()
        if row is None:
            return None
        return SlotAddress(
            row["slot_id"],
            row["shelf_id"],
            row["floor"],
            row["side"],
            row["shelf_code"],
            row["row_number"],
            row["slot_number"],
            row["slot_name"],
        )

    def get_slot_by_id(self, slot_id: int) -> SlotAddress | None:
        with closing(self.connect()) as connection:
            row = connection.execute(
                """
                SELECT slots.slot_id, shelves.shelf_id, shelves.floor, shelves.side,
                       shelves.shelf_code, shelf_rows.row_number,
                       slots.slot_number, slots.slot_name
                FROM slots
                JOIN shelf_rows ON shelf_rows.row_id = slots.row_id
                JOIN shelves ON shelves.shelf_id = shelf_rows.shelf_id
                WHERE slots.slot_id = ?
                """,
                (slot_id,),
            ).fetchone()
        if row is None:
            return None
        return SlotAddress(
            row["slot_id"],
            row["shelf_id"],
            row["floor"],
            row["side"],
            row["shelf_code"],
            row["row_number"],
            row["slot_number"],
            row["slot_name"],
        )

    def get_slot_contents(self, slot_id: int) -> list[tuple[str, str, Placement]]:
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT product_id, product_name, slot_name, stock_qty, assigned_at
                FROM (
                    SELECT products.product_id, products.product_name, slots.slot_name,
                           placements.stock_qty, placements.assigned_at
                    FROM placements
                    JOIN products ON products.product_id = placements.product_id
                    JOIN slots ON slots.slot_id = placements.slot_id
                    WHERE placements.slot_id = ?
                    UNION
                    SELECT ep.product_id, COALESCE(products.product_name, 'Exc - added later') AS product_name, slots.slot_name,
                           ep.stock_qty, ep.assigned_at
                    FROM exception_placements ep
                    LEFT JOIN products ON products.product_id = ep.product_id
                    JOIN slots ON slots.slot_id = ep.slot_id
                    WHERE ep.slot_id = ?
                )
                ORDER BY assigned_at, product_id COLLATE NOCASE
                """,
                (slot_id, slot_id),
            ).fetchall()
        return [
            (
                row["product_id"],
                row["product_name"],
                Placement(row["slot_name"], row["stock_qty"], row["assigned_at"]),
            )
            for row in rows
        ]

    def get_shelf_contents(self, shelf_id: int) -> list[tuple[str, str, Placement]]:
        """Return only committed products on one shelf for the read-only viewer."""
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT product_id, product_name, slot_name, stock_qty, assigned_at, row_number, slot_number
                FROM (
                    SELECT products.product_id, products.product_name, slots.slot_name,
                           placements.stock_qty, placements.assigned_at,
                           shelf_rows.row_number, slots.slot_number
                    FROM placements
                    JOIN products ON products.product_id = placements.product_id
                    JOIN slots ON slots.slot_id = placements.slot_id
                    JOIN shelf_rows ON shelf_rows.row_id = slots.row_id
                    WHERE shelf_rows.shelf_id = ?
                    UNION
                    SELECT ep.product_id, COALESCE(products.product_name, 'Exc - added later') AS product_name, slots.slot_name,
                           ep.stock_qty, ep.assigned_at,
                           shelf_rows.row_number, slots.slot_number
                    FROM exception_placements ep
                    LEFT JOIN products ON products.product_id = ep.product_id
                    JOIN slots ON slots.slot_id = ep.slot_id
                    JOIN shelf_rows ON shelf_rows.row_id = slots.row_id
                    WHERE shelf_rows.shelf_id = ?
                )
                ORDER BY row_number, slot_number, product_id COLLATE NOCASE
                """,
                (shelf_id, shelf_id),
            ).fetchall()
        return [
            (
                row["product_id"],
                row["product_name"],
                Placement(row["slot_name"], row["stock_qty"], row["assigned_at"]),
            )
            for row in rows
        ]

    @classmethod
    def _sync_layout(
        cls,
        connection: sqlite3.Connection,
        shelf_id: int,
        floor: str,
        shelf_code: str,
        layout: list[int],
        *,
        side: str = "1",
    ) -> None:
        """Add/remove top rows and cells without rebuilding surviving slot IDs."""
        desired = {
            (row_number, cell)
            for row_number, count in enumerate(layout, start=1)
            for cell in range(1, count + 1)
        }
        existing_slots = {
            (row["row_number"], row["slot_number"]): row
            for row in connection.execute(
                """
                SELECT slots.*, shelf_rows.row_number
                FROM slots
                JOIN shelf_rows ON shelf_rows.row_id = slots.row_id
                WHERE shelf_rows.shelf_id = ?
                """,
                (shelf_id,),
            )
        }
        removed = [row for key, row in existing_slots.items() if key not in desired]
        for row in removed:
            if connection.execute(
                "SELECT 1 FROM placements WHERE slot_id = ? LIMIT 1", (row["slot_id"],)
            ).fetchone():
                raise LayoutConflictError(
                    f"{row['slot_name']} still contains committed products. "
                    "Return or move those products before removing its row or cell."
                )
        connection.executemany(
            "DELETE FROM slots WHERE slot_id = ?",
            ((row["slot_id"],) for row in removed),
        )
        cls._rename_slots(
            connection,
            {
                row["slot_id"]: make_slot_name(
                    floor, shelf_code, row_number, cell, side=side
                )
                for (row_number, cell), row in existing_slots.items()
                if (row_number, cell) in desired
                and row["slot_name"]
                != make_slot_name(floor, shelf_code, row_number, cell, side=side)
            },
        )

        existing_rows = {
            row["row_number"]: row["row_id"]
            for row in connection.execute(
                "SELECT row_id, row_number FROM shelf_rows WHERE shelf_id = ?",
                (shelf_id,),
            )
        }
        # Ascending storage order means new rows extend the top of the shelf.
        for row_number, count in enumerate(layout, start=1):
            row_id = existing_rows.get(row_number)
            if row_id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO shelf_rows (shelf_id, row_number, slot_count)
                    VALUES (?, ?, ?)
                    """,
                    (shelf_id, row_number, count),
                )
                row_id = cursor.lastrowid
            else:
                connection.execute(
                    """
                    UPDATE shelf_rows SET slot_count = ?
                    WHERE row_id = ?
                    """,
                    (count, row_id),
                )
            connection.executemany(
                "INSERT INTO slots (row_id, slot_number, slot_name) VALUES (?, ?, ?)",
                (
                    (
                        row_id,
                        cell,
                        make_slot_name(floor, shelf_code, row_number, cell, side=side),
                    )
                    for cell in range(1, count + 1)
                    if (row_number, cell) not in existing_slots
                ),
            )
        connection.execute(
            "DELETE FROM shelf_rows WHERE shelf_id = ? AND row_number > ?",
            (shelf_id, len(layout)),
        )

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
    ) -> int:
        floor = clean_location_segment(floor)
        shelf_code = clean_location_segment(shelf_code)
        side = clean_location_segment(side)
        if not floor or not shelf_code or not side:
            raise ValueError("Floor, side, and shelf code are required.")
        even_side = int(side.isdigit() and int(side) % 2 == 0)
        for placement in staged_assignments.values():
            validate_stock_quantity(placement.stock_qty)
            if (
                not placement.assigned_at
                or datetime.fromisoformat(placement.assigned_at).utcoffset() is None
            ):
                raise ValueError(
                    "Each assignment must include the time it was added, with a timezone."
                )

        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            shelf = connection.execute(
                """
                SELECT shelf_id FROM shelves
                WHERE floor = ? COLLATE NOCASE AND side = ? COLLATE NOCASE AND shelf_code = ? COLLATE NOCASE
                """,
                (floor, side, shelf_code),
            ).fetchone()
            if shelf_id is not None:
                if shelf is not None and shelf["shelf_id"] != shelf_id:
                    raise LayoutConflictError(
                        "That floor, side, and shelf code already identify another shelf."
                    )
                cursor = connection.execute(
                    """UPDATE shelves
                       SET floor = ?, side = ?, shelf_code = ?,
                           switched_state = CASE
                               WHEN (side <> '' AND side NOT GLOB '*[^0-9]*'
                                     AND CAST(side AS INTEGER) % 2 = 0) <> ?
                               THEN ? ELSE switched_state END,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE shelf_id = ?""",
                    (floor, side, shelf_code, even_side, even_side, shelf_id),
                )
                if cursor.rowcount != 1:
                    raise KeyError(f"Shelf {shelf_id} does not exist.")
            elif shelf is None:
                cursor = connection.execute(
                    "INSERT INTO shelves (floor, side, shelf_code, switched_state) VALUES (?, ?, ?, ?)",
                    (floor, side, shelf_code, even_side),
                )
                shelf_id = int(cursor.lastrowid)
            else:
                shelf_id = int(shelf["shelf_id"])
                connection.execute(
                    "UPDATE shelves SET updated_at = CURRENT_TIMESTAMP WHERE shelf_id = ?",
                    (shelf_id,),
                )

            # Explicit removals/moves happen in this same transaction, so a product
            # can be moved off a top row and that row removed in one commit.
            connection.executemany(
                "DELETE FROM placements WHERE product_id = ?",
                (
                    (product_id,)
                    for product_id in pending_unassignments | set(staged_assignments)
                ),
            )
            connection.executemany(
                "DELETE FROM on_hand_queue WHERE product_id = ?",
                ((product_id,) for product_id in staged_assignments),
            )
            connection.executemany(
                "DELETE FROM returned_queue_products WHERE product_id = ?",
                ((product_id,) for product_id in staged_assignments),
            )
            self._sync_layout(
                connection, shelf_id, floor, shelf_code, layout, side=side
            )
            slot_ids = {
                row["slot_name"]: row["slot_id"]
                for row in connection.execute(
                    """
                    SELECT slots.slot_id, slots.slot_name
                    FROM slots
                    JOIN shelf_rows ON shelf_rows.row_id = slots.row_id
                    WHERE shelf_rows.shelf_id = ?
                    """,
                    (shelf_id,),
                )
            }
            unknown_slots = sorted(
                {placement.slot_name for placement in staged_assignments.values()}
                - set(slot_ids)
            )
            if unknown_slots:
                raise ValueError(
                    f"Unknown slot in staged assignments: {unknown_slots[0]}"
                )

            connection.executemany(
                "INSERT INTO placements (product_id, slot_id, stock_qty, assigned_at) VALUES (?, ?, ?, ?)",
                (
                    (
                        product_id,
                        slot_ids[placement.slot_name],
                        placement.stock_qty,
                        placement.assigned_at,
                    )
                    for product_id, placement in staged_assignments.items()
                ),
            )
        return shelf_id

    def save_shelf(
        self,
        floor: str,
        shelf_code: str,
        row_counts: list[int],
        *,
        side: str = "1",
        shelf_id: int | None = None,
    ) -> int:
        """Create or update a shelf layout with a list of cell counts per row.

        Index 0 in row_counts corresponds to physical Row 1.
        """
        return self.commit_shelf(
            floor=floor,
            shelf_code=shelf_code,
            layout=row_counts,
            staged_assignments={},
            pending_unassignments=set(),
            side=side,
            shelf_id=shelf_id,
        )

    def delete_shelf(self, shelf_id: int) -> None:
        """Delete an empty shelf definition and its associated rows and slots."""
        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            shelf = connection.execute(
                "SELECT shelf_id, floor, side, shelf_code FROM shelves WHERE shelf_id = ?",
                (shelf_id,),
            ).fetchone()
            if not shelf:
                raise KeyError(f"Shelf {shelf_id} not found.")

            occupied = connection.execute(
                """
                SELECT COUNT(*) as count FROM placements p
                JOIN slots s ON p.slot_id = s.slot_id
                JOIN shelf_rows r ON s.row_id = r.row_id
                WHERE r.shelf_id = ?
                """,
                (shelf_id,),
            ).fetchone()["count"]
            exc_occupied = connection.execute(
                """
                SELECT COUNT(*) as count FROM exception_placements ep
                JOIN slots s ON ep.slot_id = s.slot_id
                JOIN shelf_rows r ON s.row_id = r.row_id
                WHERE r.shelf_id = ?
                """,
                (shelf_id,),
            ).fetchone()["count"]
            if occupied > 0 or exc_occupied > 0:
                raise ValueError(
                    f"Cannot delete Shelf {shelf['shelf_code']}: {occupied + exc_occupied} product(s) are stored on this shelf."
                )
            connection.execute("DELETE FROM shelves WHERE shelf_id = ?", (shelf_id,))

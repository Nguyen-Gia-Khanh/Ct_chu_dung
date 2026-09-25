from __future__ import annotations

from contextlib import closing
from datetime import datetime
from typing import Any

from .models import (
    OnHandProduct,
    Placement,
    ProductLocation,
    ReturnedQueueProduct,
    validate_stock_quantity,
)

class InventoryOperations:
    def get_placements(self) -> dict[str, str]:
        return {
            product_id: placement.slot_name
            for product_id, placement in self.get_placement_details().items()
        }

    def get_placement_details(self) -> dict[str, Placement]:
        with closing(self.connect()) as connection, connection:
            p_rows = connection.execute(
                """
                SELECT placements.product_id, slots.slot_name,
                       placements.stock_qty, placements.assigned_at
                FROM placements
                JOIN slots ON slots.slot_id = placements.slot_id
                """
            ).fetchall()
            e_rows = connection.execute(
                """
                SELECT exception_placements.product_id, slots.slot_name,
                       exception_placements.stock_qty, exception_placements.assigned_at
                FROM exception_placements
                JOIN slots ON slots.slot_id = exception_placements.slot_id
                ORDER BY exception_placements.id ASC
                """
            ).fetchall()

        details: dict[str, dict] = {}
        for row in p_rows:
            pid = row["product_id"]
            if pid not in details:
                details[pid] = {
                    "slots": [],
                    "stock_qty": row["stock_qty"],
                    "assigned_at": row["assigned_at"],
                }
            if row["slot_name"] not in details[pid]["slots"]:
                details[pid]["slots"].append(row["slot_name"])

        for row in e_rows:
            pid = row["product_id"]
            if pid not in details:
                details[pid] = {
                    "slots": [],
                    "stock_qty": row["stock_qty"],
                    "assigned_at": row["assigned_at"],
                }
            else:
                if row["stock_qty"] is not None:
                    curr = details[pid]["stock_qty"]
                    details[pid]["stock_qty"] = (curr or 0) + row["stock_qty"]
                if row["assigned_at"] and (
                    not details[pid]["assigned_at"]
                    or row["assigned_at"] > details[pid]["assigned_at"]
                ):
                    details[pid]["assigned_at"] = row["assigned_at"]
            if row["slot_name"] not in details[pid]["slots"]:
                details[pid]["slots"].append(row["slot_name"])

        return {
            pid: Placement(
                ", ".join(info["slots"]),
                info["stock_qty"],
                info["assigned_at"],
            )
            for pid, info in details.items()
        }

    def get_all_placement_items(self) -> list[tuple[str, str, int | None, str | None]]:
        """Return every individual placement (product_id, slot_name, stock_qty, assigned_at)
        across both placements and exception_placements."""
        with closing(self.connect()) as connection:
            p_rows = connection.execute(
                """
                SELECT placements.product_id, slots.slot_name,
                       placements.stock_qty, placements.assigned_at
                FROM placements
                JOIN slots ON slots.slot_id = placements.slot_id
                """
            ).fetchall()
            e_rows = connection.execute(
                """
                SELECT exception_placements.product_id, slots.slot_name,
                       exception_placements.stock_qty, exception_placements.assigned_at
                FROM exception_placements
                JOIN slots ON slots.slot_id = exception_placements.slot_id
                ORDER BY exception_placements.id ASC
                """
            ).fetchall()
        return [
            (row["product_id"], row["slot_name"], row["stock_qty"], row["assigned_at"])
            for row in p_rows + e_rows
        ]

    def get_product_location(self, product_id: str) -> ProductLocation | None:
        """Locate a saved assignment through table relationships, not its ID format."""
        with closing(self.connect()) as connection:
            row = connection.execute(
                """
                SELECT shelf_rows.shelf_id, shelf_rows.row_number, slots.slot_number,
                       slots.slot_name, placements.stock_qty, placements.assigned_at
                FROM placements
                JOIN slots ON slots.slot_id = placements.slot_id
                JOIN shelf_rows ON shelf_rows.row_id = slots.row_id
                WHERE placements.product_id = ?
                """,
                (product_id,),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    """
                    SELECT shelf_rows.shelf_id, shelf_rows.row_number, slots.slot_number,
                           slots.slot_name, exception_placements.stock_qty, exception_placements.assigned_at
                    FROM exception_placements
                    JOIN slots ON slots.slot_id = exception_placements.slot_id
                    JOIN shelf_rows ON shelf_rows.row_id = slots.row_id
                    WHERE exception_placements.product_id = ?
                    ORDER BY exception_placements.id ASC
                    LIMIT 1
                    """,
                    (product_id,),
                ).fetchone()
        if row is None:
            return None

        all_locations = self.get_product_locations(product_id)
        joined_slots = ", ".join(all_locations) if all_locations else row["slot_name"]

        return ProductLocation(
            row["shelf_id"],
            row["row_number"],
            row["slot_number"],
            Placement(joined_slots, row["stock_qty"], row["assigned_at"]),
        )

    def get_product_locations(self, product_id: str) -> list[str]:
        """Return all distinct slot names assigned to this product across standard and exception placements."""
        with closing(self.connect()) as connection:
            p_rows = connection.execute(
                """
                SELECT slots.slot_name
                FROM placements
                JOIN slots ON slots.slot_id = placements.slot_id
                WHERE placements.product_id = ?
                """,
                (product_id,),
            ).fetchall()
            e_rows = connection.execute(
                """
                SELECT slots.slot_name
                FROM exception_placements
                JOIN slots ON slots.slot_id = exception_placements.slot_id
                WHERE exception_placements.product_id = ?
                ORDER BY exception_placements.id ASC
                """,
                (product_id,),
            ).fetchall()
        locations: list[str] = []
        for r in p_rows + e_rows:
            if r["slot_name"] not in locations:
                locations.append(r["slot_name"])
        return locations

    def get_on_hand_products(self) -> dict[str, OnHandProduct]:
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT product_id, stock_qty, queued_at
                FROM on_hand_queue
                ORDER BY queued_at, product_id COLLATE NOCASE
                """
            ).fetchall()
        return {
            row["product_id"]: OnHandProduct(
                row["product_id"], row["stock_qty"], row["queued_at"]
            )
            for row in rows
        }

    def get_returned_queue_products(self) -> dict[str, ReturnedQueueProduct]:
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT product_id, stock_qty, returned_at
                FROM returned_queue_products
                ORDER BY returned_at, product_id COLLATE NOCASE
                """
            ).fetchall()
        return {
            row["product_id"]: ReturnedQueueProduct(
                row["product_id"], row["stock_qty"], row["returned_at"]
            )
            for row in rows
        }

    def add_to_on_hand(
        self,
        quantities: dict[str, int | None],
        queued_at: str,
    ) -> int:
        """Persist unassigned products in the operator's working batch."""
        if not quantities:
            return 0
        for quantity in quantities.values():
            if quantity is not None:
                validate_stock_quantity(quantity)
        if not queued_at or datetime.fromisoformat(queued_at).utcoffset() is None:
            raise ValueError("The on-hand time must include a timezone.")

        product_ids = tuple(quantities)
        placeholders = ",".join("?" for _ in product_ids)
        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            known = {
                row["product_id"]
                for row in connection.execute(
                    f"SELECT product_id FROM products WHERE product_id IN ({placeholders})",
                    product_ids,
                )
            }
            unknown = sorted(set(product_ids) - known)
            if unknown:
                raise KeyError(
                    f"Product {unknown[0]} is not in the working product list."
                )
            assigned = connection.execute(
                f"SELECT product_id FROM placements WHERE product_id IN ({placeholders}) LIMIT 1",
                product_ids,
            ).fetchone()
            if assigned is not None:
                raise ValueError(
                    f"Product {assigned['product_id']} is already assigned to a shelf. "
                    "Move its shelf contents back to on-hand first."
                )
            connection.executemany(
                """
                INSERT INTO on_hand_queue (product_id, stock_qty, queued_at)
                VALUES (?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    stock_qty = excluded.stock_qty,
                    queued_at = excluded.queued_at
                """,
                (
                    (product_id, quantity, queued_at)
                    for product_id, quantity in quantities.items()
                ),
            )
            connection.executemany(
                "DELETE FROM returned_queue_products WHERE product_id = ?",
                ((product_id,) for product_id in product_ids),
            )
        return len(quantities)

    def update_on_hand_stock(self, product_id: str, quantity: int) -> None:
        validate_stock_quantity(quantity)
        with closing(self.connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE on_hand_queue SET stock_qty = ? WHERE product_id = ?",
                (quantity, product_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(
                    f"Product {product_id} is no longer in the on-hand queue."
                )

    def dequeue_on_hand(
        self,
        product_ids: list[str] | tuple[str, ...],
        returned_at: str,
    ) -> int:
        """Move selected on-hand products back to the total queue with stock."""
        selected_ids = tuple(dict.fromkeys(product_ids))
        if not selected_ids:
            return 0
        if not returned_at or datetime.fromisoformat(returned_at).utcoffset() is None:
            raise ValueError("The return time must include a timezone.")

        placeholders = ",".join("?" for _ in selected_ids)
        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                f"""
                SELECT product_id, stock_qty
                FROM on_hand_queue
                WHERE product_id IN ({placeholders})
                """,
                selected_ids,
            ).fetchall()
            rows_by_id = {row["product_id"]: row for row in rows}
            missing = [
                product_id
                for product_id in selected_ids
                if product_id not in rows_by_id
            ]
            if missing:
                raise KeyError(
                    f"Product {missing[0]} is no longer in the on-hand queue."
                )
            connection.executemany(
                """
                INSERT INTO returned_queue_products (product_id, stock_qty, returned_at)
                VALUES (?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    stock_qty = excluded.stock_qty,
                    returned_at = excluded.returned_at
                """,
                (
                    (
                        product_id,
                        rows_by_id[product_id]["stock_qty"],
                        returned_at,
                    )
                    for product_id in selected_ids
                ),
            )
            connection.executemany(
                "DELETE FROM on_hand_queue WHERE product_id = ?",
                ((product_id,) for product_id in selected_ids),
            )
        return len(selected_ids)

    def clear_on_hand(self) -> int:
        """Compatibility helper: return the complete on-hand batch with stock."""
        product_ids = tuple(self.get_on_hand_products())
        if not product_ids:
            return 0
        returned_at = datetime.now().astimezone().isoformat(timespec="seconds")
        return self.dequeue_on_hand(product_ids, returned_at)

    def force_pull_to_queue(
        self,
        product_ids: list[str] | tuple[str, ...],
        returned_at: str,
        *,
        extra_stock: dict[str, int | None] | None = None,
    ) -> tuple[int, int]:
        """Force pull products back to the total queue from placements or on-hand.

        Removes any placements for these products, removes any on-hand entries,
        and saves their retained stock quantities in returned_queue_products.
        Returns (pulled_from_placements_count, pulled_from_on_hand_count).
        """
        selected_ids = tuple(dict.fromkeys(product_ids))
        if not selected_ids:
            return 0, 0
        if not returned_at or datetime.fromisoformat(returned_at).utcoffset() is None:
            raise ValueError("The return time must include a timezone.")

        placeholders = ",".join("?" for _ in selected_ids)
        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            placement_rows = connection.execute(
                f"""
                SELECT product_id, stock_qty
                FROM placements
                WHERE product_id IN ({placeholders})
                """,
                selected_ids,
            ).fetchall()
            on_hand_rows = connection.execute(
                f"""
                SELECT product_id, stock_qty
                FROM on_hand_queue
                WHERE product_id IN ({placeholders})
                """,
                selected_ids,
            ).fetchall()

            if placement_rows:
                connection.execute(
                    f"DELETE FROM placements WHERE product_id IN ({placeholders})",
                    selected_ids,
                )
            if on_hand_rows:
                connection.execute(
                    f"DELETE FROM on_hand_queue WHERE product_id IN ({placeholders})",
                    selected_ids,
                )

            to_return: dict[str, int | None] = {}
            for row in placement_rows:
                to_return[row["product_id"]] = row["stock_qty"]
            for row in on_hand_rows:
                to_return[row["product_id"]] = row["stock_qty"]
            if extra_stock:
                for product_id, stock_qty in extra_stock.items():
                    if product_id in selected_ids and product_id not in to_return:
                        to_return[product_id] = stock_qty

            if to_return:
                connection.executemany(
                    """
                    INSERT INTO returned_queue_products (product_id, stock_qty, returned_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(product_id) DO UPDATE SET
                        stock_qty = excluded.stock_qty,
                        returned_at = excluded.returned_at
                    """,
                    ((pid, qty, returned_at) for pid, qty in to_return.items()),
                )
        return len(placement_rows), len(on_hand_rows)

    def swap_slot_contents(
        self,
        first_slot_id: int,
        second_slot_id: int,
    ) -> tuple[int, int]:
        """Atomically exchange every product in two cells."""
        if first_slot_id == second_slot_id:
            raise ValueError("Choose two different cells to switch.")
        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            slots = connection.execute(
                "SELECT slot_id FROM slots WHERE slot_id IN (?, ?)",
                (first_slot_id, second_slot_id),
            ).fetchall()
            if len(slots) != 2:
                raise KeyError("One of the selected shelf cells no longer exists.")
            counts = {
                row["slot_id"]: row["product_count"]
                for row in connection.execute(
                    """
                    SELECT slots.slot_id, COUNT(placements.product_id) AS product_count
                    FROM slots
                    LEFT JOIN placements ON placements.slot_id = slots.slot_id
                    WHERE slots.slot_id IN (?, ?)
                    GROUP BY slots.slot_id
                    """,
                    (first_slot_id, second_slot_id),
                )
            }
            connection.execute(
                """
                UPDATE placements
                SET slot_id = CASE slot_id
                    WHEN ? THEN ?
                    WHEN ? THEN ?
                END
                WHERE slot_id IN (?, ?)
                """,
                (
                    first_slot_id,
                    second_slot_id,
                    second_slot_id,
                    first_slot_id,
                    first_slot_id,
                    second_slot_id,
                ),
            )
        return counts[first_slot_id], counts[second_slot_id]

    def combine_slot_contents(self, source_slot_id: int, target_slot_id: int) -> int:
        """Atomically move every source-cell product into the target cell."""
        if source_slot_id == target_slot_id:
            raise ValueError("Choose two different cells to combine.")
        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            slots = connection.execute(
                "SELECT slot_id FROM slots WHERE slot_id IN (?, ?)",
                (source_slot_id, target_slot_id),
            ).fetchall()
            if len(slots) != 2:
                raise KeyError("One of the selected shelf cells no longer exists.")
            source_count = connection.execute(
                "SELECT COUNT(*) FROM placements WHERE slot_id = ?",
                (source_slot_id,),
            ).fetchone()[0]
            connection.execute(
                "UPDATE placements SET slot_id = ? WHERE slot_id = ?",
                (target_slot_id, source_slot_id),
            )
        return int(source_count)

    def assign_on_hand_to_slot(
        self,
        slot_id: int,
        assigned_at: str,
        product_ids: list[str] | tuple[str, ...] | None = None,
    ) -> int:
        """Move selected on-hand products, or the complete batch, into one slot."""
        if not assigned_at or datetime.fromisoformat(assigned_at).utcoffset() is None:
            raise ValueError("The assignment time must include a timezone.")
        selected_ids = (
            None if product_ids is None else tuple(dict.fromkeys(product_ids))
        )
        if selected_ids == ():
            return 0
        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if (
                connection.execute(
                    "SELECT 1 FROM slots WHERE slot_id = ?", (slot_id,)
                ).fetchone()
                is None
            ):
                raise KeyError("That shelf address no longer exists.")
            all_rows = connection.execute(
                "SELECT product_id, stock_qty FROM on_hand_queue ORDER BY queued_at, product_id"
            ).fetchall()
            if selected_ids is None:
                rows = all_rows
            else:
                rows_by_id = {row["product_id"]: row for row in all_rows}
                missing = [
                    product_id
                    for product_id in selected_ids
                    if product_id not in rows_by_id
                ]
                if missing:
                    raise KeyError(
                        f"Product {missing[0]} is no longer in the on-hand queue."
                    )
                rows = [rows_by_id[product_id] for product_id in selected_ids]
            if not rows:
                return 0
            conflicts = connection.execute(
                """
                SELECT placements.product_id
                FROM placements
                JOIN on_hand_queue ON on_hand_queue.product_id = placements.product_id
                LIMIT 1
                """
            ).fetchone()
            if conflicts is not None:
                raise ValueError(
                    f"Product {conflicts['product_id']} is already assigned to a shelf."
                )
            connection.executemany(
                """
                INSERT INTO placements (product_id, slot_id, stock_qty, assigned_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    (row["product_id"], slot_id, row["stock_qty"], assigned_at)
                    for row in rows
                ),
            )
            if selected_ids is None:
                connection.execute("DELETE FROM on_hand_queue")
                connection.execute(
                    "DELETE FROM returned_queue_products WHERE product_id IN (SELECT product_id FROM placements)"
                )
            else:
                connection.executemany(
                    "DELETE FROM on_hand_queue WHERE product_id = ?",
                    ((product_id,) for product_id in selected_ids),
                )
                connection.executemany(
                    "DELETE FROM returned_queue_products WHERE product_id = ?",
                    ((product_id,) for product_id in selected_ids),
                )
        return len(rows)

    def assign_catalog_direct_to_slot(
        self,
        slot_id: int,
        assigned_at: str,
        products: dict[str, tuple[str, str]],
        default_stock: int = 999,
    ) -> int:
        """Import catalog products and assign them directly to slot_id with default_stock."""
        if not products:
            return 0
        if not assigned_at or datetime.fromisoformat(assigned_at).utcoffset() is None:
            raise ValueError("The assignment time must include a timezone.")
        validate_stock_quantity(default_stock)
        self.import_products(products)
        product_ids = tuple(products.keys())
        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if (
                connection.execute(
                    "SELECT 1 FROM slots WHERE slot_id = ?", (slot_id,)
                ).fetchone()
                is None
            ):
                raise KeyError("That shelf address no longer exists.")
            connection.executemany(
                "DELETE FROM placements WHERE product_id = ?",
                ((pid,) for pid in product_ids),
            )
            connection.executemany(
                "DELETE FROM on_hand_queue WHERE product_id = ?",
                ((pid,) for pid in product_ids),
            )
            connection.executemany(
                "DELETE FROM returned_queue_products WHERE product_id = ?",
                ((pid,) for pid in product_ids),
            )
            connection.executemany(
                """
                INSERT INTO placements (product_id, slot_id, stock_qty, assigned_at)
                VALUES (?, ?, ?, ?)
                """,
                ((pid, slot_id, default_stock, assigned_at) for pid in product_ids),
            )
        return len(product_ids)

    def revert_shift_transfer(self, transfer_data: dict[str, Any]) -> int:
        """Atomically undo the latest shift transfer and restore products to their prior state."""
        slot_id = transfer_data.get("slot_id")
        products = transfer_data.get("products", [])
        if not products or slot_id is None:
            return 0
        now_ts = datetime.now().astimezone().isoformat(timespec="seconds")
        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            for item in products:
                pid = item["product_id"]
                # 1. Delete the placement at the target slot
                connection.execute(
                    "DELETE FROM placements WHERE product_id = ? AND slot_id = ?",
                    (pid, slot_id),
                )
                # 2. Restore previous placement if any
                if item.get("prev_placement"):
                    prev_slot_val, prev_stock, prev_assigned = item["prev_placement"]
                    if isinstance(prev_slot_val, str):
                        s_row = connection.execute(
                            "SELECT slot_id FROM slots WHERE slot_name = ?", (prev_slot_val,)
                        ).fetchone()
                        prev_slot_id = s_row["slot_id"] if s_row else None
                    else:
                        prev_slot_id = prev_slot_val
                    if prev_slot_id is not None:
                        connection.execute(
                            """
                            INSERT INTO placements (product_id, slot_id, stock_qty, assigned_at)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(product_id) DO UPDATE SET
                                slot_id = excluded.slot_id,
                                stock_qty = excluded.stock_qty,
                                assigned_at = excluded.assigned_at
                            """,
                            (pid, prev_slot_id, prev_stock, prev_assigned),
                        )
                # 3. Restore to on-hand queue if it was in on-hand
                if item.get("prev_on_hand") is not None or item.get("was_in_on_hand"):
                    stock = item.get("prev_on_hand")
                    connection.execute(
                        """
                        INSERT INTO on_hand_queue (product_id, stock_qty, queued_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(product_id) DO UPDATE SET
                            stock_qty = excluded.stock_qty
                        """,
                        (pid, stock, now_ts),
                    )
                # 4. Restore to returned_queue_products if it was in returned queue
                if item.get("prev_returned") is not None or item.get("was_in_returned"):
                    stock = item.get("prev_returned")
                    connection.execute(
                        """
                        INSERT INTO returned_queue_products (product_id, stock_qty, returned_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(product_id) DO UPDATE SET
                            stock_qty = excluded.stock_qty
                        """,
                        (pid, stock, now_ts),
                    )
                # 5. If product was newly imported into products table by catalog transfer, remove it
                if not item.get("was_in_products", True):
                    connection.execute(
                        "DELETE FROM products WHERE product_id = ?",
                        (pid,),
                    )
        return len(products)

    def move_slot_to_on_hand(
        self,
        slot_id: int,
        queued_at: str,
        product_ids: list[str] | tuple[str, ...] | None = None,
    ) -> int:
        """Move selected slot products, or the complete slot, back to on-hand."""
        if not queued_at or datetime.fromisoformat(queued_at).utcoffset() is None:
            raise ValueError("The on-hand time must include a timezone.")
        selected_ids = (
            None if product_ids is None else tuple(dict.fromkeys(product_ids))
        )
        if selected_ids == ():
            return 0
        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if (
                connection.execute(
                    "SELECT 1 FROM slots WHERE slot_id = ?", (slot_id,)
                ).fetchone()
                is None
            ):
                raise KeyError("That shelf address no longer exists.")
            all_rows = connection.execute(
                "SELECT product_id, stock_qty FROM placements WHERE slot_id = ?",
                (slot_id,),
            ).fetchall()
            if selected_ids is None:
                rows = all_rows
            else:
                rows_by_id = {row["product_id"]: row for row in all_rows}
                missing = [
                    product_id
                    for product_id in selected_ids
                    if product_id not in rows_by_id
                ]
                if missing:
                    raise KeyError(
                        f"Product {missing[0]} is no longer in that shelf address."
                    )
                rows = [rows_by_id[product_id] for product_id in selected_ids]
            if not rows:
                return 0
            connection.executemany(
                """
                INSERT INTO on_hand_queue (product_id, stock_qty, queued_at)
                VALUES (?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    stock_qty = excluded.stock_qty,
                    queued_at = excluded.queued_at
                """,
                ((row["product_id"], row["stock_qty"], queued_at) for row in rows),
            )
            if selected_ids is None:
                connection.execute(
                    "DELETE FROM placements WHERE slot_id = ?", (slot_id,)
                )
            else:
                connection.executemany(
                    "DELETE FROM placements WHERE slot_id = ? AND product_id = ?",
                    ((slot_id, product_id) for product_id in selected_ids),
                )
        return len(rows)

    def update_placement_stock(
        self,
        product_id: str,
        quantity: int,
        *,
        expected_slot_id: int | None = None,
    ) -> None:
        validate_stock_quantity(quantity)
        with closing(self.connect()) as connection, connection:
            if expected_slot_id is None:
                cursor = connection.execute(
                    "UPDATE placements SET stock_qty = ? WHERE product_id = ?",
                    (quantity, product_id),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE placements SET stock_qty = ?
                    WHERE product_id = ? AND slot_id = ?
                    """,
                    (quantity, product_id, expected_slot_id),
                )
            if cursor.rowcount != 1:
                raise KeyError(
                    f"Product {product_id} is no longer in that shelf address."
                )

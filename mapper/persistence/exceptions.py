from __future__ import annotations

import csv
import io
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from mapper.core.common import normalize_search
from utils.barcode_scanner import format_product_id
from .models import validate_stock_quantity

class ExceptionOperations:
    def find_product_locations(self, product_id: str) -> tuple[str, tuple[str, ...]] | None:
        """Find a registered or staged ID and all its saved locations."""
        with closing(self.connect()) as connection:
            name_row = connection.execute(
                """
                SELECT product_name FROM products WHERE product_id = ?
                UNION ALL
                SELECT product_name FROM catalog_products WHERE product_id = ?
                UNION ALL
                SELECT product_name FROM wait_to_update_csv WHERE product_id = ?
                LIMIT 1
                """,
                (product_id, product_id, product_id),
            ).fetchone()
            rows = connection.execute(
                """
                SELECT slots.slot_name FROM slots
                JOIN placements ON placements.slot_id = slots.slot_id
                WHERE placements.product_id = ?
                UNION
                SELECT slots.slot_name FROM slots
                JOIN exception_placements ON exception_placements.slot_id = slots.slot_id
                WHERE exception_placements.product_id = ?
                ORDER BY slot_name COLLATE NOCASE
                """,
                (product_id, product_id),
            ).fetchall()
        if name_row is None and not rows:
            return None
        return (name_row["product_name"] if name_row else product_id,
                tuple(row["slot_name"] for row in rows))

    def get_multi_location_products(self) -> list[tuple[str, str, tuple[str, ...]]]:
        """Group products with two or more distinct saved locations."""
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT saved.product_id, slots.slot_name,
                       COALESCE(products.product_name, catalog_products.product_name, saved.product_id)
                           AS product_name
                FROM (
                    SELECT product_id, slot_id FROM placements
                    UNION
                    SELECT product_id, slot_id FROM exception_placements
                ) AS saved
                JOIN slots ON slots.slot_id = saved.slot_id
                LEFT JOIN products ON products.product_id = saved.product_id
                LEFT JOIN catalog_products ON catalog_products.product_id = saved.product_id
                ORDER BY saved.product_id COLLATE NOCASE, slots.slot_name COLLATE NOCASE
                """
            ).fetchall()
        grouped: dict[str, tuple[str, list[str]]] = {}
        for row in rows:
            entry = grouped.setdefault(row["product_id"], (row["product_name"], []))
            entry[1].append(row["slot_name"])
        return [
            (product_id, name, tuple(locations))
            for product_id, (name, locations) in grouped.items()
            if len(locations) > 1
        ]

    def assign_exception(
        self,
        product_id: str,
        slot_id: int,
        assigned_at: str | None = None,
        stock_qty: int | None = None,
        product_name: str | None = None,
    ) -> str:
        """Assign an existing or unregistered product to an exception slot.
        Stage its CSV and catalog registrations independently.
        Returns the slot_name.
        """
        if stock_qty is not None:
            validate_stock_quantity(stock_qty)
        clean_pid = format_product_id(product_id.strip())
        if not clean_pid:
            raise ValueError("Product ID cannot be empty.")
        if assigned_at is None:
            assigned_at = datetime.now().astimezone().isoformat(timespec="seconds")

        with closing(self.connect()) as connection, connection:
            slot_row = connection.execute(
                "SELECT slot_name FROM slots WHERE slot_id = ?", (slot_id,)
            ).fetchone()
            if not slot_row:
                raise ValueError(f"Slot ID {slot_id} does not exist.")
            slot_name = slot_row["slot_name"]

            existing_product = connection.execute(
                "SELECT product_name FROM products WHERE product_id = ?", (clean_pid,)
            ).fetchone()
            existing_catalog = connection.execute(
                "SELECT product_name FROM catalog_products WHERE product_id = ?", (clean_pid,)
            ).fetchone()
            staged = connection.execute(
                """
                SELECT product_name, MAX(csv_updated) AS csv_updated,
                       MAX(catalog_updated) AS catalog_updated
                FROM wait_to_update_csv WHERE product_id = ?
                GROUP BY product_id
                """,
                (clean_pid,),
            ).fetchone()
            entered_name = (product_name or "").strip()
            resolved_name = (
                entered_name
                or (staged["product_name"] if staged else "")
                or (existing_catalog["product_name"] if existing_catalog else "")
                or (existing_product["product_name"] if existing_product else "")
                or "Exc - added later"
            )
            csv_done = int(staged["csv_updated"]) if staged else 0
            catalog_done = (
                int(staged["catalog_updated"])
                if staged else
                int(existing_catalog is not None and existing_catalog["product_name"] != "Exc - added later")
            )
            if entered_name and existing_catalog and entered_name != existing_catalog["product_name"]:
                catalog_done = 0
            if staged and entered_name and entered_name != staged["product_name"]:
                # A changed name needs to be registered again at both targets.
                connection.execute(
                    """
                    UPDATE wait_to_update_csv
                    SET product_name = ?, csv_updated = 0, catalog_updated = 0
                    WHERE product_id = ?
                    """,
                    (resolved_name, clean_pid),
                )
                csv_done = 0
                catalog_done = 0

            connection.execute(
                """
                INSERT INTO products (product_id, product_name, shortened_name)
                VALUES (?, ?, ?)
                ON CONFLICT (product_id) DO UPDATE SET
                    product_name = CASE WHEN ? THEN excluded.product_name ELSE products.product_name END,
                    shortened_name = CASE WHEN ? THEN excluded.shortened_name ELSE products.shortened_name END
                """,
                (clean_pid, resolved_name, resolved_name, bool(entered_name), bool(entered_name)),
            )

            # Insert or update into exception_placements
            connection.execute(
                """
                INSERT INTO exception_placements (product_id, slot_id, stock_qty, assigned_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (product_id, slot_id) DO UPDATE SET
                    stock_qty = excluded.stock_qty,
                    assigned_at = excluded.assigned_at
                """,
                (clean_pid, slot_id, stock_qty, assigned_at),
            )

            # Keep the staged row after either registration action.
            connection.execute(
                """
                INSERT INTO wait_to_update_csv
                    (product_id, product_name, slot_id, slot_name, csv_updated, catalog_updated)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (product_id, slot_name) DO UPDATE SET
                    product_name = excluded.product_name,
                    slot_id = excluded.slot_id
                """,
                (clean_pid, resolved_name, slot_id, slot_name, csv_done, catalog_done),
            )

        return slot_name

    def get_exception_staging(self) -> list[dict[str, Any]]:
        """Return every staged exception, including fully registered rows."""
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, product_id, product_name, slot_id, slot_name, created_at,
                       csv_updated, catalog_updated
                FROM wait_to_update_csv
                ORDER BY id ASC
                """
            ).fetchall()
        return [
            {
                "id": row["id"],
                "product_id": row["product_id"],
                "product_name": row["product_name"],
                "slot_id": row["slot_id"],
                "slot_name": row["slot_name"],
                "created_at": row["created_at"],
                "csv_updated": bool(row["csv_updated"]),
                "catalog_updated": bool(row["catalog_updated"]),
            }
            for row in rows
        ]

    def get_pending_csv_updates(self) -> list[dict[str, Any]]:
        return [item for item in self.get_exception_staging() if not item["csv_updated"]]

    def update_staged_exception_name(self, product_id: str, product_name: str) -> None:
        """Save a staged name and reopen registrations when that name changes."""
        clean_pid = format_product_id(product_id.strip())
        clean_name = product_name.strip()
        if not clean_name:
            raise ValueError("Product name cannot be empty.")
        with closing(self.connect()) as connection, connection:
            staged = connection.execute(
                "SELECT product_name FROM wait_to_update_csv WHERE product_id = ? LIMIT 1",
                (clean_pid,),
            ).fetchone()
            if staged is None:
                raise ValueError(f"{clean_pid} is no longer in the staged exception list.")
            if staged["product_name"] == clean_name:
                return
            connection.execute(
                """
                UPDATE wait_to_update_csv
                SET product_name = ?, csv_updated = 0, catalog_updated = 0
                WHERE product_id = ?
                """,
                (clean_name, clean_pid),
            )
            connection.execute(
                """
                UPDATE products SET product_name = ?, shortened_name = ?
                WHERE product_id = ?
                """,
                (clean_name, clean_name, clean_pid),
            )

    def add_staged_to_catalog(self, product_ids: list[str] | None = None) -> int:
        """Register selected staged products in the full catalog once."""
        selected = set(product_ids) if product_ids is not None else None
        with closing(self.connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT product_id, product_name FROM wait_to_update_csv
                WHERE catalog_updated = 0 ORDER BY id DESC
                """
            ).fetchall()
            products: dict[str, str] = {}
            for row in rows:
                product_id = row["product_id"]
                if selected is None or product_id in selected:
                    products.setdefault(product_id, row["product_name"])
            if not products:
                return 0
            connection.executemany(
                """
                INSERT INTO catalog_products (product_id, product_name, shortened_name)
                VALUES (?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    product_name = excluded.product_name,
                    shortened_name = excluded.shortened_name,
                    imported_at = CURRENT_TIMESTAMP
                """,
                [(product_id, name, name) for product_id, name in products.items()],
            )
            connection.executemany(
                "UPDATE wait_to_update_csv SET catalog_updated = 1 WHERE product_id = ?",
                [(product_id,) for product_id in products],
            )
        return len(products)

    def wipe_staged_exception(self, product_id: str) -> None:
        """Remove staging, catalog record, and every saved shelf placement."""
        with closing(self.connect()) as connection, connection:
            exists = connection.execute(
                "SELECT 1 FROM wait_to_update_csv WHERE product_id = ? LIMIT 1", (product_id,)
            ).fetchone()
            if exists is None:
                raise ValueError(f"{product_id} is no longer in the staged exception list.")
            connection.execute(
                "DELETE FROM wait_to_update_csv WHERE product_id = ?", (product_id,)
            )
            connection.execute(
                "DELETE FROM catalog_products WHERE product_id = ?", (product_id,)
            )
            connection.execute(
                "DELETE FROM placements WHERE product_id = ?", (product_id,)
            )
            connection.execute(
                "DELETE FROM exception_placements WHERE product_id = ?", (product_id,)
            )

    def clear_pending_csv_updates(self, ids: list[int] | None = None) -> int:
        with closing(self.connect()) as connection, connection:
            if ids is not None:
                if not ids:
                    return 0
                placeholders = ",".join("?" for _ in ids)
                cursor = connection.execute(
                    f"DELETE FROM wait_to_update_csv WHERE id IN ({placeholders})",
                    ids,
                )
            else:
                cursor = connection.execute("DELETE FROM wait_to_update_csv")
            return cursor.rowcount

    def append_pending_to_csv(
        self, csv_path: str | Path, product_ids: list[str] | None = None
    ) -> int:
        """Register each selected pending product in a CSV and keep its staged row."""
        selected = set(product_ids) if product_ids is not None else None
        pending: dict[str, dict[str, Any]] = {}
        for item in self.get_pending_csv_updates():
            if selected is None or item["product_id"] in selected:
                pending[item["product_id"]] = item
        if not pending:
            return 0

        path = Path(csv_path)
        raw = path.read_bytes() if path.exists() else b""
        encoding = "utf-8"
        text_content = ""
        if raw:
            for candidate in ("utf-8-sig", "utf-8", "cp1258", "cp1252"):
                try:
                    text_content = raw.decode(candidate)
                    encoding = candidate
                    break
                except UnicodeDecodeError:
                    continue

        first_line = text_content.splitlines()[0] if text_content.splitlines() else ""
        delimiter = max((";", ",", "\t", "|"), key=first_line.count) if first_line else ";"
        existing_rows = list(csv.reader(io.StringIO(text_content), delimiter=delimiter))
        header_cols = existing_rows[0] if existing_rows else [
            "product_id", "product_name", "shortened_name"
        ]
        if len(header_cols) < 2:
            raise ValueError("The CSV needs separate product ID and product name columns.")

        normalized = [
            "".join(character for character in normalize_search(column) if character.isalnum())
            for column in header_cols
        ]
        id_idx = next(
            (index for index, value in enumerate(normalized)
             if value in {"productid", "productcode", "mahang", "masanpham", "sku", "code"}),
            0,
        )
        name_idx = next(
            (index for index, value in enumerate(normalized)
             if value in {"productname", "tenhang", "tensanpham", "name", "title"}),
            1,
        )
        if id_idx == name_idx:
            raise ValueError("Could not identify different product ID and name columns in the CSV.")
        rows_to_write = existing_rows if existing_rows else [header_cols]
        existing_ids: set[str] = set()
        for row in rows_to_write[1:]:
            if len(row) <= id_idx:
                continue
            product_id = row[id_idx].strip()
            if product_id in pending:
                row.extend([""] * (name_idx + 1 - len(row)))
                row[name_idx] = pending[product_id]["product_name"]
                existing_ids.add(product_id)
        for product_id, item in pending.items():
            if product_id in existing_ids:
                continue
            row = [""] * len(header_cols)
            row[id_idx] = product_id
            row[name_idx] = item["product_name"]
            rows_to_write.append(row)

        output = io.StringIO(newline="")
        newline = "\r\n" if b"\r\n" in raw else "\n"
        writer = csv.writer(output, delimiter=delimiter, lineterminator=newline)
        writer.writerows(rows_to_write)
        payload = output.getvalue().encode(encoding)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(payload)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

        with closing(self.connect()) as connection, connection:
            connection.executemany(
                "UPDATE wait_to_update_csv SET csv_updated = 1 WHERE product_id = ?",
                [(product_id,) for product_id in pending],
            )
        return len(pending)

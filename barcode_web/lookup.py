"""Read current warehouse locations without initializing or migrating its database."""

from contextlib import closing
from pathlib import Path
import sqlite3

from mapper.core.common import exact_product_search_id
from mapper.persistence.exceptions import ExceptionOperations


class WarehouseLookup(ExceptionOperations):
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        # mode=ro fails for missing files instead of creating an empty database.
        with closing(self.connect()) as connection:
            connection.execute("SELECT product_id FROM products LIMIT 0")
            connection.execute("SELECT slot_name FROM slots LIMIT 0")

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=3)
        connection.row_factory = sqlite3.Row
        return connection

    def find(self, barcode: str, *, include_cell_contents: bool = False) -> dict:
        query = barcode.strip()
        tables = ("products", "catalog_products", "wait_to_update_csv", "placements", "exception_placements")
        # Match whole IDs only. The existing resolver prefers literal IDs and
        # rejects collisions between different IDs with the same dashless alias.
        sql = " UNION ".join(
            f"SELECT product_id FROM {table} WHERE product_id = ? COLLATE NOCASE "
            "OR replace(product_id, '-', '') = ? COLLATE NOCASE"
            for table in tables)
        with closing(self.connect()) as connection:
            ids = [row["product_id"] for row in connection.execute(sql, (query, query) * len(tables))]
        product_id = exact_product_search_id(query, ids)
        empty = {"product_id": None, "product_name": "", "locations": []}
        if include_cell_contents:
            empty["cells"] = []
        if product_id is None:
            return {**empty, "status": "ambiguous" if ids else "not_found", "matches": sorted(ids)}
        found = self.find_product_locations(product_id)
        if found is None:
            return {**empty, "status": "not_found"}
        name, locations = found
        result = {"status": "found" if locations else "unassigned", "product_id": product_id,
                  "product_name": name, "locations": list(locations)}
        if include_cell_contents:
            result["cells"] = self.cell_contents(locations)
        return result

    def cell_contents(self, locations: tuple[str, ...]) -> list[dict]:
        """One row per barcode in each cell, including catalog/staged exceptions."""
        cells = {name: {"location": name, "products": []} for name in locations}
        if not cells:
            return []
        placeholders = ", ".join("?" for _ in cells)
        with closing(self.connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT slots.slot_name, saved.product_id,
                       COALESCE(products.product_name, catalog_products.product_name,
                           (SELECT product_name FROM wait_to_update_csv staged
                            WHERE staged.product_id = saved.product_id
                            ORDER BY staged.id LIMIT 1), saved.product_id) AS product_name,
                       CASE WHEN COUNT(saved.stock_qty) = COUNT(*)
                            THEN SUM(saved.stock_qty) END AS stock_qty
                FROM (
                    SELECT product_id, slot_id, stock_qty FROM placements
                    UNION ALL
                    SELECT product_id, slot_id, stock_qty FROM exception_placements
                ) saved
                JOIN slots ON slots.slot_id = saved.slot_id
                LEFT JOIN products ON products.product_id = saved.product_id
                LEFT JOIN catalog_products ON catalog_products.product_id = saved.product_id
                WHERE slots.slot_name IN ({placeholders})
                GROUP BY slots.slot_id, saved.product_id
                ORDER BY saved.product_id COLLATE NOCASE
                """, tuple(cells),
            ).fetchall()
        for row in rows:
            cells[row["slot_name"]]["products"].append({
                "product_id": row["product_id"], "product_name": row["product_name"],
                "stock_qty": row["stock_qty"],
            })
        return list(cells.values())

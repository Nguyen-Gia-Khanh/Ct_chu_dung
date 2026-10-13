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

    def find(self, barcode: str) -> dict:
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
        if product_id is None:
            return {**empty, "status": "ambiguous" if ids else "not_found", "matches": sorted(ids)}
        found = self.find_product_locations(product_id)
        if found is None:
            return {**empty, "status": "not_found"}
        name, locations = found
        return {"status": "found" if locations else "unassigned", "product_id": product_id,
                "product_name": name, "locations": list(locations)}

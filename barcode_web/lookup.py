"""Read current warehouse locations without initializing or migrating its database."""

from contextlib import closing
from pathlib import Path
import re
import sqlite3

from mapper.core.common import normalise_sku
from mapper.persistence.inventory import LOCATION_SQL
from mapper.persistence.exceptions import ExceptionOperations


# Code 39 characters plus '?' for a character the phone could not read.
PARTIAL_BARCODE = re.compile(r"[0-9A-Z. $/+%?-]{1,64}")


class WarehouseLookup(ExceptionOperations):
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        # mode=ro fails for missing files instead of creating an empty database.
        with closing(self.connect()) as connection:
            connection.execute("SELECT product_id FROM catalog_products LIMIT 0")
            connection.execute("SELECT slot_name FROM slots LIMIT 0")

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=3)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.row_factory = sqlite3.Row
        return connection

    def find(self, barcode: str, *, include_cell_contents: bool = False) -> dict:
        query = normalise_sku(barcode)
        with closing(self.connect()) as connection:
            row = connection.execute('SELECT product_id FROM catalog_products WHERE product_id=?',(query,)).fetchone()
        product_id = row[0] if row else None
        empty = {"product_id": None, "product_name": "", "locations": []}
        if include_cell_contents:
            empty["cells"] = []
        if product_id is None:
            return {**empty, "status": "not_found", "matches": []}
        found = self.find_product_locations(product_id)
        if found is None:
            return {**empty, "status": "not_found"}
        name, locations = found
        result = {"status": "found" if locations else "unassigned", "product_id": product_id,
                  "product_name": name, "locations": list(locations)}
        if include_cell_contents:
            result["cells"] = self.cell_contents(locations)
        return result

    def resolve_pattern(self, pattern: str) -> dict:
        """Complete a partly read barcode only when exactly one catalog ID fits; never guess."""
        pattern = pattern.strip().upper()
        unknown = pattern.count("?")
        if (not PARTIAL_BARCODE.fullmatch(pattern) or not 1 <= unknown <= 2
                or len(pattern) - unknown < 4):
            raise ValueError("Send 4+ read characters with one or two '?' placeholders.")
        query = normalise_sku(pattern)
        # '%' is a Code 39 character: escape LIKE wildcards, then re-check each row exactly.
        like = query.replace("!", "!!").replace("%", "!%").replace("_", "!_").replace("?", "_")
        exact = re.compile(re.escape(query).replace(r"\?", "."))
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT product_id FROM catalog_products"
                " WHERE length(product_id)=? AND product_id LIKE ? ESCAPE '!' LIMIT 3",
                (len(query), like)).fetchall()
        matches = sorted({row[0] for row in rows if exact.fullmatch(row[0])})
        if len(matches) == 1:
            return {"status": "unique", "product_id": matches[0]}
        return {"status": "ambiguous" if matches else "none"}

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
                       COALESCE(c.full_name,c.brand_name,saved.product_id) AS product_name,
                       saved.stock_qty
                FROM ({LOCATION_SQL}) saved
                JOIN slots ON slots.slot_id = saved.slot_id
                JOIN catalog_products c ON c.product_id=saved.product_id
                WHERE slots.slot_name IN ({placeholders})
                ORDER BY saved.product_id COLLATE NOCASE
                """, tuple(cells),
            ).fetchall()
        for row in rows:
            cells[row["slot_name"]]["products"].append({
                "product_id": row["product_id"], "product_name": row["product_name"],
                "stock_qty": row["stock_qty"],
            })
        return list(cells.values())

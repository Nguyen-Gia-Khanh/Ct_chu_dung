"""Catalog names and the working product list (hot sellers)."""

from __future__ import annotations

from contextlib import closing

from mapper.core.common import UTC_DEFAULT
from .shared import IN_IDS, PRODUCT_NAME_SQL, ids_param, normalize_records, tuples

UPSERT_HOT_SELLER_NAMES = f"""INSERT INTO catalog_products(product_id, full_name, brand_name) VALUES (?, ?, ?)
    ON CONFLICT(product_id) DO UPDATE SET full_name=excluded.full_name,
    brand_name=COALESCE(excluded.brand_name, catalog_products.brand_name), imported_at={UTC_DEFAULT}"""
UPSERT_HOT_SELLER = f"""INSERT INTO hot_sellers(product_id) VALUES (?)
    ON CONFLICT(product_id) DO UPDATE SET imported_at={UTC_DEFAULT}"""
UPSERT_CATALOG_NAMES = f"""INSERT INTO catalog_products(product_id, brand_name, full_name) VALUES (?, ?, ?)
    ON CONFLICT(product_id) DO UPDATE SET brand_name=excluded.brand_name,
    full_name=COALESCE(excluded.full_name, catalog_products.full_name), imported_at={UTC_DEFAULT}"""


class CatalogOperations:
    def import_products(self, records: dict) -> tuple[int, int]:
        """Import working-product membership and translated catalog names; returns (new, updated)."""
        records = normalize_records(records)
        with closing(self.connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            existing = connection.execute(f'SELECT COUNT(*) FROM hot_sellers WHERE product_id {IN_IDS}',
                                          (ids_param(records),)).fetchone()[0]
            connection.executemany(UPSERT_HOT_SELLER_NAMES, [(pid, full, brand) for pid, (full, brand) in records.items()])
            connection.executemany(UPSERT_HOT_SELLER, [(pid,) for pid in records])
        return len(records) - existing, existing

    def import_catalog_products(self, records: dict) -> tuple[int, int]:
        """Honda CSV supplies brand_name; a second mapped column can supply full_name."""
        records = normalize_records(records)
        with closing(self.connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            existing = connection.execute(f'SELECT COUNT(*) FROM catalog_products WHERE product_id {IN_IDS}',
                                          (ids_param(records),)).fetchone()[0]
            connection.executemany(UPSERT_CATALOG_NAMES, [(pid, brand, full) for pid, (brand, full) in records.items()])
        return len(records) - existing, existing

    def get_products(self) -> list[tuple[str, str]]:
        return [(pid, name) for pid, name, _brand in self.get_product_records()]

    def get_product_records(self) -> list[tuple[str, str, str]]:
        """Working products as (id, display name, brand)."""
        with closing(self.connect()) as connection:
            return tuples(connection,
                f"""SELECT h.product_id, {PRODUCT_NAME_SQL}, COALESCE(c.brand_name,'')
                    FROM hot_sellers h JOIN catalog_products c USING(product_id)
                    ORDER BY h.product_id COLLATE NOCASE""")

    def get_catalog_products(self) -> list[tuple[str, str, str]]:
        """Every catalog product as (id, display name, brand)."""
        with closing(self.connect()) as connection:
            return tuples(connection,
                f"""SELECT product_id, {PRODUCT_NAME_SQL}, COALESCE(brand_name,'')
                    FROM catalog_products c ORDER BY product_id COLLATE NOCASE""")

    def get_catalog_rows(self, product_ids) -> list[tuple[str, str, str]]:
        """Catalog rows for just these IDs, for incremental search-index updates."""
        with closing(self.connect()) as connection:
            return tuples(connection,
                f"""SELECT product_id, {PRODUCT_NAME_SQL}, COALESCE(brand_name,'')
                    FROM catalog_products c WHERE product_id {IN_IDS}""", (ids_param(product_ids),))

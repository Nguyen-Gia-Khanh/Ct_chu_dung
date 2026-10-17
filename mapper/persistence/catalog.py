from __future__ import annotations

from contextlib import closing
from mapper.core.common import clean_product_name, normalise_sku, UTC_DEFAULT


class CatalogOperations:
    def import_products(self, records: dict) -> tuple[int, int]:
        """Import working-product membership and translated catalog names."""
        records = self._normalise_records(records)
        with closing(self.connect()) as connection, connection:
            existing = {row[0] for row in connection.execute('SELECT product_id FROM hot_sellers')} & records.keys()
            for pid, (full_name, brand_name) in records.items():
                connection.execute(
                    f"""INSERT INTO catalog_products(product_id, full_name, brand_name) VALUES (?, ?, ?)
                        ON CONFLICT(product_id) DO UPDATE SET full_name=excluded.full_name,
                        brand_name=COALESCE(excluded.brand_name,catalog_products.brand_name),
                        imported_at={UTC_DEFAULT}""", (pid, full_name, brand_name))
                connection.execute(
                    f"""INSERT INTO hot_sellers(product_id) VALUES (?) ON CONFLICT(product_id)
                        DO UPDATE SET imported_at={UTC_DEFAULT}""", (pid,))
                connection.execute('INSERT OR REPLACE INTO queue_origins(product_id,snapshot) VALUES (?, ?)',
                                   (pid, '{"was_in_products": true}'))
        return len(records) - len(existing), len(existing)

    @staticmethod
    def _normalise_records(records):
        normalised = {}
        for raw, value in records.items():
            pid = normalise_sku(raw)
            if not pid:
                raise ValueError('Product ID cannot be empty.')
            names = value if isinstance(value, tuple) else (value, '')
            cleaned = tuple(clean_product_name(name) for name in names)
            if pid in normalised and normalised[pid] != cleaned:
                raise ValueError(f'Conflicting imported rows for {pid}.')
            normalised[pid] = cleaned
        return normalised

    def get_products(self) -> list[tuple[str, str]]:
        return [(pid, name) for pid, name, _brand in self.get_product_records()]

    def get_product_records(self) -> list[tuple[str, str, str]]:
        with closing(self.connect()) as connection:
            return [tuple(row) for row in connection.execute(
                """SELECT h.product_id, COALESCE(c.full_name,c.brand_name,h.product_id),
                          COALESCE(c.brand_name,'')
                   FROM hot_sellers h JOIN catalog_products c USING(product_id)
                   ORDER BY h.product_id COLLATE NOCASE""")]

    def import_catalog_products(self, records: dict) -> tuple[int, int]:
        """Honda CSV supplies brand_name; a second mapped column can supply full_name."""
        records = self._normalise_records(records)
        with closing(self.connect()) as connection, connection:
            existing = {row[0] for row in connection.execute('SELECT product_id FROM catalog_products')} & records.keys()
            for pid, (brand_name, full_name) in records.items():
                connection.execute(
                    f"""INSERT INTO catalog_products(product_id, brand_name, full_name) VALUES (?, ?, ?)
                        ON CONFLICT(product_id) DO UPDATE SET brand_name=excluded.brand_name,
                        full_name=COALESCE(excluded.full_name,catalog_products.full_name),
                        imported_at={UTC_DEFAULT}""", (pid, brand_name, full_name))
        return len(records) - len(existing), len(existing)

    def get_catalog_products(self) -> list[tuple[str, str, str]]:
        with closing(self.connect()) as connection:
            return [tuple(row) for row in connection.execute(
                """SELECT product_id, COALESCE(full_name,brand_name,product_id), COALESCE(brand_name,'')
                   FROM catalog_products ORDER BY product_id COLLATE NOCASE""")]

    def get_display_catalog_products(self) -> list[tuple[str, str, str]]:
        return self.get_catalog_products()

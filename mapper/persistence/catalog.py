from __future__ import annotations

from contextlib import closing


class CatalogOperations:
    def import_products(
        self, records: dict[str, str | tuple[str, str]]
    ) -> tuple[int, int]:
        if not records:
            return 0, 0

        with closing(self.connect()) as connection, connection:
            existing = {
                row["product_id"]
                for row in connection.execute(
                    f"SELECT product_id FROM products WHERE product_id IN ({','.join('?' for _ in records)})",
                    tuple(records),
                )
            }
            connection.executemany(
                """
                INSERT INTO products (product_id, product_name, shortened_name)
                VALUES (?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    product_name = excluded.product_name,
                    shortened_name = excluded.shortened_name,
                    imported_at = CURRENT_TIMESTAMP
                """,
                [
                    (product_id, value[0], value[1] or value[0])
                    if isinstance(value, tuple)
                    else (product_id, value, value)
                    for product_id, value in records.items()
                ],
            )
        return len(records) - len(existing), len(existing)

    def get_products(self) -> list[tuple[str, str]]:
        with closing(self.connect()) as connection, connection:
            rows = connection.execute(
                "SELECT product_id, product_name FROM products ORDER BY product_id COLLATE NOCASE"
            ).fetchall()
        return [(row["product_id"], row["product_name"]) for row in rows]

    def get_product_records(self) -> list[tuple[str, str, str]]:
        """Return working-queue products with every searchable name field."""
        with closing(self.connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT product_id, product_name, shortened_name
                FROM products
                ORDER BY product_id COLLATE NOCASE
                """
            ).fetchall()
        return [
            (row["product_id"], row["product_name"], row["shortened_name"])
            for row in rows
        ]

    def import_catalog_products(
        self, records: dict[str, tuple[str, str]]
    ) -> tuple[int, int]:
        """Upsert the separate reference catalog without changing the warehouse queue."""
        if not records:
            return 0, 0

        with closing(self.connect()) as connection, connection:
            existing = {
                row["product_id"]
                for row in connection.execute("SELECT product_id FROM catalog_products")
                if row["product_id"] in records
            }
            connection.executemany(
                """
                INSERT INTO catalog_products (product_id, product_name, shortened_name)
                VALUES (?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    product_name = excluded.product_name,
                    shortened_name = excluded.shortened_name,
                    imported_at = CURRENT_TIMESTAMP
                """,
                [
                    (product_id, product_name, shortened_name)
                    for product_id, (product_name, shortened_name) in records.items()
                ],
            )
        return len(records) - len(existing), len(existing)

    def get_catalog_products(self) -> list[tuple[str, str, str]]:
        with closing(self.connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT product_id, product_name, shortened_name
                FROM catalog_products
                ORDER BY product_id COLLATE NOCASE
                """
            ).fetchall()
        return [
            (row["product_id"], row["product_name"], row["shortened_name"])
            for row in rows
        ]

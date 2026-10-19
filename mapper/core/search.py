"""In-memory product search shared by every product list and both desktop UIs."""

from __future__ import annotations

import heapq
from collections.abc import Callable, Iterable

from mapper.core.common import MAX_VISIBLE_PRODUCTS, normalize_search, normalize_sku, product_search_text


def search_key(raw_query: str) -> str:
    """Typed or scanned text in the same spelling as the cached search text."""
    return normalize_search(normalize_sku(raw_query))


class ProductIndex:
    """(product_id, name, brand) rows with their search text computed once per change."""

    def __init__(self, rows: Iterable[tuple[str, str, str]] = ()):
        self.names: dict[str, tuple[str, str]] = {}
        self._text: dict[str, str] = {}
        self.update(rows)

    def __len__(self) -> int:
        return len(self.names)

    def __contains__(self, product_id: object) -> bool:
        return product_id in self.names

    def __iter__(self):
        return iter(self.names)

    def update(self, rows: Iterable[tuple[str, str, str]]) -> None:
        for product_id, name, brand in rows:
            self.names[product_id] = (name, brand)
            self._text[product_id] = product_search_text(product_id, name, brand)

    def remove(self, product_ids: Iterable[str]) -> None:
        for product_id in product_ids:
            self.names.pop(product_id, None)
            self._text.pop(product_id, None)

    def name(self, product_id: str) -> str:
        return self.names[product_id][0]

    def exact_id(self, raw_query: str) -> str | None:
        product_id = normalize_sku(raw_query)
        return product_id if product_id in self.names else None

    def matches(
        self, raw_query: str, *, ids: Iterable[str] | None = None,
        also: Callable[[str, str], bool] | None = None,
    ) -> list[str]:
        """IDs whose SKU or names contain the query; `also(id, key)` can admit extra matches."""
        pool = self.names if ids is None else ids
        key = search_key(raw_query)
        if not key:
            return list(pool)
        text = self._text
        return [pid for pid in pool if key in text.get(pid, '') or (also is not None and also(pid, key))]

    @staticmethod
    def top(
        product_ids: Iterable[str], raw_query: str, *, limit: int = MAX_VISIBLE_PRODUCTS,
        before: Callable[[str], object] | None = None, after: Callable[[str], object] | None = None,
    ) -> list[str]:
        """The first `limit` IDs: `before` groups, then the exact ID, then `after` groups, then by ID."""
        exact = normalize_sku(raw_query)

        def rank(pid: str) -> tuple:
            return (before(pid) if before else 0, pid != exact, after(pid) if after else 0, pid.casefold())

        return heapq.nsmallest(limit, product_ids, key=rank)

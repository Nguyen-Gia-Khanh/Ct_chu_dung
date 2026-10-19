"""Resolve typed or scanned text to a shelf cell: product ID, then location ID, then shelf name."""

from __future__ import annotations

from dataclasses import dataclass, field

from mapper.core.common import normalize_search, normalize_sku
from mapper.persistence.models import SlotAddress


@dataclass(frozen=True)
class CellLookup:
    address: SlotAddress | None = None                         # an exact cell
    shelves: list[tuple[int, str, str, str]] = field(default_factory=list)  # shelf-name matches

    @property
    def shelf_id(self) -> int | None:
        if self.address is not None:
            return self.address.shelf_id
        return self.shelves[0][0] if len(self.shelves) == 1 else None


def find_cell(db, raw_query: str, shelves: list[tuple[int, str, str, str]] | None = None) -> CellLookup:
    """A product's primary cell, an exact location ID, or the shelves whose name matches."""
    raw_query = raw_query.strip()
    if not raw_query:
        return CellLookup()
    query = normalize_sku(raw_query)
    location = db.get_product_location(query)
    if location is not None:
        return CellLookup(db.get_slot_in_shelf(location.shelf_id, location.row_number, location.slot_number))
    # Location IDs keep their dashes, which SKU normalization removes.
    address = db.get_slot_by_name(raw_query) or (db.get_slot_by_name(query) if query != raw_query else None)
    if address is not None:
        return CellLookup(address)
    key = normalize_search(raw_query)
    return CellLookup(shelves=[
        shelf for shelf in (db.list_shelves() if shelves is None else shelves)
        if key in normalize_search(f"{shelf[1]} {shelf[2]} {shelf[3]} floor {shelf[1]} side {shelf[2]} shelf {shelf[3]}")
    ])

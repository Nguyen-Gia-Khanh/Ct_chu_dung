"""SQLite storage for products, shelves, persistent on-hand work, and placements."""

from __future__ import annotations

from dataclasses import dataclass

from mapper.core.common import MAX_STOCK


class LayoutConflictError(ValueError):
    pass


def validate_stock_quantity(quantity: int | None) -> None:
    if type(quantity) is not int or not 0 <= quantity <= MAX_STOCK:
        raise ValueError(f"Stock quantity must be a whole number from 0 to {MAX_STOCK:,}.")


@dataclass(frozen=True)
class Placement:
    slot_name: str
    stock_qty: int | None
    assigned_at: str | None


@dataclass(frozen=True)
class ProductLocation:
    shelf_id: int
    row_number: int
    slot_number: int
    placement: Placement


@dataclass(frozen=True)
class OnHandProduct:
    product_id: str
    stock_qty: int | None
    queued_at: str


@dataclass(frozen=True)
class SlotAddress:
    slot_id: int
    shelf_id: int
    floor: str
    side: str
    shelf_code: str
    row_number: int
    slot_number: int
    slot_name: str

"""Tab 2 assignment rules: normal assignment, Shift ("whole mode") transfers, and their revert."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from mapper.core.common import iso_timestamp

SHIFT_DEFAULT_STOCK = 999      # stock recorded for products moved without a count
SHIFT_CONFIRM_CLICKS = 3       # presses needed before a multi-product Shift transfer
SHIFT_CONFIRM_SECONDS = 3      # the presses must happen within this window
SHIFT_PREFIX_LENGTH = 5        # a queue Shift transfer moves one product family only


def shift_prefix_error(product_ids: Iterable[str]) -> str | None:
    """Why a queue Shift transfer is refused, or None when every SKU shares the family prefix."""
    prefixes = {pid[:SHIFT_PREFIX_LENGTH] for pid in product_ids}
    if len(prefixes) != 1 or len(next(iter(prefixes))) < SHIFT_PREFIX_LENGTH:
        return f"Cannot transfer: Products in queue must share the same first {SHIFT_PREFIX_LENGTH} characters."
    return None


def catalog_shift_error(product_ids: list[str]) -> str | None:
    if len(product_ids) != 1:
        return f"Cannot transfer: Catalog shift transfer only affects 1 product ID (selected {len(product_ids)})."
    return None


def needs_shift_confirmation(product_count: int) -> bool:
    return product_count > 1


def assign_products(db, slot_id: int, records: dict[str, tuple[str, str]], quantities: dict[str, int]) -> int:
    """Normal assignment with the counted stock of every product; saved immediately."""
    return db.assign_catalog_direct_to_slot(slot_id, iso_timestamp(), records, quantities=quantities)


def shift_transfer(db, slot_id: int, records: dict[str, tuple[str, str]]) -> tuple[int, dict[str, Any]]:
    """Move products straight to a cell keeping known stock (999 when uncounted).
    Returns (moved, revert data) so the latest transfer can be undone."""
    revert = db.capture_shift_transfer(records, slot_id)
    moved = db.assign_catalog_direct_to_slot(slot_id, iso_timestamp(), records, default_stock=SHIFT_DEFAULT_STOCK)
    return moved, revert


def assign_on_hand(db, slot_id: int, product_ids: list[str] | None) -> tuple[int, dict[str, Any] | None]:
    """Assign selected on-hand products, or all of them (revertible) when product_ids is None."""
    revert = None
    if product_ids is None:
        revert = db.capture_shift_transfer(db.get_on_hand_products(), slot_id)
    return db.assign_on_hand_to_slot(slot_id, iso_timestamp(), product_ids), revert


def location_status(product_id: str | None, *, on_hand=None, placement=None) -> tuple[str, bool]:
    """Search-bar status text for one exact SKU and whether it already has a place."""
    if product_id is None:
        return "", False
    if on_hand is not None:
        quantity = on_hand.stock_qty if on_hand.stock_qty is not None else "Unknown"
        return f"In on-hand queue · stock {quantity}", True
    if placement is not None:
        return f"Already at {placement.slot_name}", True
    return "Not in", False

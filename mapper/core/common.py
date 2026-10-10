"""Shared naming rules and paths. Row numbers always count from the ground up."""

from __future__ import annotations

import re
import sys
import unicodedata
from collections.abc import Iterable
from pathlib import Path


APP_TITLE = "Warehouse Shelf Mapper"
MAX_VISIBLE_PRODUCTS = 750


def application_directory() -> Path:
    """Return the project root, or the directory of a packaged executable."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def data_directory() -> Path:
    """Local databases and generated files live outside the source packages."""
    return application_directory() / "data"


def default_database_path() -> Path:
    """Use the current database location, including an unmigrated root database."""
    path = data_directory() / "warehouse_locations.db"
    old_paths = [application_directory() / name for name in ("warehouse_locations.db", "warehouse.db")]
    present_old_paths = [old_path for old_path in old_paths if old_path.exists()]
    if len(present_old_paths) > 1 or (path.exists() and present_old_paths):
        raise RuntimeError(
            "Multiple warehouse databases exist. Pass --db to select one explicitly."
        )
    if present_old_paths:
        return present_old_paths[0]
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def normalize_search(value: str) -> str:
    """Case- and accent-insensitive search, useful for Vietnamese names."""
    decomposed = unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def product_search_text(
    product_id: str, name: str, shortened_name: str = "", search_id: str | None = None,
) -> str:
    """Cache both ID spellings in one searchable string when products load/change."""
    search_id = product_id.replace("-", "") if search_id is None else search_id
    text = f"{product_id} {name} {shortened_name}"
    if search_id != product_id:
        text += f" {search_id}"
    return normalize_search(text)


def exact_product_search_id(query: str, product_ids: Iterable[str]) -> str | None:
    """Resolve visible results, preserving literal IDs and rejecting alias collisions."""
    query = query.casefold()
    aliases = set()
    for product_id in product_ids:
        folded = product_id.casefold()
        if folded == query:
            return product_id
        if folded.replace("-", "") == query:
            aliases.add(product_id)
    return next(iter(aliases)) if len(aliases) == 1 else None


def clean_location_segment(value: str) -> str:
    value = normalize_search(value).strip().upper()
    value = re.sub(r"\s+", "-", value)
    return re.sub(r"[^A-Z0-9_-]", "", value)


def make_slot_name(
    floor: str, shelf_code: str, row_number: int, slot_number: int, *, side: str = "1",
) -> str:
    """Example: floor 1, side 1, shelf A, row 8, cell 10 -> L1-1A8-10."""
    floor_code = clean_location_segment(floor)
    if not re.fullmatch(r"L[0-9]+", floor_code):
        floor_code = f"L{floor_code}"
    return f"{floor_code}-{clean_location_segment(side)}{clean_location_segment(shelf_code)}{row_number}-{slot_number}"

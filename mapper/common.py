"""Shared naming rules and paths. Row numbers always count from the ground up."""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path


APP_TITLE = "Warehouse Shelf Mapper"
MAX_VISIBLE_PRODUCTS = 750


def application_directory() -> Path:
    """Keep the database beside the script (or beside a packaged .exe)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def normalize_search(value: str) -> str:
    """Case- and accent-insensitive search, useful for Vietnamese names."""
    decomposed = unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
    return "".join(character for character in decomposed if not unicodedata.combining(character))


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

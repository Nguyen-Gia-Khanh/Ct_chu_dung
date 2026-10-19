"""Shared naming rules and paths. Row numbers always count from the ground up."""

from __future__ import annotations

import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path


APP_TITLE = "Warehouse Shelf Mapper"
MAX_VISIBLE_PRODUCTS = 750
MAX_STOCK = 2**63 - 1  # SQLite INTEGER limit
UTC_DEFAULT = "(strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))"
VIETNAM_TIME = timezone(timedelta(hours=7))
EXCEL_ERRORS = frozenset({'#N/A', '#VALUE!', '#REF!', '#DIV/0!', '#NAME?', '#NUM!', '#NULL!', '#SPILL!', '#CALC!'})


def normalize_sku(value: object) -> str:
    """The one stored and searched SKU spelling, including scanner/import input."""
    return '' if value is None else str(value).strip().upper().replace('-', '').replace(' ', '')


def clean_product_name(value: str | None) -> str | None:
    text = str(value).strip() if value is not None else ''
    return text if text and text.upper() not in EXCEL_ERRORS else None


def iso_timestamp(value: str | None = None, *, legacy_utc: bool = False) -> str:
    moment = datetime.fromisoformat(value) if value is not None else datetime.now(timezone.utc)
    if moment.utcoffset() is None:
        if not legacy_utc:
            raise ValueError('The time must include a timezone.')
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec='seconds')


def vietnam_time(value: str | None) -> str:
    if not value:
        return ''
    return datetime.fromisoformat(iso_timestamp(value, legacy_utc=True)).astimezone(
        VIETNAM_TIME
    ).isoformat(sep=' ', timespec='seconds')


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


# Combining-mark blocks; Vietnamese tone and vowel marks are all in U+0300-U+036F.
_COMBINING_MARKS = re.compile(r'[̀-ͯ᪰-᫿᷀-᷿⃐-⃿︠-︯]')
_LOCATION_SEPARATORS = re.compile(r'[,;|\n]+')


def normalize_search(value: str) -> str:
    """Case- and accent-insensitive search, useful for Vietnamese names."""
    folded = value.casefold()
    if folded.isascii():
        return folded
    return _COMBINING_MARKS.sub('', unicodedata.normalize("NFD", folded.replace("đ", "d")))


# plain_header() spellings of spreadsheet columns, most specific first.
ID_HEADERS = ("mahang", "masanpham", "masp", "productid", "productcode", "sku", "itemcode", "code")
NAME_HEADERS = ("fullname", "productname", "tenhang", "tensanpham", "name", "title")
LOCATION_HEADERS = ("vitri", "vitrikho", "vitriluutru", "vitriluutrukho", "locationid", "location",
                    "warehouselocation", "shelflocation", "shelf")


def plain_header(value: object) -> str:
    """Spreadsheet header comparison key: accent-free lowercase letters and digits only."""
    return re.sub(r'[^a-z0-9]', '', normalize_search(unicodedata.normalize('NFKC', str(value or ''))))


def split_locations(value: object) -> tuple[str, ...]:
    """One rule for location lists in cells, exports, and uploads; order kept, duplicates dropped."""
    if value is None:
        return ()
    parts = _LOCATION_SEPARATORS.split(value) if isinstance(value, str) else value
    return tuple(dict.fromkeys(part.strip() for part in parts if part and part.strip()))


@lru_cache(maxsize=None)
def product_search_text(
    product_id: str, name: str | None, brand_name: str | None = "",
) -> str:
    """SKU and both catalog names in search spelling; memoized because every product
    list rebuilds its index from the same rows."""
    return normalize_search(normalize_sku(f'{product_id} {name or ""} {brand_name or ""}'))


def exact_product_search_id(query: str, product_ids: Iterable[str]) -> str | None:
    """Resolve user input to a canonical SKU among the visible results."""
    query = normalize_sku(query)
    matches = {pid for pid in product_ids if normalize_sku(pid) == query}
    return next(iter(matches)) if len(matches) == 1 else None


def clean_location_segment(value: str) -> str:
    value = normalize_search(value).strip().upper()
    value = re.sub(r"\s+", "-", value)
    return re.sub(r"[^A-Z0-9_-]", "", value)


def shelf_prefix(floor: str, shelf_code: str, *, side: str = "1") -> str:
    """The part of every location ID shared by one shelf: floor 1, side 1, shelf A -> L1-1A."""
    floor_code = clean_location_segment(floor)
    if not re.fullmatch(r"L[0-9]+", floor_code):
        floor_code = f"L{floor_code}"
    return f"{floor_code}-{clean_location_segment(side)}{clean_location_segment(shelf_code)}"


def make_slot_name(
    floor: str, shelf_code: str, row_number: int, slot_number: int, *, side: str = "1",
) -> str:
    """Example: floor 1, side 1, shelf A, row 8, cell 10 -> L1-1A8-10."""
    return f"{shelf_prefix(floor, shelf_code, side=side)}{row_number}-{slot_number}"

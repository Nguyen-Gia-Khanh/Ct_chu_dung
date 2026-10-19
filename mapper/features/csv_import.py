"""CSV reading, product-row validation, and writing names back into a product CSV.

The interactive column-mapping dialogs live in the UI packages.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from mapper.core.common import ID_HEADERS, NAME_HEADERS, clean_product_name, normalize_sku, plain_header

ENCODINGS = ("utf-8-sig", "cp1258", "cp1252")
DELIMITERS = ",;\t|"


@dataclass
class CSVData:
    headers: list[str]
    rows: list[list[str]]


@dataclass
class PreparedImport:
    """Rows ready for import_products/import_catalog_products plus the summary counts."""
    records: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)
    skipped: int = 0
    duplicates: int = 0


def _decode(raw: bytes) -> tuple[str, str]:
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("The CSV encoding could not be read. Export it as UTF-8 CSV and try again.")


def _dialect(text: str) -> type[csv.Dialect] | csv.Dialect:
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=DELIMITERS)
    except csv.Error:
        # Short product rows can defeat sniffing; the header line still names the delimiter.
        header = next((line for line in sample.splitlines() if line.strip()), "")
        delimiter = max(DELIMITERS, key=header.count)
        if not header.count(delimiter):
            return csv.excel

        class HeaderDialect(csv.excel):
            pass
        HeaderDialect.delimiter = delimiter
        return HeaderDialect


def read_csv(path: Path) -> CSVData:
    text, _encoding = _decode(path.read_bytes())
    rows = [row for row in csv.reader(io.StringIO(text), _dialect(text)) if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise ValueError("The CSV needs a header and at least one product row.")
    return CSVData(headers=[header.strip() for header in rows[0]], rows=rows[1:])


# plain_header() spellings, most specific first.
_ID_COLUMNS = ("productid", "productcode", "sku", "maso", "mahang", "code", "id")
_FULL_NAME_COLUMNS = ("fullname", "tentiengviet", "productname", "itemname", "name", "description")
_BRAND_NAME_COLUMNS = ("brandname", "tenhonda", "hondaname")


def suggest_columns(headers: list[str], *, catalog: bool) -> tuple[int, int, int]:
    """Best guess of (product ID, primary name, optional second name or -1) columns.
    Working-product CSVs lead with the Vietnamese full name; catalog CSVs with the brand name."""
    keys = [plain_header(header) for header in headers]

    def find(candidates, fallback):
        return next((keys.index(key) for key in candidates if key in keys), fallback)

    id_index = find(_ID_COLUMNS, 0)
    primary = _BRAND_NAME_COLUMNS + ("productname", "name") if catalog else _FULL_NAME_COLUMNS
    name_index = find(primary, 1 if len(headers) > 1 else 0)
    other_index = find(_FULL_NAME_COLUMNS if catalog else _BRAND_NAME_COLUMNS, -1)
    return id_index, name_index, -1 if other_index in (id_index, name_index) else other_index


def prepare_import(data: CSVData, id_index: int, name_index: int, second_name_index: int = -1) -> PreparedImport:
    """Normalize SKUs, skip blank or short rows, and reject SKUs that collide with different names."""
    prepared = PreparedImport()
    source_codes: dict[str, str] = {}
    required_index = max(id_index, name_index, second_name_index)
    for row in data.rows:
        if len(row) <= required_index:
            prepared.skipped += 1
            continue
        product_id = normalize_sku(row[id_index])
        if not product_id or not row[name_index].strip():
            prepared.skipped += 1
            continue
        names = (clean_product_name(row[name_index]),
                 clean_product_name(row[second_name_index]) if second_name_index >= 0 else None)
        if product_id in prepared.records:
            prepared.duplicates += 1
            if source_codes[product_id] != row[id_index].strip() and prepared.records[product_id] != names:
                raise ValueError(f'CSV rows normalize to {product_id} with different names.')
        prepared.records[product_id] = names
        source_codes[product_id] = row[id_index].strip()
    if not prepared.records:
        raise ValueError("No valid product ID/name rows were found.")
    return prepared


def write_product_names(path: Path | str, names: dict[str, str]) -> None:
    """Set each product's name in a product CSV, adding missing rows; encoding, delimiter and
    line endings of an existing file are kept. The file is replaced atomically."""
    path = Path(path)
    raw = path.read_bytes() if path.exists() else b""
    text, encoding = _decode(raw) if raw else ("", "utf-8")
    delimiter = _dialect(text).delimiter if text.strip() else ";"
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter)) or [["product_id", "full_name", "brand_name"]]
    header = rows[0]
    if len(header) < 2:
        raise ValueError("The CSV needs separate product ID and product name columns.")
    keys = [plain_header(column) for column in header]
    id_index = next((index for index, key in enumerate(keys) if key in ID_HEADERS), 0)
    name_index = next((index for index, key in enumerate(keys) if key in NAME_HEADERS), 1)
    if id_index == name_index:
        raise ValueError("Could not identify different product ID and name columns in the CSV.")

    written: set[str] = set()
    for row in rows[1:]:
        if len(row) <= id_index:
            continue
        product_id = row[id_index] = normalize_sku(row[id_index])
        if product_id in names:
            row.extend([""] * (name_index + 1 - len(row)))
            row[name_index] = names[product_id]
            written.add(product_id)
    for product_id, name in names.items():
        if product_id not in written:
            row = [""] * len(header)
            row[id_index], row[name_index] = product_id, name
            rows.append(row)

    output = io.StringIO(newline="")
    csv.writer(output, delimiter=delimiter, lineterminator="\r\n" if b"\r\n" in raw else "\n").writerows(rows)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(output.getvalue().encode(encoding))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = ["CSVData", "PreparedImport", "prepare_import", "read_csv", "suggest_columns", "write_product_names"]

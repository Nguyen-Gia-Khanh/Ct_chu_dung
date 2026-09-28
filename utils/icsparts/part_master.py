from __future__ import annotations

import json
import math
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
from bs4 import BeautifulSoup

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mapper.core.common import data_directory
from utils.icsparts.common import clean_text, get_session, is_icsparts_url

# ============================================================
# CONFIG
# ============================================================

MASTER_URL = "https://icsparts.vn/danh-muc/ma-phu-tung/"

# Workbook created by scraper #1.
#
# You normally DO NOT need to paste any directory here.
# Script #2 searches automatically in:
#   1) the project's data/icsparts folder
#   2) the existing icsparts_scrape/icsparts_output folder
#   3) the same folder as this .py file or its icsparts_output child
#   4) the current terminal folder or its icsparts_output child
#
# Both .xlsx and .xlsm are accepted.
# Set this only if you deliberately keep the workbook somewhere else.
EXCEL_PATH_OVERRIDE: str | None = None

SCRIPT_DIR = Path(__file__).resolve().parent


def resolve_excel_path() -> Path:
    if EXCEL_PATH_OVERRIDE:
        return Path(EXCEL_PATH_OVERRIDE).expanduser().resolve()

    names = (
        "icsparts_catalog_data.xlsx",
        "icsparts_catalog_data.xlsm",
    )

    bases = (
        data_directory() / "icsparts",
        SCRIPT_DIR.parents[1] / "icsparts_scrape" / "icsparts_output",
        SCRIPT_DIR,
        SCRIPT_DIR / "icsparts_output",
        Path.cwd(),
        Path.cwd() / "icsparts_output",
    )

    seen = set()

    for base in bases:
        for name in names:
            candidate = (base / name).resolve()

            if candidate in seen:
                continue
            seen.add(candidate)

            if candidate.exists():
                return candidate

    # Preferred location if no workbook has been created yet.
    return (data_directory() / "icsparts" / "icsparts_catalog_data.xlsx").resolve()


EXCEL_PATH = resolve_excel_path()
OUTPUT_DIR = EXCEL_PATH.parent
CHECKPOINT_CSV = OUTPUT_DIR / "_part_master_checkpoint.csv"
ERROR_CSV = OUTPUT_DIR / "part_master_errors.csv"
RESTART_MARKER = OUTPUT_DIR / "_part_master_restart_in_progress"

# Keep this modest. 4 workers is enough for ~4,440 listing pages.
MAX_WORKERS = 8
REQUEST_DELAY_SECONDS = 0.20
REQUEST_TIMEOUT = (10, 45)

# Save downloaded listing rows every N successfully parsed pages.
CHECKPOINT_EVERY_PAGES = 40

# None = crawl every page.
# For a quick test, set MAX_PAGES = 5.
MAX_PAGES: int | None = None

# Start a fresh listing scrape on the next run. Interrupted runs resume automatically.
FORCE_RESTART = True


# ============================================================
# HTTP
# ============================================================


def fetch(url: str) -> tuple[BeautifulSoup, str]:
    response = get_session().get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    # Do not hammer the website.
    time.sleep(REQUEST_DELAY_SECONDS)

    return BeautifulSoup(response.text, "html.parser"), response.url


# ============================================================
# TEXT / URL HELPERS
# ============================================================


def absolute_url(base_url: str, href: str | None) -> str:
    if not href:
        return ""

    url = urljoin(base_url, href)
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        return ""

    if not is_icsparts_url(url):
        return ""

    return parsed._replace(fragment="").geturl()


# ============================================================
# LISTING DISCOVERY
# ============================================================

RESULT_COUNT_RE = re.compile(
    r"Hiển thị\s+[\d.,]+\s*-\s*[\d.,]+\s*/\s*([\d.,]+)\s+kết quả",
    re.IGNORECASE,
)

PART_NUMBER_RE = re.compile(
    r"\b[A-Z0-9]{5}(?:-[A-Z0-9]{2,6}){1,2}\b",
    re.IGNORECASE,
)

PRICE_RE = re.compile(r"(\d[\d.]*)\s*₫\s*$")


def page_url(page: int) -> str:
    # date=asc makes the ordering deterministic enough for resume/checkpoint use.
    return f"{MASTER_URL}?date=asc&paginate={page}"


def discover_page_count() -> tuple[int, int]:
    soup, _ = fetch(page_url(1))
    page_text = clean_text(soup.get_text(" ", strip=True))

    match = RESULT_COUNT_RE.search(page_text)
    if not match:
        raise RuntimeError(
            "Could not detect the total number of Mã Phụ Tùng records "
            "from the first page."
        )

    total_records = int(match.group(1).replace(".", "").replace(",", ""))

    # The site currently shows 12 products per listing page.
    product_rows = parse_listing_page(soup, 1, page_url(1))
    per_page = len(product_rows)

    if per_page <= 0:
        raise RuntimeError(
            "The first page was loaded, but no product cards could be parsed."
        )

    total_pages = math.ceil(total_records / per_page)
    return total_records, total_pages


# ============================================================
# PRODUCT CARD PARSING
# ============================================================

LABELS = (
    "ENG:",
    "MÃ PHỤ TÙNG:",
    "BARCODE:",
    "NHÓM PHỤ TÙNG:",
    "MODEL XE:",
    "MODEL CODE:",
)


def extract_label(text: str, label: str) -> str:
    """
    Extract text after one ICSPARTS label until the next known label.

    Example:
        ... ENG: COV FR TOP R263
        MÃ PHỤ TÙNG: 64500-KFL-D20ZD
        BARCODE: ...

    extract_label(text, "ENG:") -> "COV FR TOP R263"
    """
    escaped_others = [re.escape(other) for other in LABELS if other != label]

    pattern = (
        re.escape(label)
        + r"\s*(.*?)"
        + r"(?=\s*(?:"
        + "|".join(escaped_others)
        + r")|$)"
    )

    match = re.search(pattern, text, flags=re.IGNORECASE)
    return clean_text(match.group(1)) if match else ""


def find_smallest_product_card_text(anchor) -> str:
    """
    Product markup can change.

    We climb from a /product/ link upward and select the smallest ancestor
    that contains exactly one MÃ PHỤ TÙNG label. That normally corresponds
    to one product card and avoids depending on WordPress CSS class names.
    """
    node = anchor

    for _ in range(8):
        if node is None:
            break

        try:
            text = clean_text(node.get_text(" ", strip=True))
        except Exception:
            text = ""

        if text.upper().count("MÃ PHỤ TÙNG:") == 1 and "BARCODE:" in text.upper():
            return text

        node = getattr(node, "parent", None)

    return ""


def parse_title_fields(card_text: str, part_number: str) -> tuple[str, int | None]:
    """
    Text before ENG usually looks like:

        64500-KFL-D20ZD | Mặt nạ trước *R263* 447.034 ₫

    Return:
        ("Mặt nạ trước *R263*", 447034)
    """
    prefix = re.split(r"\bENG\s*:", card_text, maxsplit=1, flags=re.IGNORECASE)[0]
    prefix = clean_text(prefix)

    # Remove leading part number + separator.
    prefix = re.sub(
        rf"^\s*{re.escape(part_number)}\s*\|\s*",
        "",
        prefix,
        flags=re.IGNORECASE,
    )

    price_vnd = None
    price_match = PRICE_RE.search(prefix)

    if price_match:
        price_vnd = int(price_match.group(1).replace(".", ""))
        prefix = clean_text(prefix[: price_match.start()])

    return prefix, price_vnd


def parse_product_card(
    card_text: str,
    product_url: str,
    page: int,
    source_url: str,
) -> dict | None:
    part_number = extract_label(card_text, "MÃ PHỤ TÙNG:").upper()

    if not part_number:
        # Fallback if the site changes label formatting.
        match = PART_NUMBER_RE.search(card_text)
        if not match:
            return None
        part_number = match.group(0).upper()

    part_name_vi, price_vnd = parse_title_fields(card_text, part_number)

    barcode = extract_label(card_text, "BARCODE:")
    name_en = extract_label(card_text, "ENG:")
    part_group = extract_label(card_text, "NHÓM PHỤ TÙNG:")
    model_summary = extract_label(card_text, "MODEL XE:")
    model_code = extract_label(card_text, "MODEL CODE:")

    return {
        "part_number": part_number,
        "part_number_compact": part_number.replace("-", ""),
        "part_family": part_number.split("-", 1)[0],
        "part_name_vi": part_name_vi,
        "part_name_en": name_en,
        "barcode": barcode,
        "part_group": part_group,
        "model_summary": model_summary,
        "model_code": model_code,
        "price_vnd": price_vnd,
        "product_url": product_url,
        "source_page": page,
        "source_url": source_url,
        "scraped_at": datetime.now().isoformat(timespec="seconds"),
    }


def parse_listing_page(
    soup: BeautifulSoup,
    page: int,
    source_url: str,
) -> list[dict]:
    """
    Parse one /danh-muc/ma-phu-tung/ listing page.

    We do NOT rely on CSS class names.
    """
    rows = []
    seen_urls = set()

    for anchor in soup.find_all("a", href=True):
        product_url = absolute_url(source_url, anchor.get("href"))

        if not product_url:
            continue

        if "/product/" not in urlparse(product_url).path.lower():
            continue

        normalized_url = product_url.rstrip("/") + "/"

        if normalized_url in seen_urls:
            continue

        card_text = find_smallest_product_card_text(anchor)
        if not card_text:
            continue

        if "MÃ PHỤ TÙNG:" not in card_text.upper():
            continue

        row = parse_product_card(
            card_text=card_text,
            product_url=normalized_url,
            page=page,
            source_url=source_url,
        )

        if row:
            rows.append(row)
            seen_urls.add(normalized_url)

    return rows


def scrape_page(page: int) -> tuple[int, list[dict], str | None]:
    url = page_url(page)

    try:
        soup, final_url = fetch(url)
        rows = parse_listing_page(soup, page, final_url)

        if not rows:
            return page, [], f"Page {page}: no product cards parsed -> {final_url}"

        return page, rows, None

    except Exception as exc:
        return (
            page,
            [],
            f"Page {page}: {type(exc).__name__}: {exc}",
        )


# ============================================================
# CHECKPOINT / RESUME
# ============================================================

CHECKPOINT_COLUMNS = [
    "part_number",
    "part_number_compact",
    "part_family",
    "part_name_vi",
    "part_name_en",
    "barcode",
    "part_group",
    "model_summary",
    "model_code",
    "price_vnd",
    "product_url",
    "source_page",
    "source_url",
    "scraped_at",
]


def reset_if_requested() -> None:
    if not FORCE_RESTART or RESTART_MARKER.exists():
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in (CHECKPOINT_CSV, ERROR_CSV):
        if path.exists():
            path.unlink()
    RESTART_MARKER.touch()


def load_processed_pages() -> set[int]:
    if not CHECKPOINT_CSV.exists():
        return set()

    try:
        df = pd.read_csv(
            CHECKPOINT_CSV,
            usecols=["source_page"],
            encoding="utf-8-sig",
        )
    except Exception:
        return set()

    pages = pd.to_numeric(df["source_page"], errors="coerce").dropna()
    return set(pages.astype(int).tolist())


def append_checkpoint(rows: list[dict]) -> None:
    if not rows:
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(rows)

    for col in CHECKPOINT_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df = df[CHECKPOINT_COLUMNS]

    write_header = not CHECKPOINT_CSV.exists()

    df.to_csv(
        CHECKPOINT_CSV,
        mode="a",
        header=write_header,
        index=False,
        encoding="utf-8-sig",
    )


def save_errors(errors: list[str]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pd.DataFrame({"error": errors}).to_csv(
        ERROR_CSV,
        index=False,
        encoding="utf-8-sig",
    )


# ============================================================
# MASTER DEDUPLICATION
# ============================================================


def first_nonblank(series: pd.Series):
    for value in series:
        if pd.notna(value) and str(value).strip():
            return value
    return ""


def join_unique(series: pd.Series) -> str:
    seen = []
    seen_keys = set()

    for value in series:
        if pd.isna(value):
            continue

        value = str(value).strip()
        if not value:
            continue

        key = value.casefold()

        if key not in seen_keys:
            seen_keys.add(key)
            seen.append(value)

    return " | ".join(seen)


def build_part_master(checkpoint_csv: Path | None = None) -> pd.DataFrame:
    checkpoint_csv = checkpoint_csv or CHECKPOINT_CSV
    if not checkpoint_csv.exists():
        raise RuntimeError("No checkpoint data exists.")

    raw = pd.read_csv(
        checkpoint_csv,
        dtype=str,
        encoding="utf-8-sig",
    )

    if raw.empty:
        raise RuntimeError("Checkpoint exists but contains no data.")

    raw["part_number"] = raw["part_number"].fillna("").str.strip().str.upper()
    raw = raw[raw["part_number"] != ""].copy()

    # Numeric fields back to numbers.
    raw["price_vnd"] = pd.to_numeric(raw["price_vnd"], errors="coerce")
    raw["source_page"] = pd.to_numeric(raw["source_page"], errors="coerce")

    counts = raw.groupby("part_number", sort=False).size().rename("listing_occurrences")

    # Keep one row per exact Honda PN.
    # Preserve every distinct value from duplicate listing cards.
    grouped = raw.groupby("part_number", sort=False)

    master = grouped.agg(
        part_number_compact=("part_number_compact", first_nonblank),
        part_family=("part_family", first_nonblank),
        part_name_vi=("part_name_vi", join_unique),
        part_name_en=("part_name_en", join_unique),
        barcode=("barcode", join_unique),
        part_group=("part_group", join_unique),
        model_summary=("model_summary", join_unique),
        model_code=("model_code", join_unique),
        price_vnd=("price_vnd", "first"),
        product_url=("product_url", join_unique),
        first_source_page=("source_page", "min"),
        scraped_at=("scraped_at", "max"),
    ).reset_index()

    master = master.merge(
        counts.reset_index(),
        on="part_number",
        how="left",
    )

    return master


# ============================================================
# JOIN AGAINST SCRAPER #1 + COLLAPSE APPLICATIONS
# ============================================================


def _clean_application_value(value) -> str:
    if pd.isna(value):
        return ""
    return clean_text(str(value))


def _catalog_model_and_version(row: pd.Series) -> tuple[str, str]:
    """Separate the catalogue model name from its year and variant details."""
    catalog_title = _clean_application_value(row.get("catalog_title", ""))
    year_spec = _clean_application_value(row.get("year_spec", ""))
    model_codes = _clean_application_value(row.get("catalog_model_codes", ""))
    variant_hint = _clean_application_value(row.get("figure_variant_hint", ""))

    model_name = catalog_title

    if model_name and year_spec:
        model_name = re.sub(
            rf"\s*\(\s*{re.escape(year_spec)}\s*\)\s*$",
            "",
            model_name,
            flags=re.IGNORECASE,
        ).strip()

    extras = []

    if model_codes and model_codes.casefold() not in model_name.casefold():
        extras.append(f"code:{model_codes}")

    if variant_hint and variant_hint.casefold() not in model_name.casefold():
        extras.append(f"variant:{variant_hint}")

    version = year_spec or "UNSPECIFIED"
    if extras:
        version += f" ({' ; '.join(extras)})"

    return model_name or "UNSPECIFIED", version


def format_application_text(applications: dict[str, dict[str, list[str]]]) -> str:
    return "\n".join(
        f"{archetype}: "
        + "; ".join(
            f"{model} [{', '.join(versions)}]"
            for model, versions in models.items()
        )
        for archetype, models in applications.items()
    )


def build_application_summary(raw_parts: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse raw_parts into MODEL GROUP -> MODEL NAME -> [VERSIONS].

    Example JSON stored in ONE Excel cell:

    {
      "VISION": {
        "VISION 110": ["09/2014+", "2021+"]
      }
    }

    raw_parts remains the source of truth. This is only a derived convenience view.
    """
    required = {"part_number", "model_group"}

    if not required.issubset(raw_parts.columns):
        return pd.DataFrame(
            columns=[
                "part_number",
                "application_dict",
                "application_text",
                "application_count",
            ]
        )

    rows = []

    for part_number, group in raw_parts.groupby("part_number", sort=False):
        applications: dict[str, dict[str, list[str]]] = {}
        unique_entries = set()

        for _, row in group.iterrows():
            model = (
                _clean_application_value(row.get("model_group", "")) or "UNSPECIFIED"
            )
            catalog_model, version = _catalog_model_and_version(row)

            key = (model, catalog_model, version)

            if key in unique_entries:
                continue

            unique_entries.add(key)

            applications.setdefault(model, {})
            applications[model].setdefault(catalog_model, [])

            if version not in applications[model][catalog_model]:
                applications[model][catalog_model].append(version)

        # Compact JSON: machine-friendly and easy to parse back in Python/Power Query.
        application_dict = json.dumps(
            applications,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        application_text = format_application_text(applications)

        rows.append(
            {
                "part_number": part_number,
                "application_dict": application_dict,
                "application_text": application_text,
                "application_count": len(unique_entries),
            }
        )

    return pd.DataFrame(rows)


def build_group_summary(raw_parts: pd.DataFrame) -> pd.DataFrame:
    """Keep the figure code, name, and URL together for each exact part number."""
    columns = [
        "part_number",
        "group_ids",
        "group_names",
        "group_urls",
        "group_details",
        "catalog_product_urls",
    ]
    required = {"part_number", "figure_code", "figure_name", "figure_url", "part_url"}
    if not required.issubset(raw_parts.columns):
        return pd.DataFrame(columns=columns)

    rows = []
    for part_number, group in raw_parts.groupby("part_number", sort=False):
        details = []
        seen_groups = set()
        product_urls = []
        seen_products = set()

        for _, row in group.iterrows():
            group_id = _clean_application_value(row["figure_code"])
            group_name = _clean_application_value(row["figure_name"])
            group_url = _clean_application_value(row["figure_url"])
            product_url = _clean_application_value(row["part_url"])
            group_key = (group_id, group_name, group_url)

            if any(group_key) and group_key not in seen_groups:
                seen_groups.add(group_key)
                details.append({"id": group_id, "name": group_name, "url": group_url})

            if product_url and product_url not in seen_products:
                seen_products.add(product_url)
                product_urls.append(product_url)

        rows.append(
            {
                "part_number": part_number,
                "group_ids": join_unique(pd.Series([item["id"] for item in details])),
                "group_names": join_unique(
                    pd.Series([item["name"] for item in details])
                ),
                "group_urls": join_unique(pd.Series([item["url"] for item in details])),
                "group_details": json.dumps(
                    details, ensure_ascii=False, separators=(",", ":")
                )
                if details
                else "",
                "catalog_product_urls": " | ".join(product_urls),
            }
        )

    return pd.DataFrame(rows, columns=columns)


def add_catalogue_presence(
    master: pd.DataFrame, excel_path: Path | None = None
) -> pd.DataFrame:
    """
    Read scraper #1's raw_parts sheet.

    Adds:
      - exact-PN catalogue occurrence count
      - model groups seen in catalogues
      - application_dict: MODEL -> YEAR -> [VERSION/CATALOG LABELS]
      - application_text: same information, easier to read in Excel
      - figure group IDs, names, URLs, and catalogue product URLs

    No compatibility is invented. All application data is derived only from
    exact occurrences of the same PN in raw_parts.
    """
    excel_path = excel_path or EXCEL_PATH
    if not excel_path.exists():
        raise FileNotFoundError(
            f"Scraper #1 Excel not found:\n{excel_path.resolve()}\n\n"
            "Put icsparts_catalog_data.xlsx beside this script, "
            "or inside an icsparts_output folder beside it."
        )

    try:
        raw_parts = pd.read_excel(
            excel_path,
            sheet_name="raw_parts",
            dtype=str,
        )
    except ValueError as exc:
        raise RuntimeError(
            "Excel exists, but sheet 'raw_parts' was not found. Run scraper #1 first."
        ) from exc

    if "part_number" not in raw_parts.columns:
        raise RuntimeError("Sheet 'raw_parts' has no 'part_number' column.")

    raw_parts["part_number"] = (
        raw_parts["part_number"].fillna("").str.strip().str.upper()
    )

    raw_parts = raw_parts[raw_parts["part_number"] != ""].copy()

    occurrence_count = (
        raw_parts.groupby("part_number").size().rename("catalogue_occurrences")
    )

    if "model_group" in raw_parts.columns:
        catalogue_models = (
            raw_parts.groupby("part_number")["model_group"]
            .apply(join_unique)
            .rename("catalogue_model_groups")
        )
    else:
        catalogue_models = pd.Series(
            dtype="object",
            name="catalogue_model_groups",
        )

    if "catalog_title" in raw_parts.columns:
        catalogue_versions = (
            raw_parts.groupby("part_number")["catalog_title"]
            .apply(join_unique)
            .rename("catalogue_versions")
        )
    else:
        catalogue_versions = pd.Series(dtype="object", name="catalogue_versions")

    application_summary = build_application_summary(raw_parts)
    group_summary = build_group_summary(raw_parts)

    master = master.merge(
        occurrence_count.reset_index(),
        on="part_number",
        how="left",
    )

    master["catalogue_occurrences"] = (
        master["catalogue_occurrences"].fillna(0).astype(int)
    )

    master["found_in_catalogue"] = master["catalogue_occurrences"] > 0

    if not catalogue_models.empty:
        master = master.merge(
            catalogue_models.reset_index(),
            on="part_number",
            how="left",
        )
    else:
        master["catalogue_model_groups"] = ""

    master["catalogue_model_groups"] = master["catalogue_model_groups"].fillna("")

    if not catalogue_versions.empty:
        master = master.merge(
            catalogue_versions.reset_index(),
            on="part_number",
            how="left",
        )
    else:
        master["catalogue_versions"] = ""

    master["catalogue_versions"] = master["catalogue_versions"].fillna("")

    if not application_summary.empty:
        master = master.merge(
            application_summary,
            on="part_number",
            how="left",
        )
    else:
        master["application_dict"] = ""
        master["application_text"] = ""
        master["application_count"] = 0

    master["application_dict"] = master["application_dict"].fillna("")
    master["application_text"] = master["application_text"].fillna("")
    master["application_count"] = master["application_count"].fillna(0).astype(int)

    if not group_summary.empty:
        master = master.merge(group_summary, on="part_number", how="left")
    else:
        for column in group_summary.columns.drop("part_number"):
            master[column] = ""

    for column in group_summary.columns.drop("part_number"):
        master[column] = master[column].fillna("")

    # Put the useful compatibility/application columns near the PN.
    preferred_order = [
        "part_number",
        "part_number_compact",
        "part_family",
        "found_in_catalogue",
        "catalogue_occurrences",
        "application_count",
        "application_dict",
        "application_text",
        "catalogue_model_groups",
        "catalogue_versions",
        "group_ids",
        "group_names",
        "group_urls",
        "group_details",
        "catalog_product_urls",
        "part_name_vi",
        "part_name_en",
        "barcode",
        "part_group",
        "model_summary",
        "model_code",
        "price_vnd",
        "product_url",
        "listing_occurrences",
        "first_source_page",
        "scraped_at",
    ]

    remaining = [c for c in master.columns if c not in preferred_order]
    return master[preferred_order + remaining]


# ============================================================
# WRITE INTO THE SAME EXCEL
# ============================================================


def write_part_master_sheet(
    master: pd.DataFrame, excel_path: Path | None = None
) -> None:
    """
    Add/replace ONLY the part_master sheet.
    Scraper #1 sheets are preserved.
    """
    excel_path = excel_path or EXCEL_PATH
    writer_kwargs = {}

    if excel_path.suffix.lower() == ".xlsm":
        writer_kwargs["engine_kwargs"] = {"keep_vba": True}

    with pd.ExcelWriter(
        excel_path,
        engine="openpyxl",
        mode="a",
        if_sheet_exists="replace",
        **writer_kwargs,
    ) as writer:
        master.to_excel(
            writer,
            sheet_name="part_master",
            index=False,
        )

    # Small readability pass.
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter

    wb = load_workbook(
        excel_path,
        keep_vba=(excel_path.suffix.lower() == ".xlsm"),
    )
    ws = wb["part_master"]

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    widths = {
        "part_number": 22,
        "part_number_compact": 22,
        "part_family": 12,
        "catalogue_model_groups": 34,
        "catalogue_versions": 48,
        "application_dict": 60,
        "application_text": 60,
        "group_ids": 24,
        "group_names": 48,
        "group_urls": 72,
        "group_details": 72,
        "catalog_product_urls": 72,
        "part_name_vi": 38,
        "part_name_en": 38,
        "product_url": 72,
    }
    wrap_columns = {"application_dict", "application_text", "group_details"}

    for col_idx, name in enumerate(master.columns, start=1):
        letter = get_column_letter(col_idx)
        ws.column_dimensions[letter].width = widths.get(name, 20)
        if name in wrap_columns:
            for row in ws.iter_rows(min_col=col_idx, max_col=col_idx):
                cell = row[0]
                cell.alignment = cell.alignment.copy(wrap_text=True, vertical="top")

    wb.save(excel_path)


# ============================================================
# MAIN
# ============================================================


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    reset_if_requested()

    if not EXCEL_PATH.exists():
        raise FileNotFoundError(
            f"Cannot find scraper #1 output:\n{EXCEL_PATH.resolve()}\n\n"
            "Run icsparts_catalog_scraper.py first. "
            "You may place the workbook beside this script or in ./icsparts_output/."
        )

    print("Reading ICSPARTS Mã Phụ Tùng listing...")
    total_records, total_pages = discover_page_count()

    if MAX_PAGES is not None:
        total_pages = min(total_pages, MAX_PAGES)

    print(f"Records reported by website: {total_records:,}")
    print(f"Pages to consider: {total_pages:,}")

    processed_pages = load_processed_pages()

    pages = [page for page in range(1, total_pages + 1) if page not in processed_pages]

    print(f"Already checkpointed: {len(processed_pages):,} pages")
    print(f"Remaining: {len(pages):,} pages")

    errors: list[str] = []
    batch_rows: list[dict] = []
    successful_since_checkpoint = 0

    if pages:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_map = {executor.submit(scrape_page, page): page for page in pages}

            completed = 0

            for future in as_completed(future_map):
                completed += 1
                page = future_map[future]

                try:
                    page_no, rows, error = future.result()
                except Exception as exc:
                    page_no = page
                    rows = []
                    error = f"Page {page}: {type(exc).__name__}: {exc}"

                if error:
                    errors.append(error)
                    print(f"[{completed}/{len(pages)}] page {page_no}: ERROR")
                    continue

                batch_rows.extend(rows)
                successful_since_checkpoint += 1

                print(
                    f"[{completed}/{len(pages)}] page {page_no}: {len(rows)} products"
                )

                if successful_since_checkpoint >= CHECKPOINT_EVERY_PAGES:
                    append_checkpoint(batch_rows)
                    batch_rows.clear()
                    successful_since_checkpoint = 0

        # Flush the final partial batch.
        append_checkpoint(batch_rows)

    save_errors(errors)

    print("\nBuilding exact-PN part master...")
    master = build_part_master()

    print("Matching exact PNs against scraper #1 raw_parts...")
    master = add_catalogue_presence(master)

    print("Writing sheet 'part_master' into:")
    print(EXCEL_PATH.resolve())

    write_part_master_sheet(master)
    RESTART_MARKER.unlink(missing_ok=True)

    print("\nDONE")
    print(f"Unique exact PNs: {len(master):,}")
    print(f"Found in catalogue: {int(master['found_in_catalogue'].sum()):,}")
    print(f"Not found in catalogue: {int((~master['found_in_catalogue']).sum()):,}")
    print(f"Listing-page errors: {len(errors):,}")
    print("\nFinal workbook:")
    print(EXCEL_PATH.resolve())


if __name__ == "__main__":
    main()

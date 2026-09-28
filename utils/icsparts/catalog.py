from __future__ import annotations

import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mapper.core.common import data_directory
from utils.icsparts.common import build_session, clean_text, is_icsparts_url


# ============================================================
# CONFIG
# ============================================================

ROOT_URL = "https://icsparts.vn/danh-muc/parts-catalogue/"

# None = scrape every model on the Parts Catalogue page.
# For a first test, use e.g. {"AIR BLADE"} or {"WAVE"}.
ONLY_MODELS: set[str] | None = None

# Keep this modest. The site is public, but there is no reason to hammer it.
MAX_WORKERS = 4
REQUEST_DELAY_SECONDS = 0.20
REQUEST_TIMEOUT = (10, 45)

def resolve_output_dir() -> Path:
    current = data_directory() / "icsparts"
    legacy = Path(__file__).resolve().parents[2] / "icsparts_scrape" / "icsparts_output"
    for directory in (current, legacy):
        if all(
            (directory / name).exists()
            for name in (
                "icsparts_catalog_index.csv",
                "icsparts_figure_index.csv",
                "icsparts_raw_parts.csv",
            )
        ):
            return directory
    return current


OUTPUT_DIR = resolve_output_dir()
CHECKPOINT_EVERY = 30  # save partial CSV every N figure pages
MAX_ATTEMPTS = 2


# ============================================================
# REGEX
# ============================================================

# Handles common Honda formats such as:
#   12209-GB4-681
#   83510-KVG-900ZA
#   96600-060-2207
#   96211-08000
PART_NUMBER_RE = re.compile(
    r"(?<![A-Z0-9])([A-Z0-9]{5}(?:-[A-Z0-9]{2,5}){1,2})(?![A-Z0-9])",
    re.IGNORECASE,
)

FIGURE_RE = re.compile(
    r"^\s*([EF]-?\d+(?:-\d+)*)\s*\|",
    re.IGNORECASE,
)

POSITION_RE = re.compile(r"\(\s*(\d+)\s*\)")
HASH_POSITION_RE = re.compile(r"^\s*#\s*(\d+)\b")
YEAR_RE = re.compile(r"\(([^()]*(?:19|20)\d{2}[^()]*)\)")
MODEL_CODE_RE = re.compile(r"\bK[A-Z0-9]{2,4}\b", re.IGNORECASE)


# ============================================================
# HTTP
# ============================================================

_catalog_thread_local = threading.local()

def fetch(url: str) -> tuple[BeautifulSoup, str]:
    session = getattr(_catalog_thread_local, "session", None)
    if session is None:
        session = build_session()
        # The scraper controls retries explicitly: one initial try and one retry.
        adapter = HTTPAdapter(max_retries=Retry(total=0), pool_connections=8, pool_maxsize=8)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _catalog_thread_local.session = session
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    # Small delay after every request. With 4 workers this is still reasonably fast.
    time.sleep(REQUEST_DELAY_SECONDS)

    return BeautifulSoup(response.text, "html.parser"), response.url


# ============================================================
# HELPERS
# ============================================================





def absolute_url(base_url: str, href: str | None) -> str | None:
    if not href:
        return None

    url = urljoin(base_url, href)
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        return None
    if not is_icsparts_url(url):
        return None

    # Remove fragments so the same page is not treated as several URLs.
    return parsed._replace(fragment="").geturl()


def dedupe_by_url(items: list[dict]) -> list[dict]:
    seen = set()
    output = []

    for item in items:
        url = item["url"].rstrip("/") + "/"
        if url in seen:
            continue
        seen.add(url)
        item["url"] = url
        output.append(item)

    return output


def extract_year_spec(title: str) -> str:
    matches = YEAR_RE.findall(title)
    return matches[-1].strip() if matches else ""


def extract_catalog_model_codes(title: str) -> str:
    codes = []
    seen = set()

    for match in MODEL_CODE_RE.findall(title.upper()):
        if match not in seen:
            seen.add(match)
            codes.append(match)

    return ", ".join(codes)


def extract_variant_hint(figure_name: str) -> str:
    """
    Example:
        TEM (ACA125CBF) -> ACA125CBF
        TAY LÁI ... (ACA160CAF) -> ACA160CAF

    This is only a hint copied from the figure title.
    It is NOT treated as a guaranteed normalized Honda version.
    """
    found = []

    for value in re.findall(r"\(([^()]*)\)", figure_name):
        value = clean_text(value).upper()

        # Code-like: contains letters + digits, mostly compact characters.
        if (
            any(c.isalpha() for c in value)
            and any(c.isdigit() for c in value)
            and re.fullmatch(r"[A-Z0-9/,\- ]{3,40}", value)
        ):
            found.append(value)

    return ", ".join(dict.fromkeys(found))


# ============================================================
# DISCOVERY: ROOT -> MODEL -> CATALOG -> FIGURE
# ============================================================

def discover_model_pages() -> list[dict]:
    soup, final_url = fetch(ROOT_URL)
    models = []

    for a in soup.find_all("a", href=True):
        text = clean_text(a.get_text(" ", strip=True))
        upper = text.upper()

        if not upper.startswith("PARTS CATALOGUE "):
            continue
        if upper == "PARTS CATALOGUE":
            continue

        url = absolute_url(final_url, a.get("href"))
        if not url:
            continue

        model_name = text[len("PARTS CATALOGUE ") :].strip()

        models.append(
            {
                "model_group": model_name,
                "title": text,
                "url": url,
            }
        )

    models = dedupe_by_url(models)

    if ONLY_MODELS:
        wanted = {x.upper().strip() for x in ONLY_MODELS}
        models = [m for m in models if m["model_group"].upper() in wanted]

    return models


def discover_catalog_pages(model: dict) -> list[dict]:
    soup, final_url = fetch(model["url"])

    parent_path = urlparse(final_url).path.rstrip("/") + "/"
    catalogs = []

    for a in soup.find_all("a", href=True):
        text = clean_text(a.get_text(" ", strip=True))
        if not text:
            continue

        url = absolute_url(final_url, a.get("href"))
        if not url:
            continue

        path = urlparse(url).path

        # Catalogue generations/years are children of the model catalogue page.
        if not path.startswith(parent_path):
            continue

        if "/product/" in path:
            continue

        if url.rstrip("/") == final_url.rstrip("/"):
            continue

        # Ignore navigation labels/breadcrumb duplication.
        if text.upper().startswith("PARTS CATALOGUE"):
            continue

        catalogs.append(
            {
                "model_group": model["model_group"],
                "catalog_title": text,
                "year_spec": extract_year_spec(text),
                "catalog_model_codes": extract_catalog_model_codes(text),
                "url": url,
            }
        )

    return dedupe_by_url(catalogs)


def discover_figure_pages(catalog: dict) -> list[dict]:
    soup, final_url = fetch(catalog["url"])
    figures = []

    for a in soup.find_all("a", href=True):
        text = clean_text(a.get_text(" ", strip=True))
        match = FIGURE_RE.match(text)

        if not match:
            continue

        url = absolute_url(final_url, a.get("href"))
        if not url or "/product/" not in urlparse(url).path:
            continue

        figure_code = match.group(1).upper()

        chunks = [clean_text(x) for x in text.split("|")]
        figure_name = chunks[1] if len(chunks) >= 2 else ""

        section = "Engine" if figure_code.startswith("E-") else "Frame"

        figures.append(
            {
                "model_group": catalog["model_group"],
                "catalog_title": catalog["catalog_title"],
                "year_spec": catalog["year_spec"],
                "catalog_model_codes": catalog["catalog_model_codes"],
                "catalog_url": final_url,
                "section": section,
                "figure_code": figure_code,
                "figure_name": figure_name,
                "figure_variant_hint": extract_variant_hint(figure_name),
                "figure_title": text,
                "url": url,
            }
        )

    return dedupe_by_url(figures)


# ============================================================
# FIGURE -> PARTS
# ============================================================

def parse_parts_from_primary_links(
    soup: BeautifulSoup,
    figure: dict,
    final_url: str,
) -> list[dict]:
    """
    ICSPARTS figure pages currently expose links like:

      ( 7 ) 14711KWN900 14711-KWN-900 | Xu páp hút

    This is the cleanest representation because it already contains:
      position + exact PN + Vietnamese part name.
    """
    rows = []
    seen = set()

    for a in soup.find_all("a", href=True):
        text = clean_text(a.get_text(" ", strip=True))

        pn_match = PART_NUMBER_RE.search(text)
        pos_match = POSITION_RE.search(text)

        if not pn_match or not pos_match or "|" not in text:
            continue

        part_number = pn_match.group(1).upper()
        position = int(pos_match.group(1))

        part_name = clean_text(text.split("|", 1)[1])

        part_url = absolute_url(final_url, a.get("href")) or ""

        # Component links normally point to /product/<part-number-slug>/.
        # Do not accidentally treat the figure's own link as a component.
        if part_url.rstrip("/") == final_url.rstrip("/"):
            continue

        key = (position, part_number, part_name)
        if key in seen:
            continue
        seen.add(key)

        rows.append(
            make_part_row(
                figure=figure,
                position=position,
                part_number=part_number,
                part_name=part_name,
                part_url=part_url,
                figure_url=final_url,
            )
        )

    return rows


def parse_parts_from_tables(
    soup: BeautifulSoup,
    figure: dict,
    final_url: str,
) -> list[dict]:
    """
    Fallback if ICSPARTS changes the clickable diagram markup.

    We inspect table rows and look for a Honda-like dashed part number.
    """
    rows = []
    seen = set()

    for tr in soup.find_all("tr"):
        row_text = clean_text(tr.get_text(" ", strip=True))
        pn_match = PART_NUMBER_RE.search(row_text)

        if not pn_match:
            continue

        part_number = pn_match.group(1).upper()

        position = None
        cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all(["th", "td"])]

        if cells:
            m = HASH_POSITION_RE.search(cells[0])
            if m:
                position = int(m.group(1))

        # Try to infer the name from a cell containing "PN | name"
        part_name = ""
        for cell in cells:
            if part_number in cell and "|" in cell:
                right = clean_text(cell.split("|", 1)[1])
                if right:
                    part_name = right
                    break

        # Otherwise, locate the PN cell and inspect the following cell.
        if not part_name:
            for i, cell in enumerate(cells):
                if part_number in cell and i + 1 < len(cells):
                    candidate = cells[i + 1]
                    if (
                        candidate
                        and "₫" not in candidate
                        and "TCCS:" not in candidate.upper()
                    ):
                        part_name = candidate
                        break

        part_url = ""
        for a in tr.find_all("a", href=True):
            if part_number in clean_text(a.get_text(" ", strip=True)).upper():
                part_url = absolute_url(final_url, a.get("href")) or ""
                break

        key = (position, part_number, part_name)
        if key in seen:
            continue
        seen.add(key)

        rows.append(
            make_part_row(
                figure=figure,
                position=position,
                part_number=part_number,
                part_name=part_name,
                part_url=part_url,
                figure_url=final_url,
            )
        )

    return rows


def make_part_row(
    figure: dict,
    position: int | None,
    part_number: str,
    part_name: str,
    part_url: str,
    figure_url: str,
) -> dict:
    return {
        "model_group": figure["model_group"],
        "catalog_title": figure["catalog_title"],
        "year_spec": figure["year_spec"],
        "catalog_model_codes": figure["catalog_model_codes"],
        "section": figure["section"],
        "figure_code": figure["figure_code"],
        "figure_name": figure["figure_name"],
        "figure_variant_hint": figure["figure_variant_hint"],
        "position": position,
        "part_number": part_number,
        "part_number_compact": part_number.replace("-", ""),
        "part_family": part_number.split("-", 1)[0],
        "part_name": part_name,
        "catalog_url": figure["catalog_url"],
        "figure_url": figure_url,
        "part_url": part_url,
    }


def scrape_figure(figure: dict) -> tuple[list[dict], str | None]:
    try:
        soup, final_url = fetch(figure["url"])

        rows = parse_parts_from_primary_links(soup, figure, final_url)

        if not rows:
            rows = parse_parts_from_tables(soup, figure, final_url)

        if not rows:
            return [], f"No parts detected: {final_url}"

        return rows, None

    except Exception as exc:
        return [], f"{figure['url']} -> {type(exc).__name__}: {exc}"


def discover_with_retries(discover, item: dict | None = None) -> tuple[list[dict], str | None]:
    error = None
    for _ in range(MAX_ATTEMPTS):
        try:
            found = discover() if item is None else discover(item)
            if found:
                return found, None
            error = "No links detected"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
    return [], error


def scrape_figure_with_retries(figure: dict) -> tuple[list[dict], str | None]:
    error = None
    for _ in range(MAX_ATTEMPTS):
        rows, error = scrape_figure(figure)
        if rows:
            return rows, None
    return [], error


def error_record(stage: str, item: dict, error: str) -> dict:
    return {
        "stage": stage,
        "model_group": item.get("model_group", ""),
        "catalog_title": item.get("catalog_title", ""),
        "figure_code": item.get("figure_code", ""),
        "url": item["url"],
        "attempts": MAX_ATTEMPTS,
        "error": error,
    }


def save_error_report(records: list[dict]) -> None:
    report = OUTPUT_DIR / "icsparts_scrape_errors.xlsx"
    if not records:
        if report.exists():
            report.unlink()
        return
    columns = ["stage", "model_group", "catalog_title", "figure_code", "url", "attempts", "error"]
    with pd.ExcelWriter(report, engine="openpyxl") as writer:
        pd.DataFrame(records, columns=columns).to_excel(writer, sheet_name="errors", index=False)
        sheet = writer.sheets["errors"]
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column, width in {"A": 20, "B": 20, "C": 42, "D": 16, "E": 80, "F": 12, "G": 80}.items():
            sheet.column_dimensions[column].width = width


# ============================================================
# OUTPUT
# ============================================================

def save_checkpoint(rows: list[dict]) -> None:
    if not rows:
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(
        OUTPUT_DIR / "_checkpoint_raw_parts.csv",
        index=False,
        encoding="utf-8-sig",
    )


def save_outputs(
    rows: list[dict],
    catalog_index: list[dict],
    figure_index: list[dict],
    errors: list[str],
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    parts_df = pd.DataFrame(rows)

    if not parts_df.empty:
        parts_df["position"] = pd.to_numeric(parts_df["position"], errors="coerce")
        parts_df = parts_df.drop_duplicates(
            subset=[
                "catalog_url",
                "figure_url",
                "position",
                "part_number",
                "part_name",
            ]
        )

        parts_df = parts_df.sort_values(
            by=[
                "model_group",
                "catalog_title",
                "section",
                "figure_code",
                "position",
                "part_number",
            ],
            na_position="last",
        ).reset_index(drop=True)

    catalogs_df = pd.DataFrame(catalog_index)
    figures_df = pd.DataFrame(figure_index)
    errors_df = pd.DataFrame({"error": errors})

    parts_df.to_csv(
        OUTPUT_DIR / "icsparts_raw_parts.csv",
        index=False,
        encoding="utf-8-sig",
    )
    catalogs_df.to_csv(
        OUTPUT_DIR / "icsparts_catalog_index.csv",
        index=False,
        encoding="utf-8-sig",
    )
    figures_df.to_csv(
        OUTPUT_DIR / "icsparts_figure_index.csv",
        index=False,
        encoding="utf-8-sig",
    )
    errors_df.to_csv(
        OUTPUT_DIR / "icsparts_errors.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # Preserve the part_master sheet when repairing an existing catalogue.
    workbook = OUTPUT_DIR / "icsparts_catalog_data.xlsx"
    temporary = workbook.with_name(f".{workbook.stem}.updating.xlsx")
    if workbook.exists():
        shutil.copy2(workbook, temporary)
    writer_options = {"mode": "a", "if_sheet_exists": "replace"} if workbook.exists() else {}
    try:
        with pd.ExcelWriter(temporary, engine="openpyxl", **writer_options) as writer:
            parts_df.to_excel(writer, sheet_name="raw_parts", index=False)
            catalogs_df.to_excel(writer, sheet_name="catalogs", index=False)
            figures_df.to_excel(writer, sheet_name="figures", index=False)
            errors_df.to_excel(writer, sheet_name="errors", index=False)
        temporary.replace(workbook)
    finally:
        if temporary.exists():
            temporary.unlink()


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Discovering model catalogues...")
    models, root_error = discover_with_retries(discover_model_pages)

    if not models:
        save_error_report([error_record("models", {"url": ROOT_URL}, root_error or "No models found")])
        raise RuntimeError("No model catalogue pages found.")

    print(f"Found {len(models)} model groups:")
    print(", ".join(m["model_group"] for m in models))

    catalog_index: list[dict] = []
    figure_index: list[dict] = []
    discovery_errors: list[str] = []
    error_records: list[dict] = []

    for model_no, model in enumerate(models, start=1):
        print(f"\n[{model_no}/{len(models)}] {model['model_group']}")

        catalogs, model_error = discover_with_retries(discover_catalog_pages, model)
        if model_error:
            msg = f"MODEL {model['url']} -> {model_error}"
            print("  ERROR:", msg)
            discovery_errors.append(msg)
            error_records.append(error_record("model_catalogs", model, model_error))
            continue

        print(f"  Catalogues: {len(catalogs)}")
        catalog_index.extend(catalogs)

        for catalog_no, catalog in enumerate(catalogs, start=1):
            figures, error = discover_with_retries(discover_figure_pages, catalog)
            if error:
                msg = f"CATALOG {catalog['url']} -> {error}"
                discovery_errors.append(msg)
                error_records.append(error_record("catalog_figures", catalog, error))
            figure_index.extend(figures)

            print(
                f"    [{catalog_no}/{len(catalogs)}] "
                f"{catalog['catalog_title']} -> {len(figures)} figures"
            )

    if not figure_index:
        save_error_report(error_records)
        save_outputs([], catalog_index, [], discovery_errors)
        raise RuntimeError("No figure pages found.")

    print(f"\nTotal figure pages: {len(figure_index)}")
    print(f"Scraping with {MAX_WORKERS} workers...\n")

    all_rows: list[dict] = []
    errors = list(discovery_errors)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(scrape_figure_with_retries, figure): figure
            for figure in figure_index
        }

        completed = 0

        for future in as_completed(future_map):
            figure = future_map[future]
            completed += 1

            try:
                rows, error = future.result()
            except Exception as exc:
                rows = []
                error = f"{figure['url']} -> {type(exc).__name__}: {exc}"

            all_rows.extend(rows)

            if error:
                errors.append(error)
                error_records.append(error_record("figure_parts", figure, error))

            print(
                f"[{completed}/{len(figure_index)}] "
                f"{figure['model_group']} | "
                f"{figure['figure_code']} | "
                f"{len(rows)} parts"
            )

            if completed % CHECKPOINT_EVERY == 0:
                save_checkpoint(all_rows)

    save_error_report(error_records)
    save_outputs(all_rows, catalog_index, figure_index, errors)

    print("\nDONE")
    print(f"Rows: {len(all_rows):,}")
    print(f"Errors/warnings: {len(errors):,}")
    print(f"Output folder: {OUTPUT_DIR.resolve()}")
    print("\nMain file:")
    print(OUTPUT_DIR / "icsparts_catalog_data.xlsx")


if __name__ == "__main__":
    main()

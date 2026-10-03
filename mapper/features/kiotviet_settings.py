"""Store the customer's KiotViet product URL and upload tab count locally."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from mapper.core.common import data_directory


MAX_UPLOAD_TABS = 10


def validate_store_url(value: str) -> str:
    value = value.strip()
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as error:
        raise ValueError("Paste a valid KiotViet product-page URL.") from error
    host = (parts.hostname or "").lower()
    if (parts.scheme != "https"
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.kiotviet\.vn", host)
            or parts.username or parts.password or port not in (None, 443)
            or parts.path.rstrip("/") != "/man"
            or parts.fragment.rstrip("/").lower() != "/products"
            or parts.query):
        raise ValueError(
            "Paste the full KiotViet Products URL, for example "
            "https://yourstore.kiotviet.vn/man/#/Products."
        )
    return urlunsplit(("https", host, "/man/", "", "/Products"))


def validate_tab_count(value) -> int:
    text = str(value).strip()
    if not text.isascii() or not text.isdecimal() or not 1 <= int(text) <= MAX_UPLOAD_TABS:
        raise ValueError(f"Choose between 1 and {MAX_UPLOAD_TABS} KiotViet tabs.")
    return int(text)


def load_settings(path: Path | None = None) -> tuple[str, int]:
    path = path or data_directory() / "kiotviet_settings.json"
    if not path.exists():
        return "", 1
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
        return validate_store_url(settings["url"]), validate_tab_count(settings["tabs"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"Cannot read KiotViet settings at {path}: {error}") from error


def save_settings(url: str, tabs, path: Path | None = None) -> tuple[str, int]:
    url, tabs = validate_store_url(url), validate_tab_count(tabs)
    path = path or data_directory() / "kiotviet_settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"url": url, "tabs": tabs}, indent=2), encoding="utf-8")
    temporary.replace(path)
    return url, tabs

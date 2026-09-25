"""Shared HTTP session and text helpers for ICS Parts scrapers."""

from __future__ import annotations

import re
import threading
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_thread_local = threading.local()

def build_session() -> requests.Session:
    session = requests.Session()

    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )

    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/152.0 Safari/537.36"
            ),
            "Accept-Language": "vi,en-US;q=0.9,en;q=0.8",
        }
    )
    return session

def get_session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = build_session()
        _thread_local.session = session
    return session

def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()

def is_icsparts_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host == "icsparts.vn" or host.endswith(".icsparts.vn")

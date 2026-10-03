"""Shared database and optional browser uploader for HTTP handlers."""

from pathlib import Path

from mapper.core.common import default_database_path
from mapper.persistence.database import WarehouseDatabase

_database_override: Path | None = None


def configure_database(path: Path | None) -> None:
    global _database_override
    _database_override = path


def _get_database() -> WarehouseDatabase:
    return WarehouseDatabase(_database_override or default_database_path())


def _get_uploader():
    # HTTP requests also need thread-local Playwright attachments and the saved store.
    from mapper.features.kiotviet_settings import load_settings
    from mapper.features.web_upload import WebsiteUploader
    return WebsiteUploader(store_url=load_settings()[0])

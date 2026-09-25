"""Shared database and optional browser uploader for HTTP handlers."""

from pathlib import Path

from mapper.core.common import default_database_path
from mapper.persistence.database import WarehouseDatabase

_database_override: Path | None = None
_uploader = None


def configure_database(path: Path | None) -> None:
    global _database_override
    _database_override = path


def _get_database() -> WarehouseDatabase:
    return WarehouseDatabase(_database_override or default_database_path())


def _get_uploader():
    global _uploader
    if _uploader is None:
        try:
            from mapper.features.web_upload import WebsiteUploader
            _uploader = WebsiteUploader()
        except Exception:
            _uploader = None
    return _uploader

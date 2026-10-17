"""SQLite facade composed from domain-specific operations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .catalog import CatalogOperations
from .exceptions import ExceptionOperations
from .inventory import InventoryOperations
from .models import (
    LayoutConflictError,
    OnHandProduct,
    Placement,
    ProductLocation,
    SlotAddress,
    validate_stock_quantity,
)
from .schema import SchemaOperations
from .shelves import ShelfOperations


class WarehouseDatabase(
    SchemaOperations,
    CatalogOperations,
    ShelfOperations,
    InventoryOperations,
    ExceptionOperations,
):
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

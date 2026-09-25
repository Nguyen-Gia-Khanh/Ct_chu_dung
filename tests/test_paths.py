"""The desktop launcher should find a live database before and after migration."""

from __future__ import annotations

from unittest.mock import patch

from mapper.core.common import default_database_path
from tests.support import WorkspaceTestCase


class DatabasePathTests(WorkspaceTestCase):
    def test_legacy_database_is_used_until_migrated(self) -> None:
        old = self.folder / "warehouse_locations.db"
        new = self.folder / "data" / "warehouse_locations.db"
        old.write_bytes(b"original")
        with patch("mapper.core.common.application_directory", return_value=self.folder):
            self.assertEqual(default_database_path(), old)
            new.parent.mkdir()
            new.write_bytes(b"new")
            with self.assertRaises(RuntimeError):
                default_database_path()
            old.unlink()
            self.assertEqual(default_database_path(), new)

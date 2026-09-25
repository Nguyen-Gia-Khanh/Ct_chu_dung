"""The activation command moves user data without overwriting a destination."""

from __future__ import annotations

from mapper.persistence.database import WarehouseDatabase
from tests.support import WorkspaceTestCase
from utils.migrate_data import migrate


class DataMigrationTests(WorkspaceTestCase):
    def test_preview_then_migrate_database_and_outputs(self) -> None:
        root = self.folder
        database = WarehouseDatabase(root / "warehouse_locations.db")
        database.import_products({"P1": "Bolts"})
        (root / "label_printouts").mkdir()
        (root / "label_printouts" / "one.pdf").write_bytes(b"PDF")
        (root / "icsparts_scrape" / "icsparts_output").mkdir(parents=True)
        (root / "icsparts_scrape" / "icsparts_output" / "one.csv").write_text("part\n", encoding="utf-8")

        preview = migrate(root)
        self.assertEqual(len(preview), 3)
        self.assertTrue((root / "warehouse_locations.db").exists())
        migrate(root, apply=True)

        self.assertFalse((root / "warehouse_locations.db").exists())
        self.assertEqual(WarehouseDatabase(root / "data" / "warehouse_locations.db").get_products(), [("P1", "Bolts")])
        self.assertTrue((root / "data" / "labels" / "one.pdf").exists())
        self.assertTrue((root / "data" / "icsparts" / "one.csv").exists())
        self.assertEqual(len(list((root / "data" / "backups").glob("*.db"))), 1)
        self.assertEqual(migrate(root), [])

    def test_conflicting_destination_aborts_before_moving_anything(self) -> None:
        root = self.folder
        WarehouseDatabase(root / "warehouse_locations.db")
        (root / "data").mkdir()
        (root / "data" / "warehouse_locations.db").write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            migrate(root, apply=True)
        self.assertTrue((root / "warehouse_locations.db").exists())

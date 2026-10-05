import csv
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from mapper.persistence.database import WarehouseDatabase


class ExceptionStagingLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = WarehouseDatabase(Path(self.folder.name) / "warehouse.db")
        self.db.initialize()
        self.db.commit_shelf("1", "A", [2], {}, set(), side="1")
        self.first = self.db.get_slot_by_name("L1-1A1-1")
        self.second = self.db.get_slot_by_name("L1-1A1-2")
        self.csv_path = Path(self.folder.name) / "products.csv"

    def tearDown(self):
        self.folder.cleanup()

    def test_independent_registration_and_wipe(self):
        pid = "99999-ZZZ-999"
        self.db.assign_exception(pid, self.first.slot_id, product_name="Tên hàng, A")
        stage = self.db.get_exception_staging()[0]
        self.assertEqual((stage["csv_updated"], stage["catalog_updated"]), (False, False))
        self.assertNotIn(pid, {row[0] for row in self.db.get_catalog_products()})

        self.assertEqual(self.db.add_staged_to_catalog([pid]), 1)
        stage = self.db.get_exception_staging()[0]
        self.assertEqual((stage["csv_updated"], stage["catalog_updated"]), (False, True))
        self.assertEqual(self.db.add_staged_to_catalog([pid]), 0)

        self.assertEqual(self.db.append_pending_to_csv(self.csv_path, [pid]), 1)
        stage = self.db.get_exception_staging()[0]
        self.assertEqual((stage["csv_updated"], stage["catalog_updated"]), (True, True))
        self.assertEqual(self.db.get_pending_csv_updates(), [])
        with self.csv_path.open(encoding="utf-8", newline="") as file:
            rows = list(csv.reader(file, delimiter=";"))
        self.assertEqual(rows[1][:2], [pid, "Tên hàng, A"])

        self.db.assign_exception(pid, self.second.slot_id)
        self.assertEqual(len(self.db.get_exception_staging()), 2)
        self.db.update_staged_exception_name(pid, "Renamed")
        self.assertTrue(all(not item["csv_updated"] and not item["catalog_updated"]
                            for item in self.db.get_exception_staging()))
        self.assertEqual(self.db.append_pending_to_csv(self.csv_path, [pid]), 1)
        with self.csv_path.open(encoding="utf-8", newline="") as file:
            rows = list(csv.reader(file, delimiter=";"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][1], "Renamed")

        self.db.wipe_staged_exception(pid)
        self.assertEqual(self.db.get_exception_staging(), [])
        self.assertNotIn(pid, {row[0] for row in self.db.get_catalog_products()})
        self.assertEqual(self.db.get_product_locations(pid), [])

    def test_wipe_removes_regular_placement(self):
        pid = "00001-AAA-001"
        self.db.import_products({pid: ("Regular", "Regular")})
        self.db.add_to_on_hand({pid: 1}, "2026-09-22T09:00:00+00:00")
        self.db.assign_on_hand_to_slot(self.first.slot_id, "2026-09-22T10:00:00+00:00", [pid])
        self.db.assign_exception(pid, self.second.slot_id)
        self.assertEqual(len(self.db.get_product_locations(pid)), 2)
        self.db.wipe_staged_exception(pid)
        self.assertEqual(self.db.get_product_locations(pid), [])

    def test_migration_preserves_old_rows(self):
        pid = "99999-ZZZ-999"
        self.db.assign_exception(pid, self.first.slot_id)
        with closing(sqlite3.connect(self.db.path)) as connection, connection:
            connection.execute("ALTER TABLE wait_to_update_csv DROP COLUMN csv_updated")
            connection.execute("ALTER TABLE wait_to_update_csv DROP COLUMN catalog_updated")
        self.db.initialize()
        stage = self.db.get_exception_staging()[0]
        self.assertFalse(stage["csv_updated"])
        self.assertFalse(stage["catalog_updated"])


if __name__ == "__main__":
    unittest.main()

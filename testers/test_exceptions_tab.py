import os
import tempfile
import unittest
from pathlib import Path

from mapper.database import WarehouseDatabase


class TestExceptionsTabDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_warehouse.db"
        self.db = WarehouseDatabase(self.db_path)
        self.db.initialize()

        # Build a test shelf: Floor 1, Side 1, Shelf A with 2 rows of 2 slots
        self.shelf_id = self.db.commit_shelf("1", "A", [2, 2], {}, set(), side="1")
        # Slot names: L1-1A1-1, L1-1A1-2, L1-1A2-1, L1-1A2-2
        self.slot_1 = self.db.get_slot_by_name("L1-1A1-1")
        self.slot_2 = self.db.get_slot_by_name("L1-1A1-2")
        self.slot_3 = self.db.get_slot_by_name("L1-1A2-1")
        self.slot_4 = self.db.get_slot_by_name("L1-1A2-2")

        # Import an existing product
        self.db.import_products({
            "00001-AAA-001": ("Widget Alpha", "Widget Alpha"),
        })

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_multi_location_joined_display(self):
        # 1. Assign product to slot 1 via standard placement
        self.db.add_to_on_hand({"00001-AAA-001": 1}, "2026-09-22T09:00:00+00:00")
        self.db.assign_on_hand_to_slot(self.slot_1.slot_id, "2026-09-22T10:00:00+00:00", ["00001-AAA-001"])

        # Check single location
        placements = self.db.get_placements()
        self.assertEqual(placements["00001-AAA-001"], "L1-1A1-1")

        # 2. Add an exception slot (slot 2) for the same product
        slot_name = self.db.assign_exception("00001-AAA-001", self.slot_2.slot_id, stock_qty=5)
        self.assertEqual(slot_name, "L1-1A1-2")

        # Placements should now combine both locations joined by ", "
        placements = self.db.get_placements()
        self.assertEqual(placements["00001-AAA-001"], "L1-1A1-1, L1-1A1-2")

        # get_product_locations should return list of both
        locations = self.db.get_product_locations("00001-AAA-001")
        self.assertEqual(locations, ["L1-1A1-1", "L1-1A1-2"])

        # get_product_location should return combined placement
        loc = self.db.get_product_location("00001-AAA-001")
        self.assertIsNotNone(loc)
        self.assertEqual(loc.placement.slot_name, "L1-1A1-1, L1-1A1-2")

        # Add a third location via exception
        self.db.assign_exception("00001-AAA-001", self.slot_3.slot_id)
        placements = self.db.get_placements()
        self.assertEqual(placements["00001-AAA-001"], "L1-1A1-1, L1-1A1-2, L1-1A2-1")

    def test_unregistered_product_assignment_and_staging(self):
        # Assign an unregistered product ID
        unregistered_id = "99999-ZZZ-999"
        slot_name = self.db.assign_exception(unregistered_id, self.slot_4.slot_id, stock_qty=2)
        self.assertEqual(slot_name, "L1-1A2-2")

        # Should be auto-registered with default name 'Exc - added later'
        catalog = {p[0]: p[1] for p in self.db.get_catalog_products()}
        self.assertIn(unregistered_id, catalog)
        self.assertEqual(catalog[unregistered_id], "Exc - added later")

        # Placements should list it
        placements = self.db.get_placements()
        self.assertEqual(placements[unregistered_id], "L1-1A2-2")

        # Slot contents should include it
        contents = self.db.get_slot_contents(self.slot_4.slot_id)
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0][0], unregistered_id)
        self.assertEqual(contents[0][1], "Exc - added later")
        self.assertEqual(contents[0][2].stock_qty, 2)

        # Staged CSV updates should include it
        pending = self.db.get_pending_csv_updates()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["product_id"], unregistered_id)
        self.assertEqual(pending[0]["product_name"], "Exc - added later")
        self.assertEqual(pending[0]["slot_name"], "L1-1A2-2")

    def test_append_pending_to_csv(self):
        # Create a sample CSV file with headers
        csv_file = Path(self.temp_dir.name) / "catalog.csv"
        csv_file.write_text("product_id;product_name;category\n00001-AAA-001;Widget Alpha;Standard\n", encoding="utf-8")

        # Stage two exception items
        self.db.assign_exception("88888-BBB-888", self.slot_1.slot_id)
        self.db.assign_exception("77777-CCC-777", self.slot_2.slot_id)

        self.assertEqual(len(self.db.get_pending_csv_updates()), 2)

        # Append to CSV
        appended_count = self.db.append_pending_to_csv(csv_file)
        self.assertEqual(appended_count, 2)

        # Staged table should be cleared
        self.assertEqual(len(self.db.get_pending_csv_updates()), 0)

        # CSV should contain appended records named 'Exc - added later'
        csv_text = csv_file.read_text(encoding="utf-8")
        self.assertIn("88888-BBB-888;Exc - added later;", csv_text)
        self.assertIn("77777-CCC-777;Exc - added later;", csv_text)

    def test_slot_and_shelf_contents_union(self):
        # Standard placement in slot 1
        self.db.add_to_on_hand({"00001-AAA-001": 1}, "2026-09-22T09:00:00+00:00")
        self.db.assign_on_hand_to_slot(self.slot_1.slot_id, "2026-09-22T10:00:00+00:00", ["00001-AAA-001"])
        # Exception placement in slot 1 with another item
        self.db.assign_exception("88888-BBB-888", self.slot_1.slot_id, stock_qty=10)

        # Slot 1 should have both
        contents = self.db.get_slot_contents(self.slot_1.slot_id)
        pids = [c[0] for c in contents]
        self.assertIn("00001-AAA-001", pids)
        self.assertIn("88888-BBB-888", pids)

        # Shelf should also list both
        shelf_contents = self.db.get_shelf_contents(self.shelf_id)
        shelf_pids = [c[0] for c in shelf_contents]
        self.assertIn("00001-AAA-001", shelf_pids)
        self.assertIn("88888-BBB-888", shelf_pids)


if __name__ == "__main__":
    unittest.main()

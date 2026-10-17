"""Read-only matching and placement checks against an isolated warehouse database."""

from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3

from barcode_web.lookup import WarehouseLookup
from mapper.persistence.database import WarehouseDatabase
from tests.support import WorkspaceTestCase


def create_test_warehouse(path: Path) -> Path:
    if not path.resolve().is_relative_to(Path(__file__).resolve().parents[1] / "tmp"):
        raise ValueError("Warehouse fixtures must stay inside repository tmp/")
    database = WarehouseDatabase(path)
    with closing(database.connect()) as connection, connection:
        connection.executescript("""
            INSERT INTO catalog_products(product_id,full_name) VALUES
                ('001234567890','Test part'),('CAT001','Catalog exception'),('NOLOC','Unassigned part'),('STAGE01','Staged exception');
            INSERT INTO hot_sellers(product_id) VALUES ('001234567890');
            INSERT INTO shelves(shelf_id, floor, side, shelf_code,row_count) VALUES
                (1, 'L1', '1', 'A',2), (2, 'L2', '2', 'B',4);
            INSERT INTO slots(slot_id, shelf_id, row_number, slot_number, slot_name) VALUES
                (1, 1, 2, 3, 'L1-1A2-3'), (2, 2, 4, 5, 'L2-2B4-5'), (3, 2, 4, 4, 'L2-2B4-4');
            INSERT INTO placements(product_id,slot_id,stock_qty) VALUES ('001234567890',1,9),('CAT001',2,3),('STAGE01',3,1);
            INSERT INTO exception_placements(product_id,slot_id) VALUES ('001234567890',2);
            INSERT INTO wait_to_update_csv(product_id,slot_id,slot_name) VALUES ('STAGE01',3,'L2-2B4-4');
        """)
    return path


class WarehouseLookupTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.path = create_test_warehouse(self.folder / "warehouse.db")
        self.lookup = WarehouseLookup(self.path)

    def test_exact_dashless_and_all_distinct_locations(self):
        expected = {"status": "found", "product_id": "001234567890", "product_name": "Test part",
                    "locations": ["L1-1A2-3", "L2-2B4-5"]}
        self.assertEqual(self.lookup.find("001234567890"), expected)
        self.assertEqual(self.lookup.find(" 001234567890 "), expected)
        self.assertEqual(self.lookup.find("cat001")["locations"], ["L2-2B4-5"])
        self.assertEqual(self.lookup.find("STAGE01")["product_name"], "Staged exception")
        self.assertEqual(self.lookup.find("STAGE01")["locations"], ["L2-2B4-4"])

    def test_missing_unassigned_and_canonical_lookup(self):
        self.assertEqual(self.lookup.find("NOLOC")["status"], "unassigned")
        self.assertEqual(self.lookup.find("unknown")["status"], "not_found")
        self.assertEqual(self.lookup.find("' OR 1=1 --")["status"], "not_found")
        self.assertEqual(self.lookup.find("AAB")["status"], "not_found")
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("INSERT INTO catalog_products(product_id,full_name) VALUES ('AAB','Literal ID')")
        self.assertEqual(self.lookup.find("AAB")["product_id"], "AAB")
        self.assertEqual(self.lookup.find("AAB")["status"], "unassigned")

    def test_read_only_and_current_assignments(self):
        before = hashlib.sha256(self.path.read_bytes()).digest()
        self.lookup.find("001234567890", include_cell_contents=True)
        with closing(self.lookup.connect()) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM placements")
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(), before)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE placements SET slot_id=3 WHERE product_id='001234567890'")
            connection.execute("DELETE FROM exception_placements WHERE product_id='001234567890'")
        self.assertEqual(self.lookup.find("001234567890")["locations"], ["L2-2B4-4"])
        missing = self.folder / "does-not-exist.db"
        with self.assertRaises(sqlite3.OperationalError):
            WarehouseLookup(missing)
        self.assertFalse(missing.exists())

    def test_optional_cell_contents_include_all_barcodes_and_names(self):
        from unittest.mock import patch
        with patch.object(self.lookup, "cell_contents", wraps=self.lookup.cell_contents) as contents:
            self.assertNotIn("cells", self.lookup.find("001234567890"))
            contents.assert_not_called()
        found = self.lookup.find("001234567890", include_cell_contents=True)
        self.assertEqual(found["cells"], [
            {"location": "L1-1A2-3", "products": [
                {"product_id": "001234567890", "product_name": "Test part", "stock_qty": 9},
            ]},
            {"location": "L2-2B4-5", "products": [
                {"product_id": "001234567890", "product_name": "Test part", "stock_qty": 9},
                {"product_id": "CAT001", "product_name": "Catalog exception", "stock_qty": 3},
            ]},
        ])
        self.assertEqual(self.lookup.find("STAGE01", include_cell_contents=True)["cells"][0]["products"], [
            {"product_id": "STAGE01", "product_name": "Staged exception", "stock_qty": 1},
        ])
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE placements SET stock_qty=999 WHERE product_id='CAT001'")
        self.assertEqual(self.lookup.find("CAT001", include_cell_contents=True)["cells"][0]["products"][1]["stock_qty"],999)
        for barcode in ("unknown", "NOLOC", "AAB"):
            self.assertEqual(self.lookup.find(barcode, include_cell_contents=True)["cells"], [])

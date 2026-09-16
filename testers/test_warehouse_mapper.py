import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from warehouse_mapper import LayoutConflictError, WarehouseDatabase, make_slot_name, normalize_search
from mapper.database import Placement


def placement(slot_name):
    return Placement(slot_name, 12, "2026-09-15T09:00:00+00:00")


class WarehouseDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = WarehouseDatabase(Path(self.temp_directory.name) / "test.db")
        self.database.import_products({"P1": "Ốc vít M8", "P2": "Bu lông", "P3": "Washer"})

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_vietnamese_search_normalization(self):
        self.assertEqual(normalize_search("Ốc VÍT"), "oc vit")
        self.assertEqual(normalize_search("Đầu nối điện"), "dau noi dien")

    def test_irregular_layout_and_multiple_products_per_slot(self):
        layout = [6, 6, 3]
        slot_name = make_slot_name("1", "A", 2, 3)
        shelf_id = self.database.commit_shelf(
            "1",
            "A",
            layout,
            {"P1": placement(slot_name), "P2": placement(slot_name)},
            set(),
        )
        self.assertEqual(self.database.get_shelf(shelf_id), ("1", "A", layout))
        placements = self.database.get_placements()
        self.assertEqual(placements["P1"], slot_name)
        self.assertEqual(placements["P2"], slot_name)

    def test_product_can_be_moved_to_another_slot(self):
        layout = [2]
        first_cell = make_slot_name("1", "A", 1, 1)
        second_cell = make_slot_name("1", "A", 1, 2)
        self.database.commit_shelf("1", "A", layout, {"P1": placement(first_cell)}, set())
        self.database.commit_shelf("1", "A", layout, {"P1": placement(second_cell)}, set())
        self.assertEqual(self.database.get_placements()["P1"], second_cell)

    def test_occupied_top_row_cannot_be_removed(self):
        first_layout = [2, 5]
        slot_name = make_slot_name("1", "A", 2, 1)
        self.database.commit_shelf("1", "A", first_layout, {"P1": placement(slot_name)}, set())
        with self.assertRaises(LayoutConflictError):
            self.database.commit_shelf("1", "A", [2], {}, set())
        self.assertEqual(self.database.get_placements(), {"P1": slot_name})

    def test_top_row_growth_and_shrink_preserve_lower_ids_and_products(self):
        layout = [6, 6]
        slot = make_slot_name("1", "A", 1, 2)
        shelf_id = self.database.commit_shelf("1", "A", layout, {"P1": placement(slot), "P2": placement(slot)}, set())
        with closing(self.database.connect()) as connection:
            before = [tuple(row) for row in connection.execute("SELECT * FROM slots ORDER BY slot_id")]
        self.database.commit_shelf("1", "A", layout + [10], {}, set())
        self.assertEqual(self.database.get_shelf(shelf_id)[2], layout + [10])
        self.database.commit_shelf("1", "A", layout, {}, set())
        with closing(self.database.connect()) as connection:
            after = [tuple(row) for row in connection.execute("SELECT * FROM slots ORDER BY slot_id")]
        self.assertEqual(before, after)
        self.assertEqual(self.database.get_placements(), {"P1": slot, "P2": slot})

    def test_bulk_decrease_only_removes_highest_rows(self):
        layout = [6, 6, 10, 11]
        shelf_id = self.database.commit_shelf("1", "A", layout, {}, set())
        self.database.commit_shelf("1", "A", layout[:2], {}, set())
        self.assertEqual(self.database.get_shelf(shelf_id)[2], [6, 6])

    def test_move_off_top_row_and_remove_it_in_one_commit(self):
        top = make_slot_name("1", "A", 2, 8)
        bottom = make_slot_name("1", "A", 1, 1)
        shelf_id = self.database.commit_shelf("1", "A", [6, 8], {"P1": placement(top)}, set())
        self.database.commit_shelf("1", "A", [6], {"P1": placement(bottom)}, set())
        self.assertEqual(self.database.get_shelf(shelf_id)[2], [6])
        self.assertEqual(self.database.get_placements(), {"P1": bottom})

    def test_return_to_queue_and_remove_top_row_in_one_commit(self):
        top = make_slot_name("1", "A", 2, 8)
        self.database.commit_shelf("1", "A", [6, 8], {"P1": placement(top)}, set())
        self.database.commit_shelf("1", "A", [6], {}, {"P1"})
        self.assertNotIn("P1", self.database.get_placements())

    def test_failed_commit_rolls_back_layout_and_assignments(self):
        bottom = make_slot_name("1", "A", 1, 1)
        top = make_slot_name("1", "A", 2, 1)
        shelf_id = self.database.commit_shelf("1", "A", [2], {"P1": placement(bottom)}, set())
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.commit_shelf("1", "A", [2, 5], {"UNKNOWN": placement(top)}, {"P1"})
        self.assertEqual(self.database.get_shelf(shelf_id)[2], [2])
        self.assertEqual(self.database.get_placements(), {"P1": bottom})

    def test_reopening_uses_same_database_and_row_numbers(self):
        layout = [6, 6, 10]
        slot = make_slot_name("1", "A", 1, 5)
        shelf_id = self.database.commit_shelf("1", "A", layout, {"P1": placement(slot)}, set())
        reopened = WarehouseDatabase(self.database.path)
        self.assertEqual(reopened.get_shelf(shelf_id), ("1", "A", layout))
        self.assertEqual(reopened.get_placements(), {"P1": slot})

    def test_unassign_then_reshape(self):
        first_layout = [2]
        slot_name = make_slot_name("1", "A", 1, 1)
        self.database.commit_shelf("1", "A", first_layout, {"P1": placement(slot_name)}, set())
        self.database.commit_shelf("1", "A", first_layout, {}, {"P1"})
        shelf_id = self.database.commit_shelf("1", "A", [5], {}, set())
        self.assertEqual(self.database.get_shelf(shelf_id)[2], [5])


class ContinuousCellMigrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "legacy.db"

    def build_legacy_database(self, *, original_timestamps=False):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executescript("""
                PRAGMA foreign_keys = ON;
                CREATE TABLE products (
                    product_id TEXT PRIMARY KEY, product_name TEXT NOT NULL,
                    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE shelves (
                    shelf_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    floor TEXT NOT NULL COLLATE NOCASE, shelf_code TEXT NOT NULL COLLATE NOCASE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (floor, shelf_code)
                );
                CREATE TABLE shelf_rows (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shelf_id INTEGER NOT NULL REFERENCES shelves(shelf_id) ON DELETE CASCADE,
                    row_number INTEGER NOT NULL,
                    left_slot_count INTEGER NOT NULL CHECK (left_slot_count >= 0),
                    right_slot_count INTEGER NOT NULL CHECK (right_slot_count >= 0),
                    UNIQUE (shelf_id, row_number)
                );
                CREATE TABLE slots (
                    slot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    row_id INTEGER NOT NULL REFERENCES shelf_rows(row_id) ON DELETE CASCADE,
                    side TEXT NOT NULL CHECK (side IN ('L', 'R')),
                    slot_number INTEGER NOT NULL CHECK (slot_number > 0),
                    slot_name TEXT NOT NULL UNIQUE,
                    UNIQUE (row_id, side, slot_number)
                );
            """)
            columns = ("assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP" if original_timestamps else
                       "stock_qty INTEGER CHECK (stock_qty >= 0), assigned_at TEXT, "
                       "committed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP")
            connection.execute(
                "CREATE TABLE placements (product_id TEXT PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE, "
                "slot_id INTEGER NOT NULL REFERENCES slots(slot_id) ON DELETE RESTRICT, " + columns + ")"
            )
            connection.executemany("INSERT INTO shelves (shelf_id, floor, shelf_code) VALUES (?, ?, ?)",
                                   [(1, "1", "A"), (2, "2", "B")])
            rows = [(10, 1, 1, 4, 3), (20, 1, 2, 0, 2), (30, 1, 3, 2, 0), (40, 2, 1, 1, 1)]
            connection.executemany("INSERT INTO shelf_rows VALUES (?, ?, ?, ?, ?)", rows)
            old_slots = {}
            for row_id, shelf_id, row_number, left, right in rows:
                floor, code = ("1", "A") if shelf_id == 1 else ("2", "B")
                for side, count in (("L", left), ("R", right)):
                    for cell in range(1, count + 1):
                        slot_name = f"{floor}-{code}-R{row_number:02d}-{side}{cell:02d}"
                        slot_id = 100 + 2 * len(old_slots)
                        old_slots[slot_name] = slot_id
                        connection.execute("INSERT INTO slots VALUES (?, ?, ?, ?, ?)",
                                           (slot_id, row_id, side, cell, slot_name))
            products = [
                ("P1", "1-A-R01-R01", 6), ("P2", "1-A-R01-R01", 10),
                ("P3", "1-A-R01-L04", 0), ("P4", "1-A-R02-R02", 8),
                ("P5", "2-B-R01-R01", 5), ("P6", "1-A-R03-L01", 12),
            ]
            for product_id, slot, quantity in products:
                connection.execute("INSERT INTO products (product_id, product_name) VALUES (?, ?)",
                                   (product_id, f"Product {product_id}"))
                if original_timestamps:
                    connection.execute("INSERT INTO placements VALUES (?, ?, ?)",
                                       (product_id, old_slots[slot], "2000-01-02 12:00:00"))
                else:
                    connection.execute("INSERT INTO placements VALUES (?, ?, ?, ?, ?)",
                                       (product_id, old_slots[slot], quantity,
                                        "2000-01-01T15:00:00+07:00", "2000-01-02 12:00:00"))
            self.original_slots = dict(connection.execute("SELECT slot_id, row_id FROM slots"))
            self.original_placements = connection.execute("SELECT * FROM placements ORDER BY product_id").fetchall()
            self.original_shelves = connection.execute("SELECT * FROM shelves ORDER BY shelf_id").fetchall()
            # Deleted rows/cells may have used IDs above the current maximum.
            connection.execute("UPDATE sqlite_sequence SET seq = 900 WHERE name = 'shelf_rows'")
            connection.execute("UPDATE sqlite_sequence SET seq = 9000 WHERE name = 'slots'")

    def test_migration_preserves_products_counts_times_and_slot_ids_on_irregular_shelves(self):
        self.build_legacy_database()
        database = WarehouseDatabase(self.path)
        self.assertEqual(database.get_shelf(1), ("1", "A", [7, 2, 2]))
        self.assertEqual(database.get_shelf(2), ("2", "B", [2]))
        self.assertEqual(database.get_placements(), {
            "P1": "1-A-R01-C05", "P2": "1-A-R01-C05", "P3": "1-A-R01-C04",
            "P4": "1-A-R02-C02", "P5": "2-B-R01-C02", "P6": "1-A-R03-C01",
        })
        with closing(database.connect()) as connection:
            self.assertEqual(dict(connection.execute("SELECT slot_id, row_id FROM slots")), self.original_slots)
            self.assertEqual([tuple(row) for row in connection.execute("SELECT * FROM placements ORDER BY product_id")],
                             self.original_placements)
            self.assertEqual([tuple(row) for row in connection.execute("SELECT * FROM shelves ORDER BY shelf_id")],
                             self.original_shelves)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertNotIn("side", {row["name"] for row in connection.execute("PRAGMA table_info(slots)")})
            self.assertNotIn("left_slot_count", {row["name"] for row in connection.execute("PRAGMA table_info(shelf_rows)")})

    def test_reopening_and_resizing_preserve_migrated_placements_and_id_history(self):
        self.build_legacy_database()
        before = WarehouseDatabase(self.path).get_placement_details()
        database = WarehouseDatabase(self.path)
        self.assertEqual(database.get_placement_details(), before)
        database.commit_shelf("1", "A", [6, 2, 2, 1], {}, set())
        self.assertEqual(database.get_placement_details(), before)
        with closing(database.connect()) as connection:
            new_cell = connection.execute(
                "SELECT row_id, slot_id FROM slots WHERE slot_name = '1-A-R04-C01'"
            ).fetchone()
            self.assertGreater(new_cell["row_id"], 900)
            self.assertGreater(new_cell["slot_id"], 9000)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_occupied_last_cell_blocks_shrink_after_migration(self):
        self.build_legacy_database()
        database = WarehouseDatabase(self.path)
        last_cell = Placement("1-A-R01-C07", 6, "2000-01-03T09:00:00+07:00")
        database.commit_shelf("1", "A", [7, 2, 2], {"P1": last_cell}, set())
        with self.assertRaises(LayoutConflictError):
            database.commit_shelf("1", "A", [6, 2, 2], {}, set())
        self.assertEqual(database.get_shelf(1)[2], [7, 2, 2])
        self.assertEqual(database.get_placement_details()["P1"], last_cell)

    def test_original_database_gets_both_upgrades_in_one_open(self):
        self.build_legacy_database(original_timestamps=True)
        database = WarehouseDatabase(self.path)
        self.assertEqual(database.get_placement_details()["P1"], Placement("1-A-R01-C05", None, None))
        with closing(database.connect()) as connection:
            self.assertEqual(connection.execute("SELECT committed_at FROM placements WHERE product_id = 'P1'").fetchone()[0],
                             "2000-01-02 12:00:00")
            self.assertEqual(dict(connection.execute("SELECT slot_id, row_id FROM slots")), self.original_slots)

    def test_failed_migration_rolls_back_layout_and_timestamp_changes(self):
        self.build_legacy_database(original_timestamps=True)
        migrate = WarehouseDatabase._migrate_continuous_cells

        def fail_after_migration(connection):
            migrate(connection)
            raise sqlite3.OperationalError("Simulated failure before commit")

        with patch.object(WarehouseDatabase, "_migrate_continuous_cells", side_effect=fail_after_migration):
            with self.assertRaises(sqlite3.OperationalError):
                WarehouseDatabase(self.path)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT * FROM placements ORDER BY product_id").fetchall(),
                             self.original_placements)
            self.assertEqual(connection.execute("SELECT left_slot_count, right_slot_count FROM shelf_rows WHERE row_id = 10").fetchone(),
                             (4, 3))
            self.assertEqual(connection.execute("SELECT count(*) FROM slots WHERE side = 'R'").fetchone()[0], 6)
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE name IN ('slots_new', 'shelf_rows_new')").fetchall(), [])


if __name__ == "__main__":
    unittest.main()

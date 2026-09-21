"""Unit tests for the 100% offline PyQt6 desktop UI."""

import os
import unittest
from pathlib import Path
import tempfile
import shutil

# Run Qt offscreen without requiring a physical monitor
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication
from mapper.database import WarehouseDatabase
from mapper.qt_ui.app import WarehouseMapperQtApp
from mapper.qt_ui.theme import INTELLI_J_STYLESHEET


class TestQtUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_warehouse.db"
        self.database = WarehouseDatabase(self.db_path)
        # Create a sample shelf
        self.shelf_id = self.database.commit_shelf("1", "A", [10, 10, 10], {}, set(), side="1")
        # Add sample products
        self.database.import_products({"PROD-001": ("Test Book 1", "Book 1"), "PROD-002": ("Test Book 2", "Book 2")})
        self.database.import_catalog_products({"CAT-001": ("Catalog Book 1", "Cat 1")})

        self.window = WarehouseMapperQtApp(database_path=self.db_path)

    def tearDown(self):
        self.window.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_window_initialization(self):
        self.assertEqual(self.window.tabs.count(), 5)
        self.assertEqual(self.window.tabs.tabText(0), "1. Shelf Designer")
        self.assertEqual(self.window.tabs.tabText(1), "2. Assign Locations")
        self.assertEqual(self.window.tabs.tabText(2), "3. Primal Queue / Shelves")
        self.assertEqual(self.window.tabs.tabText(3), "4. Browse Shelves")
        self.assertEqual(self.window.tabs.tabText(4), "5. Switch / Combine Cells")

    def test_theme_applied(self):
        self.assertIn("JetBrains Mono", INTELLI_J_STYLESHEET)
        self.assertIn("#3574f0", INTELLI_J_STYLESHEET)
        self.assertIn("#f7f8fa", INTELLI_J_STYLESHEET)

    def test_queue_and_catalog_populated(self):
        self.assertEqual(len(self.window.products), 2)
        self.assertEqual(len(self.window.catalog_products), 1)
        self.assertEqual(self.window.assignments_view.queue_table.rowCount(), 2)
        self.assertEqual(self.window.assignments_view.catalog_table.rowCount(), 1)

    def test_load_address(self):
        # Load slot 1-1A1-1
        self.window.load_assignment_address("1", "1", "A", 1, 1)
        self.assertIsNotNone(self.window.selected_address)
        self.assertEqual(self.window.selected_address.slot_name, "L1-1A1-1")
        self.assertIn("L1-1A1-1", self.window.assignments_view.target_badge.text())

    def test_designer_build_preview(self):
        self.window.designer_view.floor_input.setText("2")
        self.window.designer_view.side_input.setText("1")
        self.window.designer_view.shelf_code_input.setText("B")
        success = self.window.build_shelf_preview()
        self.assertTrue(success)
        self.assertEqual(self.window.preview_key, ("2", "1", "B"))


if __name__ == "__main__":
    unittest.main()

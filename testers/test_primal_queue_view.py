"""Automated tests for PrimalQueueView (Tab 3)."""

from __future__ import annotations

from pathlib import Path
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest

from mapper.database import Placement, WarehouseDatabase
from mapper.primal_queue_view import PrimalQueueView


FIRST_TIME = "2026-09-20T08:00:00+00:00"
SECOND_TIME = "2026-09-20T09:00:00+00:00"


class PrimalQueueViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.root.destroy()

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "warehouse.db"
        self.database = WarehouseDatabase(self.path)

        # Import working products (primal queue / hot sellers)
        self.database.import_products({
            "HOT-1": ("Hot Seller One", "H1"),
            "HOT-2": ("Hot Seller Two", "H2"),
        })

        # Import full catalog products (including non-hot sellers)
        self.database.import_catalog_products({
            "HOT-1": ("Hot Seller One", "H1"),
            "HOT-2": ("Hot Seller Two", "H2"),
            "CAT-ONLY": ("Catalog Only Item", "CO"),
        })

        # Commit a shelf with HOT-1 placed on it
        self.shelf_id = self.database.commit_shelf(
            "1", "A", [2],
            {"HOT-1": Placement("L1-1A1-1", 10, FIRST_TIME)},
            set(),
            side="1",
        )

        self.view = PrimalQueueView(self.root, self.database)
        self.view.refresh()

    def tearDown(self) -> None:
        if self.view.search_after_id:
            self.view.after_cancel(self.view.search_after_id)
            self.view.search_after_id = None
        self.view.destroy()

    def test_primal_queue_includes_assigned_hot_seller(self) -> None:
        # HOT-1 is committed to a shelf, but must STILL be in the primal queue tree
        primal_items = [
            self.view.primal_tree.item(iid, "values")[0]
            for iid in self.view.primal_tree.get_children()
        ]
        self.assertIn("HOT-1", primal_items)
        self.assertIn("HOT-2", primal_items)
        self.assertNotIn("CAT-ONLY", primal_items)

        # Check location and stock display for HOT-1
        hot1_values = self.view.primal_tree.item("primal::HOT-1", "values")
        self.assertEqual(hot1_values[0], "HOT-1")
        self.assertEqual(hot1_values[2], "L1-1A1-1")
        self.assertEqual(hot1_values[3], "10")

    def test_catalog_tree_shows_all_catalog_products(self) -> None:
        cat_items = [
            self.view.catalog_tree.item(iid, "values")[0]
            for iid in self.view.catalog_tree.get_children()
        ]
        self.assertIn("HOT-1", cat_items)
        self.assertIn("HOT-2", cat_items)
        self.assertIn("CAT-ONLY", cat_items)

    def test_search_filters_both_trees_and_identifies_hot_seller(self) -> None:
        self.view.search_var.set("HOT-1")
        self.view.refresh_results()

        primal_items = [
            self.view.primal_tree.item(iid, "values")[0]
            for iid in self.view.primal_tree.get_children()
        ]
        cat_items = [
            self.view.catalog_tree.item(iid, "values")[0]
            for iid in self.view.catalog_tree.get_children()
        ]
        self.assertEqual(primal_items, ["HOT-1"])
        self.assertEqual(cat_items, ["HOT-1"])

        status = self.view.search_status_text.get()
        self.assertIn("HOT SELLER", status)
        self.assertIn("L1-1A1-1", status)

    def test_search_identifies_non_hot_seller(self) -> None:
        self.view.search_var.set("CAT-ONLY")
        self.view.refresh_results()

        primal_items = [
            self.view.primal_tree.item(iid, "values")[0]
            for iid in self.view.primal_tree.get_children()
        ]
        cat_items = [
            self.view.catalog_tree.item(iid, "values")[0]
            for iid in self.view.catalog_tree.get_children()
        ]
        self.assertEqual(primal_items, [])
        self.assertEqual(cat_items, ["CAT-ONLY"])

        status = self.view.search_status_text.get()
        self.assertIn("NOT a hot seller", status)

    def test_double_click_primal_tree_fills_search_bar(self) -> None:
        event = SimpleNamespace(y=5)
        # Mock identify_row to return primal::HOT-2
        original_identify = self.view.primal_tree.identify_row
        self.view.primal_tree.identify_row = lambda _y: "primal::HOT-2"
        try:
            res = self.view._on_primal_double_click(event)
            self.assertEqual(res, "break")
            self.assertEqual(self.view.search_var.get(), "HOT-2")
        finally:
            self.view.primal_tree.identify_row = original_identify

    def test_double_click_catalog_tree_fills_search_bar(self) -> None:
        event = SimpleNamespace(y=5)
        original_identify = self.view.catalog_tree.identify_row
        self.view.catalog_tree.identify_row = lambda _y: "catalog::CAT-ONLY"
        try:
            res = self.view._on_catalog_double_click(event)
            self.assertEqual(res, "break")
            self.assertEqual(self.view.search_var.get(), "CAT-ONLY")
        finally:
            self.view.catalog_tree.identify_row = original_identify

    def test_double_click_contents_tree_fills_search_bar(self) -> None:
        event = SimpleNamespace(y=5)
        original_identify = self.view.contents_tree.identify_row
        original_item = self.view.contents_tree.item
        self.view.contents_tree.identify_row = lambda _y: "content::HOT-1"
        self.view.contents_tree.item = lambda _row, _val: ("HOT-1", "Hot Seller One", "10")
        try:
            res = self.view._on_contents_double_click(event)
            self.assertEqual(res, "break")
            self.assertEqual(self.view.search_var.get(), "HOT-1")
        finally:
            self.view.contents_tree.identify_row = original_identify
            self.view.contents_tree.item = original_item

    def test_selecting_assigned_product_loads_shelf_and_highlights_cell(self) -> None:
        self.view._highlight_product_location("HOT-1")
        self.assertEqual(self.view.current_shelf_id, self.shelf_id)
        self.assertEqual(self.view.selected_slot_name, "L1-1A1-1")
        self.assertIn("L1-1A1-1", self.view.slot_header_text.get())

        content_ids = [
            self.view.contents_tree.item(iid, "values")[0]
            for iid in self.view.contents_tree.get_children()
        ]
        self.assertIn("HOT-1", content_ids)

    def test_app_mounts_primal_queue_view_as_tab_3(self) -> None:
        from mapper.app import WarehouseMapperApp
        app = WarehouseMapperApp(self.root, self.path)
        try:
            tabs = [app.notebook.tab(i, "text") for i in range(app.notebook.index("end"))]
            self.assertEqual(len(tabs), 6)
            self.assertEqual(tabs[0], "1. Shelf Designer")
            self.assertEqual(tabs[1], "2. Assign Locations")
            self.assertEqual(tabs[2], "3. Primal Queue / Shelves")
            self.assertEqual(tabs[3], "4. Browse Shelves")
            self.assertEqual(tabs[4], "5. Switch / Combine Cells")
            self.assertEqual(tabs[5], "6. Special Exceptions")
            self.assertIs(app.primal_view, app.lookup)
            self.assertEqual(str(app.primal_view), app.notebook.tabs()[2])
        finally:
            if hasattr(app, "chrome_connect_after_id") and app.chrome_connect_after_id:
                app.root.after_cancel(app.chrome_connect_after_id)
            if hasattr(app, "web_upload_after_id") and app.web_upload_after_id:
                app.root.after_cancel(app.web_upload_after_id)
            for child in app.notebook.winfo_children():
                child.destroy()
            app.toolbar.destroy()
            app.notebook.destroy()


if __name__ == "__main__":
    unittest.main()

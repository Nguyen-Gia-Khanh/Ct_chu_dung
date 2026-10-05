"""Tab 2 search navigation and Tab 6 catalog-only exception membership."""

import tkinter as tk
from unittest.mock import patch

from mapper.persistence.database import Placement, WarehouseDatabase
from tests.support import WorkspaceTestCase
from ui.desktop.app import WarehouseMapperApp


class QuickLocationTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.folder / "warehouse.db"
        db = WarehouseDatabase(self.path)
        db.import_products({"P1": "Unique bolts", "P2": "Washers"})
        db.commit_shelf("2", "AB", [2, 2], {}, set(), side="2")
        self.address = db.get_slot_address("2", "2", "AB", 2, 2)
        db.commit_shelf(
            "2", "AB", [2, 2],
            {"P1": Placement(self.address.slot_name, 8, "2026-10-05T10:00:00+07:00")},
            set(), side="2",
        )
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = WarehouseMapperApp(self.root, self.path)
        self.view = self.app.assignments

    def search(self, query):
        self.view.search_var.set(query)
        self.app.refresh_product_lists()

    def test_unique_name_loads_all_fields_and_saved_contents_without_moving_stock(self):
        before = self.app.database.get_all_placement_items()
        self.search("unique bolts")
        self.assertEqual(str(self.view.quick_move_button["state"]), "normal")
        self.view.quick_move_button.invoke()
        self.assertEqual(
            [v.get() for v in (self.view.floor_var, self.view.side_var,
                              self.view.shelf_var, self.view.row_var, self.view.cell_var)],
            ["2", "2", "AB", "2", "2"],
        )
        self.assertEqual(self.view.hand_view.get(), "shelf")
        self.assertEqual(self.app.selected_address, self.address)
        self.assertEqual(self.view._selected_shelf_cell, (2, 2))
        self.assertIn("saved::P1", self.view.contents_tree.get_children())
        self.assertEqual(self.app.database.get_all_placement_items(), before)

    def test_empty_multiple_and_missing_results_cannot_navigate(self):
        for query in ("", "P", "missing"):
            with self.subTest(query=query):
                self.search(query)
                self.assertEqual(str(self.view.quick_move_button["state"]), "disabled")
                self.app.quick_move_search_product()
                self.assertIsNone(self.app.selected_address)
        # A click during the debounce must recheck the current search.
        self.search("P1")
        self.view.search_var.set("P")
        self.app.quick_move_search_product()
        self.assertIsNone(self.app.selected_address)

    def test_unassigned_product_keeps_loaded_address(self):
        self.search("P1")
        self.app.quick_move_search_product()
        self.search("P2")
        with patch("ui.desktop.catalog_actions.messagebox.showinfo") as info:
            self.app.quick_move_search_product()
        info.assert_called_once()
        self.assertEqual(self.app.selected_address, self.address)

    def test_exception_is_catalog_only_after_reopen_and_dequeue(self):
        db = self.app.database
        db.assign_exception("E1", self.address.slot_id, stock_qty=5, product_name="Exception part")
        self.app.on_exception_data_changed()
        self.search("E1")
        self.assertEqual(self.view.queue_tree.get_children(), ())
        self.assertEqual(self.view.catalog_tree.get_children(), ("catalog::E1",))
        self.app.primal_view.refresh()
        self.assertNotIn("E1", self.app.primal_view.products)
        self.assertIn("E1", self.app.primal_view.catalog_products)
        self.app.quick_move_search_product()
        self.assertEqual(self.app.selected_address, self.address)
        db = WarehouseDatabase(self.path)
        self.assertIn("E1", db.get_catalog_only_product_ids())
        db.add_staged_to_catalog(["E1"])
        db.remove_exception_from_slot("E1", self.address.slot_id)
        db.assign_catalog_direct_to_slot(
            self.address.slot_id, "2026-10-05T10:00:00+07:00",
            {"E1": ("Exception part", "Exception part")}, default_stock=5,
        )
        db.move_slot_to_on_hand(self.address.slot_id, "2026-10-05T11:00:00+07:00", ["E1"])
        db.dequeue_on_hand(["E1"], "2026-10-05T12:00:00+07:00", restore_origin=True)
        self.assertNotIn("E1", dict(db.get_products()))
        self.assertNotIn("E1", db.get_returned_queue_products())
        self.assertIn("E1", {row[0] for row in db.get_catalog_products()})

    def test_existing_queue_product_keeps_membership_when_exception_added(self):
        db = self.app.database
        db.assign_exception("P1", self.address.slot_id, stock_qty=2)
        self.assertNotIn("P1", db.get_catalog_only_product_ids())
        self.app.on_exception_data_changed()
        self.search("P1")
        self.assertEqual(self.view.queue_tree.get_children(), ("product::P1",))

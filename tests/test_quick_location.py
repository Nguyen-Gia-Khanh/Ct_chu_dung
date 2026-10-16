"""Tab 2 search navigation and Tab 6 catalog-only exception membership."""

import tkinter as tk
from tkinter import font as tkfont
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

    def address_fields(self, view):
        return [v.get() for v in (view.floor_var, view.side_var, view.shelf_var,
                                 view.row_var, view.cell_var)]

    def add_extra_locations(self, product_id="P1"):
        db = self.app.database
        db.commit_shelf("3", "CD", [3], {}, set(), side="4")
        extra = [db.get_slot_address("2", "2", "AB", 1, 1),
                 db.get_slot_address("3", "4", "CD", 1, 3)]
        for address in extra:
            db.assign_exception(product_id, address.slot_id, stock_qty=2)
        self.app.on_exception_data_changed()
        return extra

    def test_location_columns_show_full_exception_list_and_fit_its_text(self):
        self.add_extra_locations()
        self.search("P1")
        expected = ", ".join(self.app.database.get_product_locations("P1"))
        for tree, item in ((self.view.queue_tree, "product::P1"),
                           (self.view.catalog_tree, "catalog::P1")):
            self.assertEqual(tree.set(item, "location_id"), expected)
            font = tkfont.nametofont("TkDefaultFont", root=tree)
            self.assertGreaterEqual(tree.column("location_id", "width"), font.measure(expected) + 20)
        self.assertEqual(self.view.search_location_text.get(), f"Already at {expected}")

    def test_multi_location_clicks_cycle_and_load_tab6_only_on_navigation(self):
        extra = self.add_extra_locations()
        exceptions = self.app.exceptions_view
        before_fields = self.address_fields(exceptions)
        self.search("unique bolts")
        self.assertEqual(self.address_fields(exceptions), before_fields)
        before_data = self.app.database.get_all_placement_items()
        for index, address in enumerate([self.address, *extra, self.address]):
            self.view.quick_move_button.invoke()
            expected = [address.floor, address.side, address.shelf_code,
                        str(address.row_number), str(address.slot_number)]
            self.assertEqual(self.address_fields(self.view), expected)
            self.assertEqual(self.address_fields(exceptions), expected)
            self.assertEqual(self.app.selected_address, address)
            self.assertEqual(exceptions.selected_address, address)
            self.assertIn(f"location {index % 3 + 1}/3", self.app.status_text.get())
        self.assertEqual(self.app.database.get_all_placement_items(), before_data)
        # Ordinary edits and address loading never keep the two tabs linked.
        self.view.row_var.set("1")
        self.view.cell_var.set("2")
        self.app.load_assignment_address()
        self.assertEqual(exceptions.selected_address, self.address)
        self.assertEqual(self.address_fields(exceptions), ["2", "2", "AB", "2", "2"])
        exceptions.floor_var.set("9")
        self.assertEqual(self.view.floor_var.get(), "2")

    def test_single_location_navigation_leaves_tab6_independent(self):
        exceptions = self.app.exceptions_view
        fields = self.address_fields(exceptions)
        self.search("P1")
        self.view.quick_move_button.invoke()
        self.assertEqual(self.address_fields(exceptions), fields)
        self.assertIsNone(exceptions.selected_address)
        self.assertEqual(self.view.queue_tree.set("product::P1", "location_id"), self.address.slot_name)

    def test_cycle_resets_after_search_or_location_list_changes(self):
        extra = self.add_extra_locations()
        self.search("P1")
        self.app.quick_move_search_product()
        self.app.quick_move_search_product()
        self.assertEqual(self.app.selected_address, extra[0])
        self.search("P2")
        self.search("P1")
        self.app.quick_move_search_product()
        self.assertEqual(self.app.selected_address, self.address)
        self.app.database.remove_exception_from_slot("P1", extra[0].slot_id)
        self.app.on_exception_data_changed()
        self.app.quick_move_search_product()
        self.assertEqual(self.app.selected_address, self.address)
        self.app.quick_move_search_product()
        self.assertEqual(self.app.selected_address, extra[1])
        self.app.database.remove_exception_from_slot("P1", extra[1].slot_id)
        self.app.on_exception_data_changed()
        self.assertEqual(self.view.queue_tree.set("product::P1", "location_id"), self.address.slot_name)

    def test_exception_only_product_cycles_without_repeating_duplicate_location(self):
        extra = self.add_extra_locations("E1")
        self.app.database.assign_exception("E1", extra[0].slot_id, stock_qty=3)
        self.app.on_exception_data_changed()
        self.search("E1")
        self.assertEqual(self.view.catalog_tree.set("catalog::E1", "location_id"),
                         ", ".join(address.slot_name for address in extra))
        for address in [*extra, extra[0]]:
            self.app.quick_move_search_product()
            self.assertEqual(self.app.selected_address, address)

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

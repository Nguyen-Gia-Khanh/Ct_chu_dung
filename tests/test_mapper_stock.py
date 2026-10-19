"""Stock quantity validation, commit timestamps, and catalog double-click behaviour."""

import tempfile
import tkinter as tk
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ui.desktop.app import WarehouseMapperApp
from ui.desktop.dialogs import StockQuantityDialog
from mapper.core.common import make_slot_name
from mapper.persistence.database import Placement, WarehouseDatabase


CELL_ONE = make_slot_name("1", "A", 1, 1, side="1")
CELL_TWO = make_slot_name("1", "A", 1, 2, side="1")
FIRST_TIME = "2000-01-01T09:00:00+00:00"
SECOND_TIME = "2000-01-01T10:15:00+00:00"


class StockPlacementTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = WarehouseDatabase(Path(directory.name) / "test.db")
        self.products = {"P1": "Bolts", "P2": "Washers"}
        self.database.import_products(self.products)

    def make_app(self):
        app = WarehouseMapperApp.__new__(WarehouseMapperApp)
        app.root = Mock()
        app.database = self.database
        app.products = self.products.copy()
        app.assignments = SimpleNamespace(
            queue_tree=Mock(), contents_tree=Mock(), selected_slot_text=Mock(),
        )
        app.assignments.contents_tree.get_children.return_value = ()
        app.committed_locations = {}
        app.committed_placements = {}
        app.staged_assignments = {}
        app.pending_unassignments = set()
        app.transferred_stock = {}
        app.on_hand_products = {}
        app.selected_slot = CELL_ONE
        app.current_layout = [2]
        app.preview_key = ("1", "1", "A")
        app.current_shelf_id = None
        app.status_text = Mock()
        app.refresh_all_views = Mock()
        app.refresh_product_queue = Mock()
        app.refresh_shelf_selector = Mock()
        app.build_shelf_preview = Mock(return_value=True)
        app._editor_state = Mock(return_value=())
        return app

    def test_layout_only_commit_preserves_quantity_and_both_timestamps(self):
        self.database.commit_shelf("1", "A", [2], {"P1": Placement(CELL_ONE, 16, FIRST_TIME)}, set())
        with closing(self.database.connect()) as connection:
            before = tuple(connection.execute("SELECT * FROM placements").fetchone())
        self.database.commit_shelf("1", "A", [2, 6], {}, set())
        with closing(self.database.connect()) as connection:
            after = tuple(connection.execute("SELECT * FROM placements").fetchone())
        self.assertEqual(before, after)

    def test_invalid_quantity_or_missing_assignment_time_cannot_change_database(self):
        for quantity in (-1, 1.5, True, "5", None, 2 ** 63):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                self.database.commit_shelf("1", "A", [2], {"P1": Placement(CELL_ONE, quantity, FIRST_TIME)}, set())
        for instant in (None, "", "invalid", "2000-01-01T09:00:00"):
            with self.subTest(instant=instant), self.assertRaises(ValueError):
                self.database.commit_shelf("1", "A", [2], {"P1": Placement(CELL_ONE, 5, instant)}, set())
        self.assertEqual(self.database.list_shelves(), [])
        self.assertEqual(self.database.get_placement_details(), {})

    def test_double_click_located_catalog_product_searches_without_transferring(self):
        app = self.make_app()
        placement = Placement(CELL_ONE, 27, FIRST_TIME)
        app.catalog_products = {"P1": ("Bolts", "Bolt")}
        app.committed_placements = {"P1": placement}
        app.committed_locations = {"P1": CELL_ONE}
        app.assignments.catalog_tree = Mock()
        app.assignments.catalog_tree.identify_row.return_value = "catalog::P1"
        app.assignments.search_var = Mock()
        app.assignments.search_entry = Mock()
        app.assignments._set_and_select_search = Mock()
        app.refresh_product_lists = Mock()
        app.transfer_catalog_selection_to_queue = Mock()

        result = app.activate_catalog_product(SimpleNamespace(y=20))

        self.assertEqual(result, "break")
        app.assignments._set_and_select_search.assert_called_once_with(
            app.assignments.search_var, app.assignments.search_entry, "P1"
        )
        app.transfer_catalog_selection_to_queue.assert_not_called()
        self.assertEqual(app.pending_unassignments, set())

    def test_double_click_unlocated_catalog_product_searches_without_transferring(self):
        app = self.make_app()
        app.catalog_products = {"C1": ("Catalog bolt", "C bolt")}
        app.assignments.catalog_tree = Mock()
        app.assignments.catalog_tree.identify_row.return_value = "catalog::C1"
        app.assignments.search_var = Mock()
        app.assignments.search_entry = Mock()
        app.assignments._set_and_select_search = Mock()
        app.refresh_product_lists = Mock()
        app.transfer_catalog_selection_to_queue = Mock()

        result = app.activate_catalog_product(SimpleNamespace(y=20))

        self.assertEqual(result, "break")
        app.assignments.catalog_tree.selection_set.assert_called_once_with("catalog::C1")
        app.assignments._set_and_select_search.assert_called_once_with(
            app.assignments.search_var, app.assignments.search_entry, "C1"
        )
        app.transfer_catalog_selection_to_queue.assert_not_called()

class QuantityDialogTests(unittest.TestCase):
    def setUp(self):
        self.tcl = tk.Tcl()

    def dialog(self, values):
        dialog = StockQuantityDialog.__new__(StockQuantityDialog)
        dialog.result = None
        dialog.quantity_inputs = {
            product_id: (tk.StringVar(self.tcl, value=value), Mock()) for product_id, value in values.items()
        }
        dialog.destroy = Mock()
        return dialog

    def test_all_quantities_are_required_before_any_products_are_assigned(self):
        for invalid in ("", " ", "-1", "2.5", "abc", "9,000", str(2 ** 63)):
            with self.subTest(invalid=invalid), patch("ui.desktop.dialogs.messagebox.showerror") as error:
                dialog = self.dialog({"P1": "7", "P2": invalid})
                dialog.confirm()
                self.assertIsNone(dialog.result)
                dialog.destroy.assert_not_called()
                error.assert_called_once()
                dialog.quantity_inputs["P2"][1].focus_set.assert_called_once()

    def test_confirm_accepts_separate_manual_quantities_including_zero(self):
        dialog = self.dialog({"P1": " 12 ", "P2": "0"})
        dialog.confirm()
        self.assertEqual(dialog.result, {"P1": 12, "P2": 0})
        dialog.destroy.assert_called_once()

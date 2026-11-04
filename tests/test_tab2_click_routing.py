"""Tab 2: a normal click transfers with known stock, Shift opens the stock dialog,
and a quick queue transfer brings hot sellers that are sitting in on-hand."""

from __future__ import annotations

from pathlib import Path
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mapper.persistence.database import WarehouseDatabase
from ui.desktop.app import WarehouseMapperApp
from ui.desktop.assignment_actions import AssignmentActions
from ui.desktop.catalog_actions import CatalogActions
from ui.desktop.location_assignment_view import LocationAssignmentView

FIRST_TIME = "2026-10-31T08:00:00+07:00"
HOT = "12251K97T01"
HOT_TWIN = "12251K97T02"


class Actions(CatalogActions, AssignmentActions):
    pass


class ViewRoutingTests(unittest.TestCase):
    def test_normal_click_transfers_and_shift_opens_stock_dialog(self) -> None:
        for handler, callback in (
            ("_handle_catalog_transfer_click", "on_catalog_to_queue"),
            ("_handle_queue_move_click", "on_queue_to_hand"),
        ):
            for held, clicked, quick in (
                (False, False, True), (True, False, False), (False, True, False), (True, True, False),
            ):
                with self.subTest(handler=handler, held=held, clicked=clicked):
                    action = Mock()
                    view = SimpleNamespace(whole_mode=held, _shift_clicked=clicked, **{callback: action})
                    getattr(LocationAssignmentView, handler)(view)
                    action.assert_called_once_with(to_shelf=quick)
                    self.assertFalse(view._shift_clicked)

    def test_on_hand_button_keeps_shift_for_whole_batch(self) -> None:
        for held, clicked, whole in ((False, False, False), (True, False, True), (False, True, True)):
            with self.subTest(held=held, clicked=clicked):
                action = Mock()
                view = SimpleNamespace(whole_mode=held, _shift_clicked=clicked, on_assign_address=action)
                LocationAssignmentView._handle_assign_click(view)
                action.assert_called_once_with(whole_mode=whole)

    def test_each_press_replaces_a_stale_shift_flag(self) -> None:
        for handler in (
            "_on_assign_button_press", "_on_catalog_transfer_button_press", "_on_queue_move_button_press",
        ):
            with self.subTest(handler=handler):
                view = SimpleNamespace(_shift_clicked=True)
                getattr(LocationAssignmentView, handler)(view, SimpleNamespace(state=0))
                self.assertFalse(view._shift_clicked)
                getattr(LocationAssignmentView, handler)(view, SimpleNamespace(state=1))
                self.assertTrue(view._shift_clicked)


class ActionDefaultTests(unittest.TestCase):
    """Without an explicit flag the actions follow the held Shift key."""

    def make_app(self, shift: bool) -> Actions:
        app = Actions()
        app.root = Mock()
        app.database = Mock()
        app.database.assign_catalog_direct_to_slot.return_value = 1
        app.database.capture_shift_transfer.return_value = {"slot_id": 7, "products": []}
        app.assignments = SimpleNamespace(
            whole_mode=shift, queue_tree=Mock(), catalog_tree=Mock(),
            set_queue_button_clicks=Mock(), revert_button=Mock(),
        )
        app.assignments.queue_tree.selection.return_value = (f"product::{HOT}",)
        app.assignments.queue_tree.get_children.return_value = (f"product::{HOT}",)
        app.assignments.catalog_tree.selection.return_value = (f"catalog::{HOT}",)
        app.products = {HOT: "Bolts"}
        app.product_brand_names = {HOT: "Bolts"}
        app.catalog_products = {HOT: ("Bolts", "Bolt")}
        app.committed_locations = {}
        app.committed_placements = {}
        app.staged_assignments = {}
        app.pending_unassignments = set()
        app.on_hand_products = {}
        app.transferred_stock = {}
        app.selected_address = SimpleNamespace(slot_id=7, slot_name="L1-1A1-1", ghost=False)
        app.queue_shift_timer = None
        app.queue_shift_clicks = 0
        app.reconcile_inventory_products = Mock()
        app.status_text = Mock()
        return app

    def test_default_route_for_catalog_and_queue(self) -> None:
        for method in ("assign_catalog_selection_to_address", "assign_queue_selection_to_address"):
            for shift, override, quick in (
                (False, None, True), (True, None, False), (True, True, True), (False, False, False),
            ):
                with self.subTest(method=method, shift=shift, override=override):
                    app = self.make_app(shift)
                    with patch("ui.desktop.assignment_actions.StockQuantityDialog") as dialog:
                        dialog.return_value.result = {HOT: 12}
                        getattr(app, method)(to_shelf=override)
                    call = app.database.assign_catalog_direct_to_slot.call_args
                    if quick:
                        dialog.assert_not_called()
                        self.assertEqual(call.kwargs, {"default_stock": 999})
                    else:
                        dialog.assert_called_once()
                        self.assertEqual(call.kwargs, {"quantities": {HOT: 12}})

    def test_normal_click_with_several_catalog_products_points_to_shift(self) -> None:
        app = self.make_app(shift=False)
        app.catalog_products[HOT_TWIN] = ("Washers", "Washer")
        app.assignments.catalog_tree.selection.return_value = (f"catalog::{HOT}", f"catalog::{HOT_TWIN}")
        app.assignments.search_location_text = Mock()
        app.assignments.search_location_label = Mock()
        with patch("ui.desktop.assignment_actions.StockQuantityDialog") as dialog:
            app.assign_catalog_selection_to_address()
        dialog.assert_not_called()
        app.database.assign_catalog_direct_to_slot.assert_not_called()
        message = app.assignments.search_location_text.set.call_args.args[0]
        self.assertIn("(selected 2)", message)
        self.assertIn("Hold Shift", message)

    def test_pressing_shift_cancels_pending_quick_transfer_clicks(self) -> None:
        app = self.make_app(shift=True)
        app.queue_shift_clicks = 2
        app._on_whole_mode_change(True)
        self.assertEqual(app.queue_shift_clicks, 0)
        app.assignments.set_queue_button_clicks.assert_called_with(None)
        app.database.assign_catalog_direct_to_slot.assert_not_called()

    def test_quick_queue_transfer_includes_on_hand_but_skips_shelved_rows(self) -> None:
        app = self.make_app(shift=False)
        app.products.update({HOT_TWIN: "Washers", "12251K97T03": "Nuts"})
        app.on_hand_products[HOT_TWIN] = SimpleNamespace(stock_qty=5)
        app.committed_locations["12251K97T03"] = "L1-1A1-2"
        app.assignments.queue_tree.get_children.return_value = (
            f"product::{HOT}", f"product::{HOT_TWIN}", "product::12251K97T03",
        )
        for _ in range(3):  # two products need the three-click confirmation
            app.assign_queue_selection_to_address()
        records = app.database.assign_catalog_direct_to_slot.call_args.args[2]
        self.assertEqual(set(records), {HOT, HOT_TWIN})
        self.assertIn("1 brought from on-hand", app.status_text.set.call_args.args[0])


class OnHandHotSellerAppTests(unittest.TestCase):
    """The real app and database: a hot seller in on-hand moves with one normal click."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        db_path = Path(self.temp_dir.name) / "warehouse.db"
        database = WarehouseDatabase(db_path)
        database.commit_shelf("1", "A", [3], {}, set(), side="1")
        database.import_products({HOT: "Brake pad", HOT_TWIN: "Brake shoe"})
        database.add_to_on_hand({HOT: 6}, FIRST_TIME)

        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = WarehouseMapperApp(self.root, database_path=db_path)
        self.app.notebook.select(self.app.assignments)
        view = self.app.assignments
        for variable, value in (
            (view.floor_var, "1"), (view.side_var, "1"), (view.shelf_var, "A"), (view.row_var, "1"), (view.cell_var, "1"),
        ):
            variable.set(value)
        self.app.load_assignment_address()
        view.search_var.set(HOT)
        self.app.refresh_product_lists()

    def click_queue_button(self, *, shift: bool) -> None:
        button = self.app.assignments.queue_move_button
        button.event_generate("<Button-1>", state=1 if shift else 0)
        button.invoke()

    def test_normal_click_brings_on_hand_hot_seller_with_its_stock(self) -> None:
        self.assertIn(HOT, self.app.on_hand_products)
        with patch("ui.desktop.assignment_actions.StockQuantityDialog") as dialog:
            self.click_queue_button(shift=False)

        dialog.assert_not_called()
        placement = self.app.database.get_placement_details()[HOT]
        self.assertEqual((placement.slot_name, placement.stock_qty), ("L1-1A1-1", 6))
        self.assertNotIn(HOT, self.app.database.get_on_hand_products())
        self.assertNotIn(HOT, self.app.on_hand_products)
        self.assertNotIn(f"hand::{HOT}", self.app.assignments.on_hand_tree.get_children())
        self.assertIn(f"saved::{HOT}", self.app.assignments.contents_tree.get_children())
        self.assertIn("1 brought from on-hand", self.app.status_text.get())

        # Revert puts it back in on-hand with the same stock.
        with patch("tkinter.messagebox.askyesno", return_value=True):
            self.app.revert_latest_shift_transfer()
        self.assertNotIn(HOT, self.app.database.get_placement_details())
        self.assertEqual(self.app.database.get_on_hand_products()[HOT].stock_qty, 6)
        self.assertIn(f"hand::{HOT}", self.app.assignments.on_hand_tree.get_children())

    def test_shift_click_assigns_on_hand_hot_seller_with_entered_stock(self) -> None:
        self.app.assignments.queue_tree.selection_set(f"product::{HOT}")
        with patch("ui.desktop.assignment_actions.StockQuantityDialog") as dialog, patch.object(
            self.app.root, "wait_window"
        ):
            dialog.return_value.result = {HOT: 4}
            self.click_queue_button(shift=True)

        self.assertEqual(dialog.call_args.kwargs["initial_quantities"], {HOT: 6})
        placement = self.app.database.get_placement_details()[HOT]
        self.assertEqual((placement.slot_name, placement.stock_qty), ("L1-1A1-1", 4))
        self.assertNotIn(HOT, self.app.database.get_on_hand_products())
        self.assertIsNone(self.app.last_shift_transfer)

    def test_shelved_hot_seller_is_still_not_moved_by_quick_transfer(self) -> None:
        with patch("ui.desktop.assignment_actions.StockQuantityDialog"):
            self.click_queue_button(shift=False)
        self.app.assignments.search_var.set(HOT)
        self.app.refresh_product_lists()
        self.app.assignments.cell_var.set("2")
        self.app.load_assignment_address()

        with patch("ui.desktop.assignment_actions.play_error_sound") as sound:
            self.click_queue_button(shift=False)
        sound.assert_called_once()
        self.assertEqual(self.app.database.get_placement_details()[HOT].slot_name, "L1-1A1-1")
        self.assertEqual(
            self.app.assignments.search_location_text.get(), f"Not assigned: {HOT} is already at L1-1A1-1."
        )


if __name__ == "__main__":
    unittest.main()

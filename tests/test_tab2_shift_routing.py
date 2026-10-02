"""Tab 2 transfers directly by default and stages products while Shift is held."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from ui.desktop.assignment_actions import AssignmentActions
from ui.desktop.catalog_actions import CatalogActions
from ui.desktop.location_assignment_view import LocationAssignmentView


class TransferApp(AssignmentActions, CatalogActions):
    pass


class Tab2ShiftRoutingTests(TestCase):
    def make_app(self, shift=False):
        app = TransferApp()
        app.root = Mock()
        app.database = Mock()
        app.database.assign_catalog_direct_to_slot.return_value = 1
        app.database.force_pull_to_queue.return_value = (0, 0)
        app.assignments = SimpleNamespace(
            whole_mode=shift,
            queue_tree=Mock(),
            catalog_tree=Mock(),
            on_hand_tree=Mock(),
            set_queue_button_clicks=Mock(),
            revert_button=Mock(),
        )
        app.assignments.queue_tree.selection.return_value = ("product::ABCDE1",)
        app.assignments.queue_tree.get_children.return_value = ("product::ABCDE1",)
        app.assignments.catalog_tree.selection.return_value = ("catalog::ABCDE1",)
        app.products = {"ABCDE1": "Bolts"}
        app.catalog_products = {"ABCDE1": ("Bolts", "Bolt")}
        app.committed_placements = {}
        app.on_hand_products = {}
        app.returned_queue_products = {}
        app.staged_assignments = {}
        app.pending_unassignments = set()
        app.transferred_stock = {}
        app.selected_address = SimpleNamespace(slot_id=7, slot_name="F1-A1-1")
        app.queue_shift_timer = None
        app.queue_shift_clicks = 0
        app.apply_inventory_changes = Mock()
        app.reconcile_inventory_products = Mock()
        app.status_text = Mock()
        return app

    def test_click_routes_use_shift_state_and_mouse_press_state(self):
        for handler, callback in (
            ("_handle_catalog_transfer_click", "on_catalog_to_queue"),
            ("_handle_queue_move_click", "on_queue_to_hand"),
        ):
            for held, clicked, direct in (
                (False, False, True), (True, False, False),
                (False, True, False), (True, True, False),
            ):
                with self.subTest(handler=handler, held=held, clicked=clicked):
                    action = Mock()
                    view = SimpleNamespace(whole_mode=held, _shift_clicked=clicked)
                    setattr(view, callback, action)
                    getattr(LocationAssignmentView, handler)(view)
                    action.assert_called_once_with(to_shelf=direct)
                    self.assertFalse(view._shift_clicked)

    def test_mouse_press_clears_stale_shift_click(self):
        for handler in (
            "_on_assign_button_press", "_on_catalog_transfer_button_press",
            "_on_queue_move_button_press",
        ):
            with self.subTest(handler=handler):
                view = SimpleNamespace(_shift_clicked=True)
                getattr(LocationAssignmentView, handler)(view, SimpleNamespace(state=0))
                self.assertFalse(view._shift_clicked)

    def test_labels_follow_routes_and_restore_after_shift_release(self):
        view = SimpleNamespace(
            whole_mode=False, assign_button=Mock(), catalog_transfer_button=Mock(),
            queue_move_button=Mock(), on_whole_mode_change=Mock(),
        )
        LocationAssignmentView.set_whole_mode(view, True)
        view.catalog_transfer_button.configure.assert_called_with(
            text="Transfer selected to total queue", style="TButton",
        )
        view.queue_move_button.configure.assert_called_with(
            text="Move selected → on-hand", style="TButton",
        )
        view.assign_button.configure.assert_called_with(
            text="Transfer ALL on-hand → shelf (Whole mode)",
            style="WholeMode.Commit.TButton",
        )
        LocationAssignmentView.set_whole_mode(view, False)
        view.catalog_transfer_button.configure.assert_called_with(
            text="Transfer selected → shelf (stock 999)", style="WholeMode.TButton",
        )
        LocationAssignmentView.set_queue_button_clicks(view)
        view.queue_move_button.configure.assert_called_with(
            text="Transfer queue → shelf (stock 999)", style="WholeMode.TButton",
        )

    def test_catalog_default_and_explicit_routes(self):
        for shift, override, direct in (
            (False, None, True), (True, None, False),
            (True, False, False), (False, False, False), (True, True, True),
        ):
            with self.subTest(shift=shift, override=override):
                app = self.make_app(shift)
                app.transfer_catalog_selection_to_queue(to_shelf=override)
                if direct:
                    app.database.assign_catalog_direct_to_slot.assert_called_once()
                    self.assertEqual(
                        app.database.assign_catalog_direct_to_slot.call_args.kwargs,
                        {"default_stock": 999},
                    )
                    app.database.force_pull_to_queue.assert_not_called()
                else:
                    app.database.assign_catalog_direct_to_slot.assert_not_called()
                    app.database.force_pull_to_queue.assert_called_once()

    def test_queue_default_and_explicit_routes(self):
        for shift, override, direct in (
            (False, None, True), (True, None, False),
            (True, False, False), (False, False, False), (True, True, True),
        ):
            with self.subTest(shift=shift, override=override):
                app = self.make_app(shift)
                with patch("ui.desktop.assignment_actions.StockQuantityDialog") as dialog:
                    dialog.return_value.result = {"ABCDE1": 12}
                    app.move_selected_to_on_hand(to_shelf=override)
                if direct:
                    app.database.assign_catalog_direct_to_slot.assert_called_once()
                    dialog.assert_not_called()
                    app.database.add_to_on_hand.assert_not_called()
                else:
                    app.database.assign_catalog_direct_to_slot.assert_not_called()
                    dialog.assert_called_once()
                    self.assertEqual(
                        app.database.add_to_on_hand.call_args.args[0], {"ABCDE1": 12},
                    )

    def test_default_queue_transfer_keeps_three_click_confirmation(self):
        app = self.make_app()
        app.products["ABCDE2"] = "Washers"
        app.assignments.queue_tree.get_children.return_value = (
            "product::ABCDE1", "product::ABCDE2",
        )
        app.move_selected_to_on_hand()
        app.assignments.set_queue_button_clicks.assert_called_with(2)
        app.database.assign_catalog_direct_to_slot.assert_not_called()
        app.move_selected_to_on_hand()
        app.assignments.set_queue_button_clicks.assert_called_with(1)
        app.database.assign_catalog_direct_to_slot.assert_not_called()
        app.move_selected_to_on_hand()
        app.database.assign_catalog_direct_to_slot.assert_called_once()
        self.assertEqual(app.queue_shift_clicks, 0)

    def test_shift_press_resets_pending_direct_transfer_confirmation(self):
        app = self.make_app(shift=True)
        app.queue_shift_clicks = 2
        app._on_whole_mode_change(True)
        self.assertEqual(app.queue_shift_clicks, 0)
        app.database.assign_catalog_direct_to_slot.assert_not_called()

    def test_on_hand_assign_still_uses_shift_for_whole_batch(self):
        for shift in (False, True):
            with self.subTest(shift=shift):
                callback = Mock()
                view = SimpleNamespace(
                    whole_mode=shift, _shift_clicked=False, on_assign_address=callback,
                )
                LocationAssignmentView._handle_assign_click(view)
                callback.assert_called_once_with(whole_mode=shift)

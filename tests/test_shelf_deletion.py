"""Exercise Tab 1's delete button against an isolated SQLite database."""

from __future__ import annotations

import tkinter as tk
from unittest.mock import patch

from mapper.persistence.database import WarehouseDatabase
from tests.support import WorkspaceTestCase
from ui.desktop.app import WarehouseMapperApp


class ShelfDeletionTests(WorkspaceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.path = self.folder / "warehouse.db"
        database = WarehouseDatabase(self.path)
        database.import_products({"P1": "Bolts"})
        self.shelf_id = database.save_shelf("1", "A", [2], side="1")
        self.other_id = database.save_shelf("1", "B", [1], side="1")
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = WarehouseMapperApp(self.root, self.path)
        self.dialogs = self.enterContext(patch("ui.desktop.shelf_actions.messagebox"))
        self.dialogs.askyesno.return_value = True
        self.select_shelf(self.shelf_id)

    def select_shelf(self, shelf_id: int) -> None:
        label = next(label for label, saved_id in self.app.shelf_choices.items() if saved_id == shelf_id)
        self.app.shelf_selector.set(label)

    def delete(self) -> None:
        self.app.delete_shelf_button.invoke()

    def test_delete_empty_selected_shelf_without_loading(self) -> None:
        first_slot = self.app.database.get_slot_address("1", "1", "A", 1, 1)
        self.delete()
        reopened = WarehouseDatabase(self.path)
        self.assertIsNone(reopened.get_shelf_id("1", "A", side="1"))
        self.assertIsNone(reopened.get_slot_by_id(first_slot.slot_id))
        self.assertEqual(reopened.get_shelf_id("1", "B", side="1"), self.other_id)
        self.assertNotIn(self.shelf_id, self.app.shelf_choices.values())
        self.assertNotIn(self.shelf_id, self.app.shelf_browser.shelf_choices.values())
        self.assertNotIn(self.shelf_id, self.app.primal_view.shelf_choices.values())
        self.assertEqual(self.app.database.get_products(), [("P1", "Bolts")])
        self.assertIn("Deleted", self.app.status_text.get())
        self.dialogs.askyesno.assert_called_once()
        self.dialogs.showerror.assert_not_called()

    def test_delete_loaded_shelf_clears_editor_browser_and_address(self) -> None:
        self.app.load_selected_shelf()
        self.app.shelf_browser.show_saved_shelf(self.shelf_id)
        self.app.selected_address = self.app.database.get_slot_address("1", "1", "A", 1, 1)
        self.delete()
        self.assertIsNone(self.app.current_shelf_id)
        self.assertEqual(self.app.current_layout, [])
        self.assertIsNone(self.app.preview_key)
        self.assertIsNone(self.app.selected_address)
        self.assertFalse(self.app.has_pending_changes())
        self.assertIsNone(self.app.shelf_browser.current_key)
        self.assertEqual(self.app.shelf_browser.shelf_grid.cells, {})
        self.assertEqual(self.app.shelf_selector.get(), "")

    def test_delete_clears_preview_of_saved_shelf(self) -> None:
        self.app.load_selected_shelf()
        self.app.build_shelf_preview(switch_tab=False)
        self.assertIsNone(self.app.shelf_browser.current_shelf_id)
        self.assertTrue(self.app.shelf_browser.shelf_grid.cells)
        self.delete()
        self.assertEqual(self.app.shelf_browser.shelf_grid.cells, {})

    def test_delete_other_shelf_preserves_loaded_editor_and_browser(self) -> None:
        self.app.load_selected_shelf()
        self.app.shelf_browser.show_saved_shelf(self.shelf_id)
        state = self.app._editor_state()
        self.select_shelf(self.other_id)
        self.delete()
        self.assertEqual(self.app.current_shelf_id, self.shelf_id)
        self.assertEqual(self.app._editor_state(), state)
        self.assertEqual(self.app.shelf_browser.current_shelf_id, self.shelf_id)
        self.assertEqual(self.app.preview_key, ("1", "1", "A"))
        self.dialogs.showerror.assert_not_called()

    def test_cancel_keeps_shelf_and_editor(self) -> None:
        self.app.load_selected_shelf()
        self.dialogs.askyesno.return_value = False
        self.delete()
        self.assertEqual(self.app.database.get_shelf_id("1", "A"), self.shelf_id)
        self.assertEqual(self.app.current_shelf_id, self.shelf_id)

    def test_pending_changes_are_preserved(self) -> None:
        self.app.load_selected_shelf()
        self.app.designer.shelf_code_var.set("C")
        self.delete()
        self.assertEqual(self.app.database.get_shelf_id("1", "A"), self.shelf_id)
        self.assertEqual(self.app.designer.shelf_code_var.get(), "C")
        self.assertTrue(self.app.has_pending_changes())
        self.dialogs.askyesno.assert_not_called()
        self.dialogs.showinfo.assert_called_once()

    def test_no_selection_requests_a_shelf(self) -> None:
        self.app.shelf_selector.set("")
        self.delete()
        self.assertEqual(len(self.app.database.list_shelves()), 2)
        self.dialogs.showinfo.assert_called_once()
        self.dialogs.askyesno.assert_not_called()

    def test_regular_products_prevent_deletion(self) -> None:
        address = self.app.database.get_slot_address("1", "1", "A", 1, 1)
        self.app.database.add_to_on_hand({"P1": 12}, "2026-10-02T08:00:00+07:00")
        self.app.database.assign_on_hand_to_slot(address.slot_id, "2026-10-02T08:01:00+07:00", ["P1"])
        self.delete()
        self.assertEqual(self.app.database.get_shelf_id("1", "A"), self.shelf_id)
        self.assertEqual(self.app.database.get_placement_details()["P1"].stock_qty, 12)
        self.dialogs.showerror.assert_called_once()

    def test_exception_products_prevent_deletion(self) -> None:
        address = self.app.database.get_slot_address("1", "1", "A", 1, 1)
        self.app.database.assign_exception("E1", address.slot_id, product_name="Exception", stock_qty=3)
        self.delete()
        self.assertEqual(self.app.database.get_shelf_id("1", "A"), self.shelf_id)
        self.assertEqual(self.app.database.get_product_locations("E1"), [address.slot_name])
        self.dialogs.showerror.assert_called_once()

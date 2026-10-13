"""Only Tab 2's saved manual stock edits advance the displayed timestamp."""

import tkinter as tk
from contextlib import closing
from datetime import datetime
from unittest.mock import patch

from mapper.persistence.database import WarehouseDatabase
from tests.support import WorkspaceTestCase
from ui.desktop.app import WarehouseMapperApp


FIRST = "2026-10-13T09:00:00+07:00"
SECOND = "2026-10-13T10:00:00+07:00"


class StockModificationTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.folder / "warehouse.db"
        db = WarehouseDatabase(self.path)
        db.import_products({"P1": "Bolts"})
        db.commit_shelf("1", "A", [2], {}, set(), side="1")
        self.first = db.get_slot_address("1", "1", "A", 1, 1)
        self.second = db.get_slot_address("1", "1", "A", 1, 2)
        db.add_to_on_hand({"P1": 12}, FIRST)
        db.assign_on_hand_to_slot(self.first.slot_id, FIRST, ["P1"])
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = WarehouseMapperApp(self.root, self.path)
        self.app.notebook.select(self.app.assignments)
        self.app.selected_address = self.first
        self.app.refresh_address_contents()
        self.tree = self.app.assignments.contents_tree
        self.tree.selection_set("saved::P1")

    def displayed_time(self):
        return self.tree.set("saved::P1", "stock_modified_at")

    def test_button_updates_time_only_after_saving_changed_stock(self):
        self.assertEqual(self.tree.heading("stock_modified_at")["text"],
                         "Latest stock modification")
        self.assertEqual(self.displayed_time(), "")
        for quantity in (None, 12):
            with patch("ui.desktop.assignment_actions.simpledialog.askinteger", return_value=quantity):
                self.app.modify_selected_stock()
            self.assertEqual(self.displayed_time(), "")

        with patch("ui.desktop.assignment_actions.simpledialog.askinteger", return_value=15), \
             patch("ui.desktop.assignment_actions.datetime") as clock:
            clock.now.return_value = datetime.fromisoformat(SECOND)
            self.app.modify_selected_stock()
        self.assertEqual(self.tree.set("saved::P1", "stock_qty"), "15")
        self.assertEqual(self.displayed_time(), SECOND.replace("T", " "))
        self.assertEqual(self.tree.set("saved::P1", "assigned_at"), FIRST.replace("T", " "))
        for quantity in (None, 15):
            with patch("ui.desktop.assignment_actions.simpledialog.askinteger", return_value=quantity):
                self.app.modify_selected_stock()
            self.assertEqual(self.displayed_time(), SECOND.replace("T", " "))

        db = WarehouseDatabase(self.path)
        self.assertEqual(db.get_slot_stock_modifications(self.first.slot_id), {"P1": SECOND})
        # Other stock writes and ordinary moves must preserve the button's timestamp.
        db.update_placement_stock("P1", 18, expected_slot_id=self.first.slot_id)
        db.import_products({"P1": "Renamed bolts"})
        db.swap_slot_contents(self.first.slot_id, self.second.slot_id)
        db.move_slot_to_on_hand(self.second.slot_id, SECOND, ["P1"])
        db.dequeue_on_hand(["P1"], SECOND)
        db.add_to_on_hand({"P1": 18}, SECOND)
        db.assign_on_hand_to_slot(self.first.slot_id, SECOND, ["P1"])
        self.app.refresh_address_contents()
        self.assertEqual(self.displayed_time(), SECOND.replace("T", " "))

    def test_on_hand_button_time_survives_reassignment(self):
        db = self.app.database
        db.update_placement_stock("P1", 13, modified_at=FIRST)
        db.move_slot_to_on_hand(self.first.slot_id, FIRST, ["P1"])
        self.app.reload_database_state()
        self.app.refresh_on_hand_queue()
        self.app.assignments.on_hand_tree.selection_set("hand::P1")
        with patch("ui.desktop.assignment_actions.simpledialog.askinteger", return_value=20), \
             patch("ui.desktop.assignment_actions.datetime") as clock:
            clock.now.return_value = datetime.fromisoformat(SECOND)
            self.app.modify_on_hand_stock()
        for quantity in (None, 20):
            with patch("ui.desktop.assignment_actions.simpledialog.askinteger", return_value=quantity), \
                 patch("ui.desktop.assignment_actions.datetime") as clock:
                clock.now.return_value = datetime.fromisoformat(FIRST)
                self.app.modify_on_hand_stock()
        db.assign_on_hand_to_slot(self.first.slot_id, SECOND, ["P1"])
        self.app.refresh_address_contents()
        self.assertEqual(self.displayed_time(), SECOND.replace("T", " "))

    def test_failed_edit_rolls_back_stock_and_time(self):
        db = self.app.database
        with self.assertRaises(KeyError):
            db.update_placement_stock("P1", 20, expected_slot_id=self.second.slot_id, modified_at=SECOND)
        with self.assertRaises(ValueError):
            db.update_placement_stock("P1", 20, modified_at="2026-10-13T10:00:00")
        self.assertEqual(db.get_slot_contents(self.first.slot_id)[0][2].stock_qty, 12)
        self.assertEqual(db.get_slot_stock_modifications(self.first.slot_id), {})
        # Upgrade an existing database without fabricating modification history.
        with closing(db.connect()) as connection, connection:
            connection.execute("DROP TABLE stock_modifications")
        reopened = WarehouseDatabase(self.path)
        self.assertEqual(reopened.get_slot_stock_modifications(self.first.slot_id), {})
        self.assertEqual(reopened.get_slot_contents(self.first.slot_id)[0][2].stock_qty, 12)

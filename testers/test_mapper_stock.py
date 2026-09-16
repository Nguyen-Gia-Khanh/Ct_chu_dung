"""Quantity validation, assignment timing, and migration checks without a display."""

import sqlite3
import tempfile
import tkinter as tk
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mapper.app import WarehouseMapperApp
from mapper.assignment_view import StockQuantityDialog
from mapper.database import Placement, WarehouseDatabase


CELL_ONE = "1-A-R01-C01"
CELL_TWO = "1-A-R01-C02"
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
        app.selected_slot = CELL_ONE
        app.current_layout = [2]
        app.preview_key = ("1", "A")
        app.status_text = Mock()
        app.refresh_all_views = Mock()
        app.refresh_product_queue = Mock()
        app.refresh_shelf_selector = Mock()
        app.build_shelf_preview = Mock(return_value=True)
        app._editor_state = Mock(return_value=())
        return app

    def stage(self, app, quantities, instant):
        app.assignments.queue_tree.selection.return_value = tuple(f"product::{pid}" for pid in quantities)
        with patch("mapper.app.StockQuantityDialog", return_value=SimpleNamespace(result=quantities)), \
                patch("mapper.app.datetime") as clock:
            clock.now.return_value = datetime.fromisoformat(instant)
            app.assign_selected_products()
            clock.now.assert_called_once_with()
        return datetime.fromisoformat(instant).astimezone().isoformat(timespec="seconds")

    def test_separate_assignment_times_and_quantities_survive_later_commit_and_reopen(self):
        app = self.make_app()
        first = self.stage(app, {"P1": 7}, FIRST_TIME)
        second = self.stage(app, {"P2": 43}, SECOND_TIME)
        expected = {"P1": Placement(CELL_ONE, 7, first), "P2": Placement(CELL_ONE, 43, second)}
        self.assertEqual(app.staged_assignments, expected)
        self.assertEqual(self.database.get_placements(), {})
        app.refresh_slot_contents()
        values = {call.kwargs["iid"]: call.kwargs["values"] for call in app.assignments.contents_tree.insert.call_args_list}
        self.assertEqual(values["staged::P1"], ("P1", "Bolts", 7, first.replace("T", " "), "Staged"))
        with patch("mapper.app.messagebox.showinfo"):
            self.assertTrue(app.commit_changes())
        self.assertEqual(app.staged_assignments, {})
        self.assertEqual(app.committed_placements, expected)
        self.assertEqual(WarehouseDatabase(self.database.path).get_placement_details(), expected)
        with closing(self.database.connect()) as connection:
            for row in connection.execute("SELECT assigned_at, committed_at FROM placements"):
                added = datetime.fromisoformat(row["assigned_at"])
                committed = datetime.fromisoformat(row["committed_at"]).replace(tzinfo=timezone.utc)
                self.assertGreater(committed, added)
        app.assignments.contents_tree.insert.reset_mock()
        app.refresh_slot_contents()
        values = {call.kwargs["iid"]: call.kwargs["values"] for call in app.assignments.contents_tree.insert.call_args_list}
        self.assertEqual(values["saved::P2"], ("P2", "Washers", 43, second.replace("T", " "), "Saved"))

    def test_multi_selection_can_have_different_quantities(self):
        app = self.make_app()
        assigned_at = self.stage(app, {"P1": 0, "P2": 58}, FIRST_TIME)
        self.assertEqual(app.staged_assignments["P1"], Placement(CELL_ONE, 0, assigned_at))
        self.assertEqual(app.staged_assignments["P2"], Placement(CELL_ONE, 58, assigned_at))
        self.assertEqual(app.visible_slot_counts(), {CELL_ONE: (0, 2)})

    def test_cancel_does_not_dequeue_or_record_time(self):
        app = self.make_app()
        app.assignments.queue_tree.selection.return_value = ("product::P1", "product::P2")
        with patch("mapper.app.StockQuantityDialog", return_value=SimpleNamespace(result=None)), \
                patch("mapper.app.datetime") as clock:
            app.assign_selected_products()
            clock.now.assert_not_called()
        self.assertEqual(app.staged_assignments, {})
        self.assertEqual(self.database.get_placements(), {})
        app.refresh_all_views.assert_not_called()

    def test_return_and_reassign_record_new_details_and_leave_other_product_unchanged(self):
        app = self.make_app()
        self.stage(app, {"P1": 12, "P2": 3}, FIRST_TIME)
        with patch("mapper.app.messagebox.showinfo"):
            app.commit_changes()
        original_p2 = app.committed_placements["P2"]
        app.assignments.contents_tree.selection.return_value = ("saved::P1",)
        app.return_selected_to_queue()
        app.selected_slot = CELL_TWO
        assigned_at = self.stage(app, {"P1": 9}, SECOND_TIME)
        with patch("mapper.app.messagebox.showinfo"):
            app.commit_changes()
        self.assertEqual(self.database.get_placement_details(), {
            "P1": Placement(CELL_TWO, 9, assigned_at), "P2": original_p2,
        })

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

    def test_failed_commit_keeps_staged_quantity_and_original_assignment_time(self):
        app = self.make_app()
        instant = self.stage(app, {"P1": 7}, FIRST_TIME)
        with patch.object(self.database, "commit_shelf", side_effect=sqlite3.OperationalError("database is locked")), \
                patch("mapper.app.messagebox.showerror"):
            self.assertFalse(app.commit_changes())
        self.assertEqual(app.staged_assignments, {"P1": Placement(CELL_ONE, 7, instant)})
        self.assertEqual(self.database.get_placements(), {})

    def test_legacy_migration_preserves_commit_time_and_does_not_invent_stock_or_added_time(self):
        self.database.commit_shelf("1", "A", [2], {}, set())
        # Recreate the exact original placements schema and an existing record.
        with closing(self.database.connect()) as connection, connection:
            slot_id = connection.execute("SELECT slot_id FROM slots WHERE slot_name = ?", (CELL_ONE,)).fetchone()[0]
            original_slots = [tuple(row) for row in connection.execute("SELECT * FROM slots ORDER BY slot_id")]
            connection.execute("DROP TABLE placements")
            connection.execute("""
                CREATE TABLE placements (
                    product_id TEXT PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
                    slot_id INTEGER NOT NULL REFERENCES slots(slot_id) ON DELETE RESTRICT,
                    assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute(
                "INSERT INTO placements VALUES (?, ?, ?)", ("P1", slot_id, "1999-12-30 08:00:00"),
            )
        migrated = WarehouseDatabase(self.database.path)
        self.assertEqual(migrated.get_placements(), {"P1": CELL_ONE})
        self.assertEqual(migrated.get_placement_details(), {"P1": Placement(CELL_ONE, None, None)})
        with closing(migrated.connect()) as connection:
            row = connection.execute("SELECT * FROM placements").fetchone()
            self.assertEqual(row["committed_at"], "1999-12-30 08:00:00")
            self.assertEqual([tuple(row) for row in connection.execute("SELECT * FROM slots ORDER BY slot_id")], original_slots)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        # Opening twice must not rename the real assignment timestamp or data.
        reopened = WarehouseDatabase(self.database.path)
        self.assertEqual(reopened.get_placement_details(), migrated.get_placement_details())
        reopened.commit_shelf("1", "A", [2], {"P2": Placement(CELL_ONE, 34, SECOND_TIME)}, set())
        self.assertEqual(reopened.get_placement_details()["P1"], Placement(CELL_ONE, None, None))
        self.assertEqual(reopened.get_placement_details()["P2"], Placement(CELL_ONE, 34, SECOND_TIME))
        app = self.make_app()
        app.reload_database_state()
        app.refresh_slot_contents()
        values = {call.kwargs["iid"]: call.kwargs["values"] for call in app.assignments.contents_tree.insert.call_args_list}
        self.assertEqual(values["saved::P1"], ("P1", "Bolts", "Unknown", "Unknown", "Saved"))


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
            with self.subTest(invalid=invalid), patch("mapper.assignment_view.messagebox.showerror") as error:
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


if __name__ == "__main__":
    unittest.main()

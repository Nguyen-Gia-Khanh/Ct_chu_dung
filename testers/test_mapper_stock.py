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
from mapper.assignment_view import AssignmentView, StockQuantityDialog
from mapper.common import make_slot_name
from mapper.database import Placement, ReturnedQueueProduct, WarehouseDatabase


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
        app.returned_queue_products = {}
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

    def test_selected_slot_contents_put_newest_at_bottom_and_unknown_time_first(self):
        app = self.make_app()
        app.products["P3"] = "Legacy item"
        app.committed_locations = {"P1": CELL_ONE, "P2": CELL_ONE, "P3": CELL_ONE}
        app.committed_placements = {
            "P1": Placement(CELL_ONE, 1, FIRST_TIME),
            "P2": Placement(CELL_ONE, 2, SECOND_TIME),
            "P3": Placement(CELL_ONE, None, None),
        }

        app.refresh_slot_contents()

        inserted_ids = [
            call.kwargs["iid"]
            for call in app.assignments.contents_tree.insert.call_args_list
        ]
        self.assertEqual(inserted_ids, ["saved::P3", "saved::P1", "saved::P2"])

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

    def test_transfer_staged_product_preserves_stock_and_unassigns(self):
        app = self.make_app()
        instant = self.stage(app, {"P1": 15}, FIRST_TIME)
        self.assertEqual(app.staged_assignments["P1"], Placement(CELL_ONE, 15, instant))
        app.assignments.contents_tree.selection.return_value = ("staged::P1",)
        app.transfer_selected_products()
        self.assertNotIn("P1", app.staged_assignments)
        self.assertEqual(app.transferred_stock.get("P1"), 15)
        app.refresh_all_views.assert_called()

    def test_transfer_saved_product_preserves_stock_and_marks_unassignment(self):
        app = self.make_app()
        self.stage(app, {"P1": 22}, FIRST_TIME)
        with patch("mapper.app.messagebox.showinfo"):
            app.commit_changes()
        app.assignments.contents_tree.selection.return_value = ("saved::P1",)
        app.transfer_selected_products()
        self.assertIn("P1", app.pending_unassignments)
        self.assertEqual(app.transferred_stock.get("P1"), 22)
        app.refresh_all_views.assert_called()

    def test_catalog_transfer_adds_product_to_queue_and_keeps_catalog_record(self):
        self.database.import_catalog_products({"C1": ("Catalog bolt", "C bolt")})
        app = self.make_app()
        app.catalog_products = {"C1": ("Catalog bolt", "C bolt")}
        app.assignments.catalog_tree = Mock()
        app.assignments.catalog_tree.selection.return_value = ("catalog::C1",)
        app.reload_database_state = Mock()

        app.transfer_catalog_selection_to_queue()

        self.assertIn(("C1", "Catalog bolt"), self.database.get_products())
        self.assertIn(("C1", "Catalog bolt", "C bolt"), self.database.get_catalog_products())
        app.reload_database_state.assert_called_once()
        app.refresh_all_views.assert_called()

    def test_catalog_transfer_moves_saved_product_to_queue_with_stock(self):
        placement = Placement(CELL_ONE, 27, FIRST_TIME)
        self.database.import_catalog_products({"P1": ("Bolts", "Bolt")})
        self.database.commit_shelf("1", "A", [2], {"P1": placement}, set())
        app = self.make_app()
        app.catalog_products = {"P1": ("Bolts", "Bolt")}
        app.committed_placements = {"P1": placement}
        app.committed_locations = {"P1": CELL_ONE}
        app.assignments.catalog_tree = Mock()
        app.assignments.catalog_tree.selection.return_value = ("catalog::P1",)
        app.reload_database_state = Mock()

        app.transfer_catalog_selection_to_queue()

        self.assertIn("P1", app.pending_unassignments)
        self.assertEqual(app.transferred_stock["P1"], 27)
        self.assertIn(("P1", "Bolts", "Bolt"), self.database.get_catalog_products())

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

    def test_exact_shared_search_reports_saved_or_unassigned_location(self):
        app = self.make_app()
        app.catalog_products = {"P1": ("Bolts", "Bolt"), "C1": ("Catalog bolt", "C bolt")}
        app.assignments.search_var = Mock()
        app.assignments.search_location_text = Mock()
        app.assignments.search_location_label = Mock()
        app.committed_placements = {"P1": Placement(CELL_ONE, 8, FIRST_TIME)}

        app.refresh_search_location("P1")
        app.assignments.search_location_text.set.assert_called_with(
            f"Already at {CELL_ONE}"
        )
        app.assignments.search_location_label.configure.assert_called_with(
            foreground="#c62828"
        )

        app.pending_unassignments.add("P1")
        app.refresh_search_location("P1")
        app.assignments.search_location_text.set.assert_called_with(
            f"Already at {CELL_ONE} (queued for transfer)"
        )

        app.refresh_search_location("C1")
        app.assignments.search_location_text.set.assert_called_with(
            "Not in"
        )
        app.assignments.search_location_label.configure.assert_called_with(
            foreground="#555555"
        )

    def test_catalog_refresh_uses_the_queue_search_field(self):
        app = self.make_app()
        app.catalog_products = {
            "C1": ("Catalog bolt", "C bolt"),
            "C2": ("Catalog washer", "C washer"),
        }
        app.catalog_search = {
            product_id: " ".join((product_id, *names)).casefold()
            for product_id, names in app.catalog_products.items()
        }
        app.assignments.search_var = Mock()
        app.assignments.search_var.get.return_value = "C bolt"
        app.assignments.catalog_tree = Mock()
        app.assignments.catalog_tree.get_children.return_value = ()
        app.assignments.catalog_count_text = Mock()
        app.refresh_search_location = Mock()

        app.refresh_catalog()

        app.assignments.catalog_tree.insert.assert_called_once_with(
            "", "end", iid="catalog::C1", values=("C1", "Catalog bolt", "C bolt")
        )
        app.refresh_search_location.assert_called_once_with("C bolt")

    def test_queue_search_index_includes_shortened_name(self):
        self.database.import_products({"P1": ("Bolts", "Fastener alias")})
        app = self.make_app()
        app.refresh_product_lists = Mock()

        app.reload_database_state()

        self.assertIn("fastener alias", app.product_search["P1"])

    def test_total_queue_shows_returned_stock_first_with_highlight(self):
        app = self.make_app()
        app.product_search = {"P1": "p1 bolts", "P2": "p2 washers"}
        app.search_after_id = None
        app.returned_queue_products = {
            "P1": ReturnedQueueProduct("P1", 42, SECOND_TIME)
        }
        app.assignments.search_var = Mock()
        app.assignments.search_var.get.return_value = ""
        app.assignments.on_hand_tree = Mock()
        app.assignments.queue_tree.get_children.return_value = ()
        app.assignments.queue_count_text = Mock()

        WarehouseMapperApp.refresh_product_queue(app)

        calls = app.assignments.queue_tree.insert.call_args_list
        self.assertEqual(
            calls[0].kwargs,
            {
                "iid": "product::P1",
                "values": ("P1", "Bolts", "42"),
                "tags": ("returned",),
            },
        )
        self.assertEqual(
            calls[1].kwargs,
            {
                "iid": "product::P2",
                "values": ("P2", "Washers", ""),
                "tags": (),
            },
        )

    def test_move_returned_product_to_on_hand_prefills_and_clears_marker(self):
        self.database.add_to_on_hand({"P1": 42}, FIRST_TIME)
        self.database.dequeue_on_hand(["P1"], SECOND_TIME)
        app = self.make_app()
        app.returned_queue_products = self.database.get_returned_queue_products()
        app.assignments.queue_tree.selection.return_value = ("product::P1",)

        with patch("mapper.app.StockQuantityDialog") as mock_dialog, patch(
            "mapper.app.datetime"
        ) as clock:
            mock_dialog.return_value = SimpleNamespace(result={"P1": 42})
            clock.now.return_value = datetime.fromisoformat(SECOND_TIME)

            app.move_selected_to_on_hand()

        self.assertEqual(
            mock_dialog.call_args.kwargs["initial_quantities"], {"P1": 42}
        )
        self.assertEqual(self.database.get_returned_queue_products(), {})
        self.assertEqual(self.database.get_on_hand_products()["P1"].stock_qty, 42)

    def test_dequeue_action_moves_only_selected_on_hand_rows(self):
        self.database.add_to_on_hand({"P1": 12, "P2": 4}, FIRST_TIME)
        app = self.make_app()
        app.on_hand_products = self.database.get_on_hand_products()
        app.assignments.on_hand_tree = Mock()
        app.assignments.on_hand_tree.get_children.return_value = ()
        app.assignments.on_hand_tree.selection.return_value = ("hand::P1",)
        app.assignments.on_hand_count_text = Mock()

        with patch("mapper.app.datetime") as clock:
            clock.now.return_value = datetime.fromisoformat(SECOND_TIME)
            app.dequeue_selected_on_hand()

        self.assertEqual(set(self.database.get_on_hand_products()), {"P2"})
        self.assertEqual(
            self.database.get_returned_queue_products()["P1"].stock_qty, 12
        )
        app.refresh_all_views.assert_called_once()

    def test_assign_prefills_transferred_stock_and_cleans_up(self):
        app = self.make_app()
        app.transferred_stock["P1"] = 42
        app.assignments.queue_tree.selection.return_value = ("product::P1",)
        with patch("mapper.app.StockQuantityDialog") as mock_dialog, patch("mapper.app.datetime") as clock:
            mock_dialog.return_value = SimpleNamespace(result={"P1": 42})
            clock.now.return_value = datetime.fromisoformat(SECOND_TIME)
            app.assign_selected_products()
            mock_dialog.assert_called_once()
            _, kwargs = mock_dialog.call_args
            self.assertEqual(kwargs.get("initial_quantities"), {"P1": 42})
        self.assertNotIn("P1", app.transferred_stock)
        self.assertEqual(app.staged_assignments["P1"].stock_qty, 42)

    def test_preassign_queue_stock_stores_quantity(self):
        app = self.make_app()
        app.assignments.queue_tree.selection.return_value = ("product::P1", "product::P2")
        with patch("mapper.app.StockQuantityDialog") as mock_dialog:
            mock_dialog.return_value = SimpleNamespace(result={"P1": 10, "P2": 20})
            app.preassign_queue_stock()
        self.assertEqual(app.transferred_stock, {"P1": 10, "P2": 20})
        app.refresh_product_queue.assert_called()

    def test_return_selected_to_queue_clears_transferred_stock(self):
        app = self.make_app()
        app.transferred_stock["P1"] = 99
        app.assignments.contents_tree.selection.return_value = ("staged::P1",)
        app.return_selected_to_queue()
        self.assertNotIn("P1", app.transferred_stock)


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


class AssignmentViewInteractionTests(unittest.TestCase):
    def test_double_click_product_id_copies_only_the_id_and_highlights_row(self):
        view = AssignmentView.__new__(AssignmentView)
        view.contents_tree = Mock()
        view.contents_tree.identify_row.return_value = "saved::P1"
        view.contents_tree.identify_column.return_value = "#1"
        view.contents_tree.item.return_value = ("P1", "Bolts", 7, FIRST_TIME, "Saved")
        view.clipboard_clear = Mock()
        view.clipboard_append = Mock()
        view.update_idletasks = Mock()
        view.copy_status_text = Mock()

        result = view.copy_product_id(SimpleNamespace(x=10, y=20))

        self.assertEqual(result, "break")
        view.contents_tree.selection_set.assert_called_once_with("saved::P1")
        view.contents_tree.focus.assert_called_once_with("saved::P1")
        view.clipboard_append.assert_called_once_with("P1")
        view.copy_status_text.set.assert_called_once_with("Copied P1")

    def test_double_click_any_product_cell_copies_the_row_id(self):
        view = AssignmentView.__new__(AssignmentView)
        view.contents_tree = Mock()
        view.contents_tree.identify_row.return_value = "saved::P1"
        view.contents_tree.identify_column.return_value = "#2"
        view.contents_tree.item.return_value = ("P1", "Bolts", 7, FIRST_TIME, "Saved")
        view.clipboard_clear = Mock()
        view.clipboard_append = Mock()
        view.update_idletasks = Mock()
        view.copy_status_text = Mock()

        self.assertEqual(view.copy_product_id(SimpleNamespace(x=120, y=20)), "break")
        view.clipboard_append.assert_called_once_with("P1")


if __name__ == "__main__":
    unittest.main()

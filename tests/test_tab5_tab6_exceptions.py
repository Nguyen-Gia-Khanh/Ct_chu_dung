"""Tab 5 moves must preserve Tab 6 exception records and address navigation."""

from contextlib import closing
import sqlite3
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

from mapper.core.common import iso_timestamp
from mapper.persistence.database import Placement, WarehouseDatabase
from tests.support import WorkspaceTestCase
from ui.desktop.cell_transfer_view import CellTransferView
from ui.desktop.exceptions_view import ExceptionsView


FIRST = "2026-10-10T08:00:00+07:00"
SECOND = "2026-10-10T09:00:00+07:00"


class ExceptionCellTransferTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.db = WarehouseDatabase(self.folder / "warehouse.db")
        self.db.import_products({"P1": "Regular left", "P2": "Regular right"})
        self.db.commit_shelf("1", "A", [2], {}, set(), side="1")
        self.db.commit_shelf("2", "B", [2], {}, set(), side="2")
        self.left = self.db.get_slot_address("1", "1", "A", 1, 1)
        self.other = self.db.get_slot_address("1", "1", "A", 1, 2)
        self.right = self.db.get_slot_address("2", "2", "B", 1, 1)
        self.empty = self.db.get_slot_address("2", "2", "B", 1, 2)
        self.db.add_to_on_hand({"P1": 12, "P2": 4}, FIRST)
        self.db.assign_on_hand_to_slot(self.left.slot_id, FIRST, ["P1"])
        self.db.assign_on_hand_to_slot(self.right.slot_id, SECOND, ["P2"])
        self.db.assign_exception("E1", self.left.slot_id, FIRST, 5, "Exception left")
        self.db.assign_exception("E1", self.other.slot_id, SECOND, 7)
        self.db.assign_exception("E2", self.right.slot_id, SECOND, None, "Exception right")
        self.db.add_staged_to_catalog(["E1"])
        self.db.append_pending_to_csv(self.folder / "products.csv", ["E1"])

    def snapshot(self):
        with closing(self.db.connect()) as connection:
            return {
                table: [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                for table in ("placements", "exception_placements", "wait_to_update_csv",
                              "hot_sellers", "catalog_products", "queue_origins")
            }

    def assert_moved_records(self, before, destinations):
        after = self.snapshot()
        for table, rows in before.items():
            expected = []
            for row in rows:
                moved = dict(row)
                if table in ("placements", "exception_placements", "wait_to_update_csv"):
                    if row["slot_id"] in destinations:
                        address = destinations[row["slot_id"]]
                        moved["slot_id"] = address.slot_id
                        if table == "wait_to_update_csv":
                            moved["slot_name"] = address.slot_name
                expected.append(moved)
            self.assertEqual(after[table], expected, table)

    def test_switch_mixed_cells_updates_staging_and_survives_reopen(self):
        before = self.snapshot()
        self.assertEqual(self.db.swap_slot_contents(self.left.slot_id, self.right.slot_id), (2, 2))
        self.assert_moved_records(before, {self.left.slot_id: self.right, self.right.slot_id: self.left})
        self.db = WarehouseDatabase(self.db.path)
        self.assertEqual(set(self.db.find_product_locations("E1")[1]),
                         {self.right.slot_name, self.other.slot_name})
        self.db.remove_exception_from_slot("E1", self.right.slot_id)
        self.assertEqual(self.db.find_product_locations("E1")[1], (self.other.slot_name,))

    def test_switch_same_exception_in_both_cells_preserves_each_record(self):
        self.db.assign_exception("E1", self.right.slot_id, SECOND, 11)
        before = self.snapshot()
        self.assertEqual(self.db.swap_slot_contents(self.left.slot_id, self.right.slot_id), (2, 3))
        self.assert_moved_records(before, {self.left.slot_id: self.right, self.right.slot_id: self.left})

    def test_switch_into_empty_cell_moves_exceptions_and_reports_full_count(self):
        before = self.snapshot()
        self.assertEqual(self.db.swap_slot_contents(self.left.slot_id, self.empty.slot_id), (2, 0))
        self.assert_moved_records(before, {self.left.slot_id: self.empty})
        self.assertEqual(self.db.get_slot_contents(self.left.slot_id), [])

    def test_combine_both_directions_preserves_other_locations(self):
        for source, target in ((self.left, self.right), (self.right, self.left)):
            with self.subTest(source=source.slot_name):
                before = self.snapshot()
                self.assertEqual(self.db.combine_slot_contents(source.slot_id, target.slot_id), 2)
                self.assert_moved_records(before, {source.slot_id: target})
                self.assertEqual(self.db.get_slot_contents(source.slot_id), [])
                self.assertEqual(len(self.db.get_slot_contents(target.slot_id)), 4)
                # Restore the original records for the reverse-direction check.
                with closing(self.db.connect()) as connection, connection:
                    for table in ("placements", "exception_placements", "wait_to_update_csv"):
                        connection.execute(f"DELETE FROM {table}")
                        for row in before[table]:
                            columns = ", ".join(row)
                            placeholders = ", ".join("?" for _ in row)
                            connection.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                                               tuple(row.values()))

    def test_exception_only_cell_can_be_combined(self):
        before = self.snapshot()
        self.assertEqual(self.db.combine_slot_contents(self.other.slot_id, self.empty.slot_id), 1)
        self.assert_moved_records(before, {self.other.slot_id: self.empty})
        self.assertEqual(self.db.get_slot_contents(self.other.slot_id), [])

    def test_combine_overlap_rejects_exception_and_regular_duplicates_atomically(self):
        for product_id in ("E1", "P1"):
            with self.subTest(product_id=product_id):
                self.db.assign_exception(product_id, self.right.slot_id, SECOND, 3)
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, "already in both cells"):
                    self.db.combine_slot_contents(self.left.slot_id, self.right.slot_id)
                self.assertEqual(self.snapshot(), before)
                self.db.remove_exception_from_slot(product_id, self.right.slot_id)

    def test_failed_staging_write_rolls_back_regular_and_exception_moves(self):
        with closing(self.db.connect()) as connection, connection:
            connection.execute("""
                CREATE TRIGGER reject_stage BEFORE INSERT ON wait_to_update_csv
                BEGIN SELECT RAISE(ABORT, 'staging failed'); END
            """)
        before = self.snapshot()
        for operation in (self.db.swap_slot_contents, self.db.combine_slot_contents):
            with self.subTest(operation=operation.__name__):
                with self.assertRaisesRegex(sqlite3.IntegrityError, "staging failed"):
                    operation(self.left.slot_id, self.right.slot_id)
                self.assertEqual(self.snapshot(), before)

    def test_confirmed_merge_keeps_shared_stock_and_preserves_registration(self):
        self.db.assign_exception("E1", self.right.slot_id, SECOND, 11)
        self.db.assign_exception("P1", self.right.slot_id, SECOND, 3)
        with closing(self.db.connect()) as connection, connection:
            connection.execute("UPDATE wait_to_update_csv SET csv_updated = 0 "
                               "WHERE product_id = 'E1' AND slot_id = ?", (self.right.slot_id,))
        self.assertEqual(self.db.combine_slot_contents(
            self.left.slot_id, self.right.slot_id, merge_duplicates=True), 2)
        self.assertEqual(self.db.get_slot_contents(self.left.slot_id), [])
        contents = {pid: placement for pid, _name, placement in self.db.get_slot_contents(self.right.slot_id)}
        self.assertEqual(len(contents), 4)
        self.assertEqual(contents["E1"], Placement(self.right.slot_name, 5, iso_timestamp(SECOND)))
        self.assertEqual(contents["P1"], Placement(self.right.slot_name, 12, iso_timestamp(SECOND)))
        stages = [row for row in self.db.get_exception_staging()
                  if row["product_id"] == "E1" and row["slot_id"] == self.right.slot_id]
        self.assertEqual(len(stages), 1)
        self.assertEqual((stages[0]["csv_updated"], stages[0]["catalog_updated"]), (False, True))
        self.assertEqual(set(self.db.find_product_locations("E1")[1]),
                         {self.right.slot_name, self.other.slot_name})
        self.db.remove_exception_from_slot("E1", self.right.slot_id)
        self.assertEqual(self.db.find_product_locations("E1")[1], (self.other.slot_name,))

    def test_merge_with_regular_target_and_unknown_quantity_keeps_one_placement(self):
        self.db.assign_exception("P2", self.left.slot_id, FIRST, None)
        self.db.combine_slot_contents(self.left.slot_id, self.right.slot_id, merge_duplicates=True)
        contents = [placement for pid, _name, placement in self.db.get_slot_contents(self.right.slot_id)
                    if pid == "P2"]
        self.assertEqual(contents, [Placement(self.right.slot_name, 4, iso_timestamp(SECOND))])

    def test_merge_never_adds_counts_or_overflows(self):
        self.db.assign_exception("E1", self.right.slot_id, SECOND, 9_223_372_036_854_775_807)
        self.db.combine_slot_contents(self.left.slot_id, self.right.slot_id, merge_duplicates=True)
        self.assertEqual(self.db.get_placement_details()['E1'].stock_qty,5)


class ExceptionTransferViewTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.db = WarehouseDatabase(self.folder / "warehouse.db")
        self.db.commit_shelf("1", "A", [2], {}, set(), side="1")
        self.first = self.db.get_slot_address("1", "1", "A", 1, 1)
        self.second = self.db.get_slot_address("1", "1", "A", 1, 2)
        self.db.assign_exception("E1", self.first.slot_id, FIRST, 5, "Exception")
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.view = ExceptionsView(self.root, self.db)
        self.view.pack(fill="both", expand=True)

    @staticmethod
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from ExceptionTransferViewTests.descendants(child)

    def test_enter_in_each_address_field_loads_cell_without_assigning(self):
        self.root.deiconify()
        self.root.update()
        self.view.product_id_var.set("NEW")
        variables = (self.view.floor_var, self.view.side_var, self.view.shelf_var,
                     self.view.row_var, self.view.cell_var)
        entries = [widget for widget in self.descendants(self.view)
                   if isinstance(widget, ttk.Entry)
                   and str(widget.cget("textvariable")) in {str(var) for var in variables}]
        self.assertEqual(len(entries), 5)
        before = self.db.get_all_placement_items()
        for entry in entries:
            with self.subTest(variable=entry.cget("textvariable")):
                self.view.selected_address = self.first
                self.view.cell_var.set("2")
                entry.focus_force()
                self.root.update()
                entry.event_generate("<Return>")
                self.root.update()
                self.assertEqual(self.view.selected_address, self.second)
        self.assertEqual(self.db.get_all_placement_items(), before)
        self.view.cell_var.set("999")
        entries[-1].event_generate("<Return>")
        self.root.update()
        self.assertIsNone(self.view.selected_address)
        self.assertEqual(self.view.cell_contents_tree.get_children(), ())

    @patch("ui.desktop.cell_transfer_view.messagebox.askyesno", return_value=True)
    def test_tab5_transfer_refreshes_tab6_locations_and_keeps_edited_inputs(self, _confirm):
        self.view.product_id_var.set("E1")
        self.view.find_product()
        self.view.load_address()
        self.view.product_name_var.set("Unsaved name")
        self.view.qty_var.set("19")
        transfer = CellTransferView(self.root, self.db, can_change=lambda: True,
                                    on_changed=lambda *_args: transfer.refresh())
        self.addCleanup(transfer.destroy)
        transfer.refresh()
        transfer.left.load_shelf(self.first.shelf_id, select_slot_id=self.first.slot_id)
        transfer.right.load_shelf(self.second.shelf_id, select_slot_id=self.second.slot_id)
        transfer.swap_cells()
        # Tab activation calls refresh after the user returns from Tab 5.
        self.view.refresh()
        self.assertEqual(self.view.pending_tree.item("stage-E1", "values")[2], self.second.slot_name)
        self.assertIn(self.second.slot_name, self.view.found_locations_text.get())
        self.assertNotIn(self.first.slot_name, self.view.found_locations_text.get())
        self.assertEqual(self.view.cell_contents_tree.get_children(), ())
        self.assertEqual(self.view.product_name_var.get(), "Unsaved name")
        self.assertEqual(self.view.qty_var.get(), "19")
        self.assertEqual(transfer.right.selected_product_count, 1)
        self.assertEqual(self.db.get_slot_contents(self.second.slot_id)[0][2],
                         Placement(self.second.slot_name, 5, iso_timestamp(FIRST)))

    def test_duplicate_popup_discard_and_merge_buttons(self):
        self.db.assign_exception("E1", self.second.slot_id, SECOND, 7)
        self.root.deiconify()
        self.root.update()
        transfer = CellTransferView(self.root, self.db, can_change=lambda: True,
                                    on_changed=lambda *_args: transfer.refresh())
        transfer.pack()
        self.addCleanup(transfer.destroy)
        transfer.refresh()
        transfer.left.load_shelf(self.first.shelf_id, select_slot_id=self.first.slot_id)
        transfer.right.load_shelf(self.second.shelf_id, select_slot_id=self.second.slot_id)

        def click_popup_button(label):
            for widget in self.descendants(self.root):
                if isinstance(widget, ttk.Button) and widget.cget("text") == label:
                    widget.invoke()
                    return
            # Close a failed dialog lookup so the test reports instead of hanging.
            for widget in self.root.winfo_children():
                if isinstance(widget, tk.Toplevel):
                    widget.event_generate("<Escape>")
            self.fail(f"Popup button not found: {label}")

        before = self.db.get_all_placement_items()
        self.root.after(200, lambda: click_popup_button("Discard move"))
        with patch("ui.desktop.cell_transfer_view.messagebox.askyesno") as confirmation:
            transfer.combine_cells(transfer.left, transfer.right)
            confirmation.assert_not_called()
        self.assertEqual(self.db.get_all_placement_items(), before)
        self.assertIn("Both cells are unchanged", transfer.status_text.get())

        self.root.after(200, lambda: click_popup_button("Combine locations"))
        with patch("ui.desktop.cell_transfer_view.messagebox.askyesno") as confirmation:
            transfer.combine_cells(transfer.left, transfer.right)
            confirmation.assert_not_called()
        self.assertEqual(self.db.get_slot_contents(self.first.slot_id), [])
        self.assertEqual(self.db.get_slot_contents(self.second.slot_id)[0][2],
                         Placement(self.second.slot_name, 5, iso_timestamp(SECOND)))

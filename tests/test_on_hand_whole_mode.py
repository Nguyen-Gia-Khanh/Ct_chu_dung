"""Tests for Tab 2 Whole Mode and direct catalog-to-shelf transfer."""

from __future__ import annotations

from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from mapper.persistence.database import Placement, WarehouseDatabase
from ui.desktop.app import WarehouseMapperApp
from ui.desktop.location_assignment_view import LocationAssignmentView


FIRST_TIME = "2026-09-25T08:00:00+00:00"
SECOND_TIME = "2026-09-25T08:30:00+00:00"


class DatabaseDirectCatalogToShelfTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "warehouse.db"
        self.database = WarehouseDatabase(self.db_path)
        self.database.commit_shelf("1", "A", [3], {}, set(), side="1")
        self.address = self.database.get_slot_address("1", "1", "A", 1, 2)
        self.assertIsNotNone(self.address)

    def test_assign_catalog_direct_to_slot_sets_default_stock_999(self) -> None:
        catalog_products = {
            "CAT-1": ("Product One", "P1"),
            "CAT-2": ("Product Two", "P2"),
        }
        moved = self.database.assign_catalog_direct_to_slot(
            self.address.slot_id,
            FIRST_TIME,
            catalog_products,
            default_stock=999,
        )
        self.assertEqual(moved, 2)

        placements = self.database.get_placement_details()
        self.assertEqual(
            placements,
            {
                "CAT-1": Placement(self.address.slot_name, 999, FIRST_TIME),
                "CAT-2": Placement(self.address.slot_name, 999, FIRST_TIME),
            },
        )
        # Products should also be present in products table
        products = dict(self.database.get_products())
        self.assertIn("CAT-1", products)
        self.assertIn("CAT-2", products)

    def test_assign_catalog_direct_clears_previous_placements_and_queues(self) -> None:
        self.database.import_products({"CAT-1": "Product One"})
        self.database.add_to_on_hand({"CAT-1": 15}, FIRST_TIME)
        self.assertIn("CAT-1", self.database.get_on_hand_products())

        moved = self.database.assign_catalog_direct_to_slot(
            self.address.slot_id,
            SECOND_TIME,
            {"CAT-1": ("Product One", "P1")},
            default_stock=999,
        )
        self.assertEqual(moved, 1)
        self.assertNotIn("CAT-1", self.database.get_on_hand_products())
        self.assertEqual(
            self.database.get_placement_details()["CAT-1"],
            Placement(self.address.slot_name, 999, SECOND_TIME),
        )


class Tab2WholeModeViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def test_whole_mode_toggles_button_texts_and_badge(self) -> None:
        view = LocationAssignmentView(
            self.root,
            on_search=lambda: None,
            on_queue_to_hand=lambda: None,
            on_catalog_to_queue=lambda: None,
            on_catalog_activate=lambda _e: None,
            on_load_address=lambda: None,
            on_assign_address=lambda: None,
            on_dequeue_hand=lambda: None,
            on_selected_to_hand=lambda: None,
            on_slot_to_hand=lambda: None,
            on_modify_hand_stock=lambda: None,
            on_modify_stock=lambda: None,
            on_upload=lambda: None,
            on_modify_location=lambda: None,
        )
        view.pack()

        # Initial normal mode
        self.assertFalse(view.whole_mode)
        self.assertEqual(
            view.assign_button.cget("text"),
            "Assign selected on-hand → loaded address",
        )
        self.assertEqual(
            view.catalog_transfer_button.cget("text"),
            "Assign selected catalog → loaded address",
        )

        # Toggle whole mode on
        view.set_whole_mode(True)
        self.assertTrue(view.whole_mode)
        self.assertEqual(
            view.assign_button.cget("text"),
            "Transfer ALL on-hand → shelf (Whole mode)",
        )
        self.assertEqual(
            view.assign_button.cget("style"),
            "WholeMode.Commit.TButton",
        )
        self.assertEqual(
            view.catalog_transfer_button.cget("text"),
            "Transfer selected → shelf (stock 999)",
        )
        self.assertEqual(
            view.catalog_transfer_button.cget("style"),
            "WholeMode.TButton",
        )

        # Toggle whole mode off
        view.set_whole_mode(False)
        self.assertFalse(view.whole_mode)
        self.assertEqual(
            view.assign_button.cget("text"),
            "Assign selected on-hand → loaded address",
        )
        self.assertEqual(
            view.assign_button.cget("style"),
            "Commit.TButton",
        )
        self.assertEqual(
            view.catalog_transfer_button.cget("text"),
            "Assign selected catalog → loaded address",
        )
        self.assertEqual(
            view.catalog_transfer_button.cget("style"),
            "TButton",
        )


class Tab2WholeModeAppWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "warehouse.db"
        database = WarehouseDatabase(self.db_path)
        database.commit_shelf("1", "A", [3], {}, set(), side="1")
        database.import_products({"P1": "Item 1", "P2": "Item 2"})
        database.import_catalog_products({"C1": ("Cat Item 1", ""), "C2": ("Cat Item 2", "")})
        database.add_to_on_hand({"P1": 10, "P2": 20}, FIRST_TIME)

        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = WarehouseMapperApp(self.root, database_path=self.db_path)
        # Select Tab 2
        self.app.notebook.select(self.app.assignments)

        # Load address 1-1-A-1-1
        self.app.assignments.floor_var.set("1")
        self.app.assignments.side_var.set("1")
        self.app.assignments.shelf_var.set("A")
        self.app.assignments.row_var.set("1")
        self.app.assignments.cell_var.set("1")
        self.app.load_assignment_address()
        self.assertIsNotNone(self.app.selected_address)

    def test_assign_on_hand_whole_mode_transfers_all_items_without_selection(self) -> None:
        # No rows selected in on_hand_tree
        self.app.assignments.on_hand_tree.selection_set()
        self.assertEqual(len(self.app.assignments.on_hand_tree.selection()), 0)

        # Execute assignment with whole_mode = True
        self.app.assign_on_hand_to_address(whole_mode=True)

        # Both P1 and P2 should now be placed on the shelf
        placements = self.app.database.get_placement_details()
        self.assertIn("P1", placements)
        self.assertIn("P2", placements)
        self.assertEqual(placements["P1"].slot_name, "L1-1A1-1")
        self.assertEqual(placements["P2"].slot_name, "L1-1A1-1")
        self.assertEqual(placements["P1"].stock_qty, 10)
        self.assertEqual(placements["P2"].stock_qty, 20)
        # On-hand queue is now empty
        self.assertEqual(len(self.app.on_hand_products), 0)

    def test_transfer_catalog_to_shelf_direct_sets_stock_999(self) -> None:
        # Select C1 in catalog_tree
        self.app.assignments.catalog_tree.selection_set("catalog::C1")

        # Execute catalog transfer with to_shelf = True
        self.app.assign_catalog_selection_to_address(whole_mode=True)

        placements = self.app.database.get_placement_details()
        self.assertIn("C1", placements)
        self.assertEqual(placements["C1"].slot_name, "L1-1A1-1")
        self.assertEqual(placements["C1"].stock_qty, 999)
        self.assertIn("Assigned 1 catalog product(s) directly to L1-1A1-1 with stock 999", self.app.status_text.get())

    def test_assign_button_shift_click_triggers_whole_mode(self) -> None:
        # Generate Button-1 with state=1 (Shift held)
        self.app.assignments.assign_button.event_generate("<Button-1>", state=1)
        self.app.assignments.assign_button.invoke()

        placements = self.app.database.get_placement_details()
        self.assertIn("P1", placements)
        self.assertIn("P2", placements)
        self.assertEqual(len(self.app.on_hand_products), 0)

    def test_catalog_transfer_button_shift_click_triggers_shelf_transfer(self) -> None:
        self.app.assignments.catalog_tree.selection_set("catalog::C2")
        self.app.assignments.catalog_transfer_button.event_generate("<Button-1>", state=1)
        self.app.assignments.catalog_transfer_button.invoke()

        placements = self.app.database.get_placement_details()
        self.assertIn("C2", placements)
        self.assertEqual(placements["C2"].stock_qty, 999)
        self.assertEqual(placements["C2"].slot_name, "L1-1A1-1")

    def test_normal_assign_only_moves_selected_on_hand_product(self) -> None:
        # Only select P1
        self.app.assignments.on_hand_tree.selection_set("hand::P1")
        self.app.assignments.assign_button.invoke()

        placements = self.app.database.get_placement_details()
        self.assertIn("P1", placements)
        self.assertNotIn("P2", placements)
        self.assertIn("P2", self.app.on_hand_products)

    def test_catalog_shift_transfer_one_id_constraint(self) -> None:
        # Select both C1 and C2
        self.app.assignments.catalog_tree.selection_set("catalog::C1", "catalog::C2")
        self.app.assign_catalog_selection_to_address(whole_mode=True)

        # Execution denied: neither in placements
        placements = self.app.database.get_placement_details()
        self.assertNotIn("C1", placements)
        self.assertNotIn("C2", placements)
        self.assertIn("only affects 1 product ID", self.app.assignments.search_location_text.get())
        self.assertEqual(str(self.app.assignments.search_location_label.cget("foreground")), "#c62828")

        # Select only C1
        self.app.assignments.catalog_tree.selection_set("catalog::C1")
        self.app.assign_catalog_selection_to_address(whole_mode=True)

        placements = self.app.database.get_placement_details()
        self.assertIn("C1", placements)
        self.assertEqual(placements["C1"].stock_qty, 999)
        self.assertEqual(str(self.app.assignments.revert_button.cget("state")), "normal")

        # C1 must NOT be in queue_tree
        queue_ids = [
            item.removeprefix("product::")
            for item in self.app.assignments.queue_tree.get_children()
        ]
        self.assertNotIn("C1", queue_ids)

        # C1 must be in contents_tree (loaded address contents)
        content_ids = [
            item.removeprefix("saved::")
            for item in self.app.assignments.contents_tree.get_children()
        ]
        self.assertIn("C1", content_ids)

        # C1 location column in catalog_tree must show loaded slot
        catalog_vals = self.app.assignments.catalog_tree.item("catalog::C1", "values")
        self.assertEqual(catalog_vals[2], "L1-1A1-1")

    def test_queue_shift_transfer_prefix_constraint(self) -> None:
        # Add products with different first 5 chars to queue
        self.app.database.import_products({
            "12251-K97-T01": "Part 1",
            "12252-K97-T01": "Part 2",
        })
        self.app.reload_database_state()
        self.app.refresh_all_views()

        # In queue tree, we have products with different prefixes (12251 vs 12252)
        self.app.assign_queue_selection_to_address(whole_mode=True)

        placements = self.app.database.get_placement_details()
        self.assertNotIn("12251-K97-T01", placements)
        self.assertNotIn("12252-K97-T01", placements)
        self.assertIn("must share the same first 5 characters", self.app.assignments.search_location_text.get())
        self.assertEqual(str(self.app.assignments.search_location_label.cget("foreground")), "#c62828")
        self.assertEqual(self.app.queue_shift_clicks, 0)

    def test_queue_shift_transfer_single_item_bypasses_triple_click(self) -> None:
        self.app.database.import_products({
            "12251-K97-T01": "Part 1",
        })
        self.app.reload_database_state()
        self.app.assignments.search_var.set("12251-K97-T01")
        self.app.refresh_product_queue()

        # Single item in queue -> immediate transfer without triple-click
        self.app.assign_queue_selection_to_address(whole_mode=True)

        placements = self.app.database.get_placement_details()
        self.assertIn("12251-K97-T01", placements)
        self.assertEqual(placements["12251-K97-T01"].stock_qty, 999)
        self.assertEqual(str(self.app.assignments.revert_button.cget("state")), "normal")

        # Must NOT be in queue_tree
        queue_ids = [
            item.removeprefix("product::")
            for item in self.app.assignments.queue_tree.get_children()
        ]
        self.assertNotIn("12251-K97-T01", queue_ids)

        # Must appear in loaded address contents_tree
        content_ids = [
            item.removeprefix("saved::")
            for item in self.app.assignments.contents_tree.get_children()
        ]
        self.assertIn("12251-K97-T01", content_ids)

    def test_queue_shift_transfer_triple_click_flow(self) -> None:
        self.app.database.import_products({
            "12251-K97-T01": "Part 1",
            "12251-K97-T02": "Part 2",
        })
        self.app.reload_database_state()
        self.app.assignments.search_var.set("12251")
        self.app.refresh_product_queue()

        # Ensure both are in the queue_tree
        tree_items = [
            item.removeprefix("product::")
            for item in self.app.assignments.queue_tree.get_children()
        ]
        self.assertIn("12251-K97-T01", tree_items)
        self.assertIn("12251-K97-T02", tree_items)

        # Click 1
        self.app.assign_queue_selection_to_address(whole_mode=True)
        self.assertEqual(self.app.queue_shift_clicks, 1)
        self.assertIn("Click 2 more times", str(self.app.assignments.queue_move_button.cget("text")))
        placements = self.app.database.get_placement_details()
        self.assertNotIn("12251-K97-T01", placements)

        # Click 2
        self.app.assign_queue_selection_to_address(whole_mode=True)
        self.assertEqual(self.app.queue_shift_clicks, 2)
        self.assertIn("Click 1 more time", str(self.app.assignments.queue_move_button.cget("text")))
        placements = self.app.database.get_placement_details()
        self.assertNotIn("12251-K97-T01", placements)

        # Click 3 -> Execution
        self.app.assign_queue_selection_to_address(whole_mode=True)
        self.assertEqual(self.app.queue_shift_clicks, 0)
        placements = self.app.database.get_placement_details()
        self.assertIn("12251-K97-T01", placements)
        self.assertIn("12251-K97-T02", placements)
        self.assertEqual(placements["12251-K97-T01"].stock_qty, 999)
        self.assertEqual(placements["12251-K97-T02"].stock_qty, 999)
        self.assertEqual(str(self.app.assignments.revert_button.cget("state")), "normal")

        # Both must be deleted from queue_tree
        queue_ids = [
            item.removeprefix("product::")
            for item in self.app.assignments.queue_tree.get_children()
        ]
        self.assertNotIn("12251-K97-T01", queue_ids)
        self.assertNotIn("12251-K97-T02", queue_ids)

        # Both must appear in contents_tree
        content_ids = [
            item.removeprefix("saved::")
            for item in self.app.assignments.contents_tree.get_children()
        ]
        self.assertIn("12251-K97-T01", content_ids)
        self.assertIn("12251-K97-T02", content_ids)

    def test_revert_latest_shift_transfer(self) -> None:
        # Transfer catalog item C1
        self.app.assignments.catalog_tree.selection_set("catalog::C1")
        self.app.assign_catalog_selection_to_address(whole_mode=True)
        self.assertIn("C1", self.app.database.get_placement_details())
        self.assertEqual(str(self.app.assignments.revert_button.cget("state")), "normal")

        # Now revert it
        with patch("tkinter.messagebox.askyesno", return_value=True):
            self.app.revert_latest_shift_transfer()

        # Placements should no longer contain C1
        self.assertNotIn("C1", self.app.database.get_placement_details())
        self.assertIsNone(self.app.last_shift_transfer)
        self.assertEqual(str(self.app.assignments.revert_button.cget("state")), "disabled")

        # C1 must no longer be in contents_tree
        content_ids = [
            item.removeprefix("saved::")
            for item in self.app.assignments.contents_tree.get_children()
        ]
        self.assertNotIn("C1", content_ids)


if __name__ == "__main__":
    unittest.main()

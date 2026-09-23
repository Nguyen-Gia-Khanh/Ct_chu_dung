"""Atomic cell switch/combine operations and controller direction tests."""

from pathlib import Path
from types import SimpleNamespace
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from mapper.cell_transfer_view import CellTransferPane, CellTransferView
from mapper.common import make_slot_name
from mapper.database import Placement, SlotAddress, WarehouseDatabase


FIRST_TIME = "2026-09-21T08:00:00+00:00"
SECOND_TIME = "2026-09-21T09:00:00+00:00"


class CellTransferDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = WarehouseDatabase(Path(directory.name) / "warehouse.db")
        self.database.import_products(
            {"P1": "Bolts", "P2": "Washers", "P3": "Bearings"}
        )
        self.left_name = make_slot_name("1", "A", 1, 1, side="1")
        self.right_name = make_slot_name("2", "B", 1, 1, side="2")
        self.empty_name = make_slot_name("2", "B", 1, 2, side="2")
        self.left_shelf_id = self.database.commit_shelf(
            "1",
            "A",
            [1],
            {
                "P1": Placement(self.left_name, 12, FIRST_TIME),
                "P2": Placement(self.left_name, 4, SECOND_TIME),
            },
            set(),
            side="1",
        )
        self.right_shelf_id = self.database.commit_shelf(
            "2",
            "B",
            [2],
            {"P3": Placement(self.right_name, 9, FIRST_TIME)},
            set(),
            side="2",
        )
        self.left = self.database.get_slot_by_name(self.left_name)
        self.right = self.database.get_slot_by_name(self.right_name)
        self.empty = self.database.get_slot_by_name(self.empty_name)
        self.assertIsNotNone(self.left)
        self.assertIsNotNone(self.right)
        self.assertIsNotNone(self.empty)

    def test_slot_can_be_resolved_by_name_or_id(self) -> None:
        self.assertEqual(self.database.get_slot_by_id(self.left.slot_id), self.left)
        self.assertEqual(
            self.database.get_slot_by_name(self.left_name.casefold()), self.left
        )

    def test_switch_exchanges_complete_cells_and_preserves_product_details(self) -> None:
        counts = self.database.swap_slot_contents(
            self.left.slot_id,
            self.right.slot_id,
        )

        self.assertEqual(counts, (2, 1))
        self.assertEqual(
            self.database.get_placement_details(),
            {
                "P1": Placement(self.right_name, 12, FIRST_TIME),
                "P2": Placement(self.right_name, 4, SECOND_TIME),
                "P3": Placement(self.left_name, 9, FIRST_TIME),
            },
        )

    def test_switch_with_empty_cell_moves_contents_without_data_loss(self) -> None:
        counts = self.database.swap_slot_contents(
            self.left.slot_id,
            self.empty.slot_id,
        )

        self.assertEqual(counts, (2, 0))
        placements = self.database.get_placement_details()
        self.assertEqual(placements["P1"], Placement(self.empty_name, 12, FIRST_TIME))
        self.assertEqual(placements["P2"], Placement(self.empty_name, 4, SECOND_TIME))
        self.assertEqual(placements["P3"], Placement(self.right_name, 9, FIRST_TIME))

    def test_combine_empties_source_and_keeps_target_contents(self) -> None:
        moved = self.database.combine_slot_contents(
            self.left.slot_id,
            self.right.slot_id,
        )

        self.assertEqual(moved, 2)
        self.assertEqual(self.database.get_slot_contents(self.left.slot_id), [])
        self.assertEqual(
            {item[0] for item in self.database.get_slot_contents(self.right.slot_id)},
            {"P1", "P2", "P3"},
        )
        self.assertEqual(
            self.database.get_placement_details()["P1"],
            Placement(self.right_name, 12, FIRST_TIME),
        )

    def test_same_or_missing_cell_is_rejected_without_changes(self) -> None:
        before = self.database.get_placement_details()

        with self.assertRaises(ValueError):
            self.database.swap_slot_contents(self.left.slot_id, self.left.slot_id)
        with self.assertRaises(ValueError):
            self.database.combine_slot_contents(self.left.slot_id, self.left.slot_id)
        with self.assertRaises(KeyError):
            self.database.swap_slot_contents(self.left.slot_id, 999_999)
        with self.assertRaises(KeyError):
            self.database.combine_slot_contents(999_999, self.right.slot_id)

        self.assertEqual(self.database.get_placement_details(), before)


class CellTransferControllerTests(unittest.TestCase):
    @staticmethod
    def address(slot_id: int, slot_name: str) -> SlotAddress:
        return SlotAddress(slot_id, slot_id, "1", "1", "A", 1, slot_id, slot_name)

    def make_view(self) -> CellTransferView:
        view = CellTransferView.__new__(CellTransferView)
        view.database = Mock()
        view.database.swap_slot_contents.return_value = (2, 3)
        view.database.combine_slot_contents.return_value = 2
        view.left = SimpleNamespace(
            selected_address=self.address(1, "LEFT"),
            selected_product_count=2,
        )
        view.right = SimpleNamespace(
            selected_address=self.address(2, "RIGHT"),
            selected_product_count=3,
        )
        view.on_changed = Mock()
        view.can_change = Mock(return_value=True)
        view.refresh = Mock()
        view.status_text = Mock()
        return view

    @patch("mapper.cell_transfer_view.messagebox.askyesno", return_value=True)
    def test_switch_controller_uses_left_and_right_cells(self, _confirm: Mock) -> None:
        view = self.make_view()

        view.swap_cells()

        view.database.swap_slot_contents.assert_called_once_with(1, 2)
        view.on_changed.assert_called_once()
        view.refresh.assert_called_once()

    @patch("mapper.cell_transfer_view.messagebox.askyesno", return_value=True)
    def test_combine_controller_respects_button_direction(self, _confirm: Mock) -> None:
        view = self.make_view()

        view.combine_cells(view.right, view.left)

        view.database.combine_slot_contents.assert_called_once_with(2, 1)
        view.on_changed.assert_called_once()
        view.refresh.assert_called_once()

    def test_pending_designer_changes_block_cell_operations(self) -> None:
        view = self.make_view()
        view.can_change.return_value = False

        view.swap_cells()
        view.combine_cells(view.left, view.right)

        view.database.swap_slot_contents.assert_not_called()
        view.database.combine_slot_contents.assert_not_called()


class CellTransferPaneCascadeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.root.destroy()

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = WarehouseDatabase(Path(directory.name) / "warehouse.db")
        self.database.import_products(
            {"91201KVB901": "Oil Seal", "P2": "Washers"}
        )
        self.slot_name = make_slot_name("1", "A", 1, 2, side="1")
        self.shelf_id = self.database.commit_shelf(
            "1",
            "A",
            [3],
            {"91201KVB901": Placement(self.slot_name, 5, FIRST_TIME)},
            set(),
            side="1",
        )
        self.pane = CellTransferPane(self.root, "Left Pane", self.database)
        self.pane.refresh()

    def tearDown(self) -> None:
        self.pane.destroy()

    def test_shelf_dropdown_populates_tab6_style(self) -> None:
        expected_label = "Floor 1 — Side 1 — Shelf A"
        self.assertIn(expected_label, self.pane.shelf_choices)
        self.assertIn(expected_label, list(self.pane.shelf_selector["values"]))

    def test_cascade_selection_shelf_row_cell(self) -> None:
        label = "Floor 1 — Side 1 — Shelf A"
        self.pane.shelf_var.set(label)
        self.pane._shelf_changed()

        self.assertEqual(self.pane.current_shelf_id, self.shelf_id)
        self.assertEqual(list(self.pane.row_selector["values"]), ["1"])

        self.pane.row_var.set("1")
        self.pane._row_changed()
        self.assertEqual(list(self.pane.cell_selector["values"]), ["1", "2", "3"])

        self.pane.cell_var.set("2")
        self.pane._cell_changed()
        self.assertIsNotNone(self.pane.selected_address)
        self.assertEqual(self.pane.selected_address.slot_name, self.slot_name)
        self.assertEqual(self.pane.selected_product_count, 1)

    def test_click_cell_synchronizes_cascade_dropdowns(self) -> None:
        label = "Floor 1 — Side 1 — Shelf A"
        self.pane.shelf_var.set(label)
        self.pane._shelf_changed()

        # Select row 1, cell 2
        self.pane._select_coordinates(1, 2)
        self.assertEqual(self.pane.row_var.get(), "1")
        self.assertEqual(self.pane.cell_var.get(), "2")
        self.assertEqual(self.pane.selected_address.slot_name, self.slot_name)

    def test_find_product_id_loads_shelf_and_selects_cell(self) -> None:
        self.pane.search_var.set("91201KVB901")
        self.pane.find()

        self.assertEqual(self.pane.shelf_var.get(), "Floor 1 — Side 1 — Shelf A")
        self.assertEqual(self.pane.row_var.get(), "1")
        self.assertEqual(self.pane.cell_var.get(), "2")
        self.assertIsNotNone(self.pane.selected_address)
        self.assertEqual(self.pane.selected_address.slot_name, self.slot_name)
        self.assertEqual(self.pane.selected_product_count, 1)

    def test_search_entry_auto_selects_all_text_after_find(self) -> None:
        self.pane.search_var.set("91201KVB901")
        self.pane.find()
        self.root.update_idletasks()

        # Selection should cover the entire text so next keystroke or scan wipes it clean
        self.assertTrue(self.pane.search_entry.selection_present())
        self.assertEqual(self.pane.search_entry.index(tk.SEL_FIRST), 0)
        self.assertEqual(self.pane.search_entry.index(tk.SEL_LAST), len(self.pane.search_var.get()))

    def test_newly_created_shelves_appear_in_cascade_selection(self) -> None:
        # Create 3 new shelves
        shelf2_id = self.database.save_shelf("1", "B", [4, 4], side="1")
        shelf3_id = self.database.save_shelf("1", "C", [5, 5, 5], side="1")
        shelf4_id = self.database.save_shelf("2", "A", [6], side="2")

        # Refresh the pane
        self.pane.refresh()

        values = list(self.pane.shelf_selector["values"])
        self.assertIn("Floor 1 — Side 1 — Shelf A", values)
        self.assertIn("Floor 1 — Side 1 — Shelf B", values)
        self.assertIn("Floor 1 — Side 1 — Shelf C", values)
        self.assertIn("Floor 2 — Side 2 — Shelf A", values)

        # Select one of the new shelves and verify cascade dropdowns
        self.pane.shelf_var.set("Floor 1 — Side 1 — Shelf C")
        self.pane._shelf_changed()
        self.assertEqual(self.pane.current_shelf_id, shelf3_id)
        self.assertEqual(list(self.pane.row_selector["values"]), ["1", "2", "3"])

        self.pane.row_var.set("2")
        self.pane._row_changed()
        self.assertEqual(list(self.pane.cell_selector["values"]), ["1", "2", "3", "4", "5"])


if __name__ == "__main__":
    unittest.main()

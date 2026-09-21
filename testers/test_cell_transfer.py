"""Atomic cell switch/combine operations and controller direction tests."""

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from mapper.cell_transfer_view import CellTransferView
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


if __name__ == "__main__":
    unittest.main()

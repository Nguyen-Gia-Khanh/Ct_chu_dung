"""Right-click on Tab 2's shelf steps the selected box to the next cell ID,
moving to cell 1 of the row above at the end of a row."""

from __future__ import annotations

from pathlib import Path
import tempfile
import tkinter as tk
import unittest

from mapper.persistence.database import WarehouseDatabase
from mapper.services.shelf_grid import build_grid, next_cell
from ui.desktop.app import WarehouseMapperApp


def at(grid, row, cell):
    return next(item for item in grid.cells() if (item.row, item.cell) == (row, cell))


class NextCellTests(unittest.TestCase):
    def test_steps_along_the_row_then_up_to_cell_one(self) -> None:
        grid = build_grid("1", "1", "A", [3, 2])
        self.assertEqual(next_cell(grid, at(grid, 1, 1)).slot_name, "L1-1A1-2")
        self.assertEqual(next_cell(grid, at(grid, 1, 3)).slot_name, "L1-1A2-1")

    def test_follows_cell_ids_on_a_reversed_shelf(self) -> None:
        grid = build_grid("1", "1", "A", [3, 2], revert_location_id=True)
        self.assertEqual(next_cell(grid, at(grid, 1, 2)).slot_name, "L1-1A1-3")
        self.assertEqual(next_cell(grid, at(grid, 1, 3)).slot_name, "L1-1A2-1")

    def test_starts_at_row_one_and_stops_after_the_top_row(self) -> None:
        grid = build_grid("1", "1", "A", [3, 2])
        self.assertEqual(next_cell(grid, None).slot_name, "L1-1A1-1")
        self.assertIsNone(next_cell(grid, at(grid, 2, 2)))

    def test_skips_rows_without_cells(self) -> None:
        grid = build_grid("1", "1", "A", [1, 0, 2])
        self.assertEqual(next_cell(grid, at(grid, 1, 1)).slot_name, "L1-1A3-1")


class AssignTabRightClickTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        db_path = Path(self.temp_dir.name) / "warehouse.db"
        WarehouseDatabase(db_path).commit_shelf("1", "A", [3, 2], {}, set(), side="1")
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = WarehouseMapperApp(self.root, database_path=db_path)
        self.app.notebook.select(self.app.assignments)
        self.view = self.app.assignments
        self.view.floor_var.set("1")
        self.view.side_var.set("1")
        self.view.shelf_var.set("A")
        self.view.hand_view.set("shelf")
        self.view._show_hand_view()

    def load(self, row: int, cell: int) -> None:
        self.view.row_var.set(str(row))
        self.view.cell_var.set(str(cell))
        self.app.load_assignment_address()

    def right_click(self) -> None:
        # Tk drops synthetic mouse events on a withdrawn window, so check the
        # binding and call its handler directly.
        self.assertIn("_select_next_shelf_cell", self.view.shelf_grid.canvas.bind("<Button-3>"))
        self.assertEqual(self.view._select_next_shelf_cell(), "break")

    def test_right_click_loads_the_next_cell_and_moves_up_at_the_row_end(self) -> None:
        self.load(1, 2)
        self.right_click()
        self.assertEqual(self.app.selected_address.slot_name, "L1-1A1-3")
        self.assertEqual(self.view.shelf_grid.selected, "L1-1A1-3")
        self.right_click()
        self.assertEqual(self.app.selected_address.slot_name, "L1-1A2-1")
        self.assertEqual((self.view.row_var.get(), self.view.cell_var.get()), ("2", "1"))

    def test_right_click_with_no_selection_loads_row_one_cell_one(self) -> None:
        self.right_click()
        self.assertEqual(self.app.selected_address.slot_name, "L1-1A1-1")

    def test_right_click_on_the_last_cell_stays_and_says_so(self) -> None:
        self.load(2, 2)
        self.right_click()
        self.assertEqual(self.app.selected_address.slot_name, "L1-1A2-2")
        self.assertIn("last cell", self.view.address_status_text.get())


if __name__ == "__main__":
    unittest.main()

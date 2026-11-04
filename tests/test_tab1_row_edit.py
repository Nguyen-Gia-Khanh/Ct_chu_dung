"""Tab 1: insert a row at the blue bar, remove any row with its ✕, and see ghost cells
as a red warning line instead of a popup."""

from __future__ import annotations

import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from mapper.persistence.database import Placement, WarehouseDatabase
from tests.support import WorkspaceTestCase
from ui.desktop.app import WarehouseMapperApp
from ui.desktop.designer import ShelfDesigner, gap_at

TIME = "2026-11-04T08:00:00+07:00"


def name(row: int, cell: int) -> str:
    return f"L1-1A{row}-{cell}"


class GapAtTests(unittest.TestCase):
    def test_pointer_picks_the_nearest_gap_between_row_middles(self) -> None:
        middles = [10, 30, 50]  # Row 3, Row 2, Row 1 from the top of the screen
        self.assertEqual([gap_at(middles, y) for y in (0, 20, 40, 60)], [3, 2, 1, 0])


class DesignerTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.rows_changed = Mock()
        self.designer = ShelfDesigner(self.root, lambda: None, self.rows_changed)
        self.designer.pack()
        self.designer.prepare_row_inputs([6, 6, 10], origins=[1, 2, 3], notify=False)

    def layout(self):
        return self.designer.validated_layout()[3]

    def labels(self):
        return self.designer.row_labels()

    def test_saved_rows_show_highest_first_with_the_bar_on_top(self) -> None:
        self.assertEqual(self.labels(), ["Row 3", "Row 2", "Row 1 — ground"])
        self.assertEqual(self.designer.insert_gap, 3)

    def test_insert_row_at_the_bar_bumps_the_rows_above(self) -> None:
        self.designer.set_insert_gap(2)
        self.designer.insert_row()
        self.assertEqual(self.layout(), [6, 6, 4, 10])
        self.assertEqual(self.designer.row_origins, [1, 2, None, 3])
        self.assertEqual(self.labels(), ["Row 4 (was 3)", "Row 3 (new)", "Row 2", "Row 1 — ground"])
        self.assertEqual(self.designer.insert_gap, 3)  # the bar stays just above the new row
        self.rows_changed.assert_called_once()

    def test_insert_below_the_ground_row(self) -> None:
        self.designer.set_insert_gap(0)
        self.designer.insert_row()
        self.assertEqual(self.layout(), [4, 6, 6, 10])
        self.assertEqual(self.labels()[-1], "Row 1 (new) — ground")

    def test_remove_any_row_drops_the_rows_above(self) -> None:
        self.designer.remove_row(2)
        self.assertEqual(self.layout(), [6, 10])
        self.assertEqual(self.designer.row_origins, [1, 3])
        self.assertEqual(self.labels(), ["Row 2 (was 3)", "Row 1 — ground"])
        self.assertEqual(self.designer.insert_gap, 2)

    def test_the_last_row_cannot_be_removed(self) -> None:
        self.designer.prepare_row_inputs([5], origins=[1], notify=False)
        self.designer.remove_row(1)
        self.assertEqual(self.layout(), [5])

    def test_row_count_box_adds_and_removes_at_the_top(self) -> None:
        self.designer.row_count_var.set("4")
        self.designer.prepare_row_inputs()
        self.assertEqual((self.layout(), self.designer.row_origins), ([6, 6, 10, 4], [1, 2, 3, None]))
        self.assertEqual(self.designer.insert_gap, 4)
        self.designer.row_count_var.set("2")
        self.designer.prepare_row_inputs()
        self.assertEqual((self.layout(), self.designer.row_origins), ([6, 6], [1, 2]))

    def test_new_shelf_rows_have_no_history_labels(self) -> None:
        self.designer.prepare_row_inputs([4, 4], notify=False)
        self.designer.insert_row()
        self.assertEqual(self.labels(), ["Row 3", "Row 2", "Row 1 — ground"])

    def test_ghost_warning_shows_and_hides(self) -> None:
        self.designer.set_ghost_warning("⚠ Ghost cells")
        self.assertEqual(self.designer.ghost_warning.winfo_manager(), "pack")
        self.designer.set_ghost_warning("")
        self.assertEqual(self.designer.ghost_warning.winfo_manager(), "")

    def test_typed_cell_counts_are_read_without_popups(self) -> None:
        self.designer.row_inputs[0].set("x")
        with patch("ui.desktop.designer.messagebox.showerror") as popup:
            self.assertIsNone(self.designer.typed_layout())
        popup.assert_not_called()
        self.designer.row_inputs[0].set("3")
        self.assertEqual(self.designer.typed_layout(), [3, 6, 10])


class Tab1AppTests(WorkspaceTestCase):
    def setUp(self) -> None:
        super().setUp()
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.path = self.folder / "warehouse.db"
        self.db = WarehouseDatabase(self.path)
        self.db.import_products({"P1": "Bolts", "P2": "Nuts"})
        for target in ("showerror", "showinfo"):
            patcher = patch(f"ui.desktop.shelf_actions.messagebox.{target}")
            setattr(self, target, patcher.start())
            self.addCleanup(patcher.stop)

    def open_shelf(self, layout, placements) -> WarehouseMapperApp:
        self.db.commit_shelf("1", "A", layout, {pid: Placement(name(*cell), 5, TIME)
                                                for pid, cell in placements.items()}, set(), side="1")
        app = WarehouseMapperApp(self.root, database_path=self.path)
        app.refresh_shelf_selector()
        app.shelf_selector.set("Floor 1 — Side 1 — Shelf A")
        app.load_selected_shelf()
        return app

    def warning(self, app) -> str:
        return app.designer.ghost_warning_var.get()

    def test_lowering_an_occupied_row_shows_a_red_line_and_commits_a_ghost(self) -> None:
        app = self.open_shelf([3], {"P1": (1, 3)})
        self.assertEqual(self.warning(app), "")
        app.designer.row_inputs[0].set("2")
        app.refresh_ghost_warning()
        self.assertIn("Row 1 cell 3", self.warning(app))
        self.assertTrue(app.build_shelf_preview(switch_tab=False))
        self.assertTrue(app.shelf_browser.shelf_grid.cells[name(1, 3)].ghost)
        self.assertTrue(app.commit_changes())
        self.showerror.assert_not_called()
        self.assertEqual(self.db.get_shelf(app.current_shelf_id)[3], [2])
        self.assertEqual(self.db.get_product_locations("P1"), [name(1, 3)])
        self.assertIn("Ghost cells kept: 1", self.showinfo.call_args.args[1])
        self.assertIn("Row 1 cell 3", self.warning(app))  # still there until the products move

    def test_removing_a_middle_row_lifts_its_products_into_a_ghost_row(self) -> None:
        app = self.open_shelf([2, 2, 2], {"P1": (2, 1), "P2": (3, 1)})
        app.designer.remove_row(2)
        self.assertIn("Row 3 (was Row 2) cell 1", self.warning(app))
        self.assertTrue(app.has_pending_changes())
        self.assertTrue(app.commit_changes())
        self.assertEqual(self.db.get_product_locations("P2"), [name(2, 1)])
        self.assertEqual(self.db.get_product_locations("P1"), [name(3, 1)])
        self.assertEqual(app.designer.row_origins, [1, 2])
        self.assertFalse(app.has_pending_changes())

    def test_inserting_a_middle_row_bumps_products_up(self) -> None:
        app = self.open_shelf([2, 2], {"P1": (2, 2)})
        app.designer.set_insert_gap(1)
        app.designer.insert_row()
        self.assertTrue(app.has_pending_changes())
        self.assertEqual(app.committed_locations["P1"], name(3, 2))  # product list shows the new ID
        self.assertTrue(app.commit_changes())
        self.assertEqual(self.db.get_shelf(app.current_shelf_id)[3], [2, 4, 2])
        self.assertEqual(self.db.get_product_locations("P1"), [name(3, 2)])
        self.assertEqual(app.designer.row_labels(), ["Row 3", "Row 2", "Row 1 — ground"])

    def test_loading_a_shelf_with_ghosts_shows_the_warning(self) -> None:
        shelf_id = self.db.commit_shelf("1", "A", [3], {"P1": Placement(name(1, 3), 5, TIME)}, set(), side="1")
        self.db.commit_shelf("1", "A", [2], {}, set(), side="1", shelf_id=shelf_id)
        app = WarehouseMapperApp(self.root, database_path=self.path)
        app.refresh_shelf_selector()
        app.shelf_selector.set("Floor 1 — Side 1 — Shelf A")
        app.load_selected_shelf()
        self.assertIn("Row 1 cell 3", self.warning(app))
        self.assertEqual(app.designer.validated_layout()[3], [2])

    def test_new_shelf_clears_the_warning(self) -> None:
        app = self.open_shelf([3], {"P1": (1, 3)})
        app.designer.set_ghost_warning("⚠ something")
        app.new_shelf()
        self.assertEqual(self.warning(app), "")


if __name__ == "__main__":
    unittest.main()

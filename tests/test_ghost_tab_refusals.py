"""Tabs 2, 5 and 6 refuse to put products into a ghost cell: error sound and a status
message, no popup, nothing moved. Products can still leave a ghost cell."""

from __future__ import annotations

import tkinter as tk
from unittest.mock import Mock, patch

from mapper.persistence.database import Placement, WarehouseDatabase
from tests.support import WorkspaceTestCase
from ui.desktop.app import WarehouseMapperApp
from ui.desktop.cell_transfer_view import CellTransferView

TIME = "2026-11-04T08:00:00+07:00"


def name(row: int, cell: int) -> str:
    return f"L1-1A{row}-{cell}"


class TkWorkspaceTestCase(WorkspaceTestCase):
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

    def mute(self, target: str) -> Mock:
        patcher = patch(target)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock


class Tab2And6GhostTests(TkWorkspaceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.db.import_products({"Q1": "Queue part", "G1": "Ghost part"})
        self.db.import_catalog_products({"C1": ("Catalog part", "")})
        shelf_id = self.db.commit_shelf("1", "A", [3], {"G1": Placement(name(1, 3), 2, TIME)}, set(), side="1")
        self.db.commit_shelf("1", "A", [2], {}, set(), side="1", shelf_id=shelf_id)  # cell 1-3 becomes a ghost
        self.app = WarehouseMapperApp(self.root, database_path=self.path)
        self.sound = self.mute("ui.desktop.assignment_actions.play_error_sound")
        self.dialog = self.mute("ui.desktop.assignment_actions.StockQuantityDialog")
        self.popup = self.mute("ui.desktop.assignment_actions.messagebox.showerror")
        self.app.notebook.select(self.app.assignments)
        view = self.app.assignments
        for variable, value in ((view.floor_var, "1"), (view.side_var, "1"), (view.shelf_var, "A"),
                                (view.row_var, "1"), (view.cell_var, "3")):
            variable.set(value)
        self.app.load_assignment_address()

    def assert_refused(self) -> None:
        self.sound.assert_called_once()
        self.dialog.assert_not_called()
        self.popup.assert_not_called()
        self.assertIn("ghost cell", self.app.status_text.get())
        self.assertEqual(self.db.get_product_locations("G1"), [name(1, 3)])
        for pid in ("Q1", "C1"):
            self.assertEqual(self.db.get_product_locations(pid), [])

    def search(self, text: str) -> None:
        self.app.assignments.search_var.set(text)
        self.app.refresh_product_lists()

    def test_loading_a_ghost_cell_says_to_move_its_products_out(self) -> None:
        self.assertTrue(self.app.selected_address.ghost)
        self.assertIn("Ghost cell", self.app.status_text.get())
        self.sound.assert_not_called()

    def test_queue_button_refuses_at_the_first_click(self) -> None:
        self.search("Q1")
        self.app.assign_queue_selection_to_address(to_shelf=True)
        self.assert_refused()
        self.assertEqual(self.app.queue_shift_clicks, 0)

    def test_queue_shift_click_refuses_before_the_stock_dialog(self) -> None:
        self.search("Q1")
        self.app.assignments.queue_tree.selection_set("product::Q1")
        self.app.assign_queue_selection_to_address(to_shelf=False)
        self.assert_refused()

    def test_catalog_button_refuses_both_ways(self) -> None:
        self.search("C1")
        self.app.assignments.catalog_tree.selection_set("catalog::C1")
        for to_shelf in (True, False):
            with self.subTest(to_shelf=to_shelf):
                self.sound.reset_mock()
                self.app.assign_catalog_selection_to_address(to_shelf=to_shelf)
                self.assert_refused()

    def test_on_hand_button_refuses(self) -> None:
        self.db.add_to_on_hand({"Q1": 4}, TIME)
        self.app.reload_database_state()
        self.app.refresh_on_hand_queue()
        self.app.assignments.on_hand_tree.selection_set("hand::Q1")
        self.app.assign_on_hand_to_address()
        self.assert_refused()

    def test_products_can_still_return_to_on_hand(self) -> None:
        with patch("ui.desktop.assignment_actions.messagebox.askyesno", return_value=True):
            self.app.move_address_to_on_hand()
        self.assertEqual(self.db.get_product_locations("G1"), [])
        self.sound.assert_not_called()

    def test_tab6_refuses_an_exception_in_a_ghost_cell(self) -> None:
        sound = self.mute("ui.desktop.exceptions_view.play_error_sound")
        popup = self.mute("ui.desktop.exceptions_view.messagebox.showerror")
        view = self.app.exceptions_view
        view.row_var.set("1")
        view.cell_var.set("3")
        view.load_address()
        view.product_id_var.set("Q1")
        view.assign_exception()
        sound.assert_called_once()
        popup.assert_not_called()
        self.assertIn("ghost cell", self.app.status_text.get())
        self.assertEqual(self.db.get_product_locations("Q1"), [])


class Tab5GhostTests(TkWorkspaceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.db.import_products({"P1": "Bolts", "P2": "Nuts", "P3": "Washers"})
        shelf_id = self.db.commit_shelf("1", "A", [3, 3], {
            "P1": Placement(name(1, 3), 5, TIME), "P2": Placement(name(2, 1), 6, TIME),
            "P3": Placement(name(1, 2), 7, TIME)}, set(), side="1")
        self.db.commit_shelf("1", "A", [2, 3], {}, set(), side="1", shelf_id=shelf_id)  # 1-3 (P1) is a ghost
        self.on_changed = Mock()
        self.view = CellTransferView(self.root, self.db, self.on_changed, lambda: True)
        self.view.refresh()
        self.view.left.load_shelf(shelf_id)
        self.view.right.load_shelf(shelf_id)
        self.sound = self.mute("ui.desktop.cell_transfer_view.play_error_sound")
        self.confirm = self.mute("ui.desktop.cell_transfer_view.messagebox.askyesno")
        self.confirm.return_value = True
        self.popup = self.mute("ui.desktop.cell_transfer_view.messagebox.showerror")

    def locations(self):
        return {pid: placement.slot_name for pid, placement in self.db.get_placement_details().items()}

    def assert_refused(self) -> None:
        self.sound.assert_called_once()
        self.confirm.assert_not_called()
        self.popup.assert_not_called()
        self.assertIn("ghost cell", self.view.status_text.get())
        self.assertEqual(self.locations(), {"P1": name(1, 3), "P2": name(2, 1), "P3": name(1, 2)})
        self.on_changed.assert_not_called()

    def test_the_ghost_is_drawn_red_at_the_end_of_its_row(self) -> None:
        self.assertTrue(self.view.left.shelf_grid.cells[name(1, 3)].ghost)

    def test_switch_into_a_full_ghost_is_refused(self) -> None:
        self.view.left._select_coordinates(2, 1)
        self.view.right._select_coordinates(1, 3)
        self.view.swap_cells()
        self.assert_refused()

    def test_a_full_ghost_switches_with_an_empty_cell(self) -> None:
        self.view.left._select_coordinates(1, 3)
        self.view.right._select_coordinates(2, 3)
        self.view.swap_cells()
        self.assertEqual(self.locations()["P1"], name(2, 3))
        self.sound.assert_not_called()

    def test_combine_into_a_ghost_is_refused(self) -> None:
        self.view.left._select_coordinates(2, 1)
        self.view.right._select_coordinates(1, 3)
        self.view.combine_cells(self.view.left, self.view.right)
        self.assert_refused()

    def test_a_block_cannot_move_into_a_ghost(self) -> None:
        self.view.left.shelf_grid.set_marked({name(1, 2)})
        self.view.shift_block(self.view.left, 0, 1)
        self.assert_refused()

    def test_a_ghost_block_moves_up(self) -> None:
        self.view.left.shelf_grid.set_marked({name(1, 3)})
        self.view.shift_block(self.view.left, 1, 0)
        self.assertEqual(self.locations()["P1"], name(2, 3))

    def test_block_switch_into_a_ghost_is_refused(self) -> None:
        self.view.left.shelf_grid.set_marked({name(2, 1)})
        self.view.right.shelf_grid.set_marked({name(1, 3)})
        self.view.swap_blocks()
        self.assert_refused()

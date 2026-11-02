"""Tab 5 blocks: drag a box over cells, move them up/down/left/right, or switch two same-size blocks."""

from __future__ import annotations

from contextlib import closing
import sqlite3
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mapper.persistence.database import Placement, WarehouseDatabase
from mapper.services.shelf_grid import build_grid, cells_in_id_order, plan_block_shift
from tests.support import WorkspaceTestCase
from ui.desktop.cell_transfer_view import CellTransferView
from ui.desktop.widgets import ShelfGridCanvas

TIME = "2026-11-02T08:00:00+07:00"


def name(row: int, cell: int) -> str:
    return f"L1-1A{row}-{cell}"


class PlanBlockShiftTests(unittest.TestCase):
    def grid(self, layout, filled, *, reverse=False):
        return build_grid("1", "1", "A", layout, filled, revert_location_id=reverse)

    def test_rows_move_up_onto_the_cells_they_leave(self) -> None:
        grid = self.grid([2, 2, 2, 2], [name(2, 1), name(2, 2), name(3, 1)])
        plan = plan_block_shift(grid, {name(r, c) for r in (2, 3) for c in (1, 2)}, 1, 0)
        self.assertEqual(plan.moves, {name(2, 1): name(3, 1), name(2, 2): name(3, 2), name(3, 1): name(4, 1)})
        self.assertEqual(set(plan.selection), {name(r, c) for r in (3, 4) for c in (1, 2)})
        self.assertEqual((plan.missing, plan.blocked), ((), ()))

    def test_down_and_right_follow_the_drawing(self) -> None:
        grid = self.grid([3, 3], [name(2, 1)])
        self.assertEqual(plan_block_shift(grid, {name(2, 1)}, -1, 0).moves, {name(2, 1): name(1, 1)})
        self.assertEqual(plan_block_shift(grid, {name(2, 1)}, 0, 2).moves, {name(2, 1): name(2, 3)})

    def test_left_and_right_use_screen_order_on_a_reversed_shelf(self) -> None:
        # Reversed IDs draw cell 3 on the left, so moving right lowers the cell number.
        grid = self.grid([3], [name(1, 3)], reverse=True)
        self.assertEqual(plan_block_shift(grid, {name(1, 3)}, 0, 1).moves, {name(1, 3): name(1, 2)})

    def test_occupied_cells_past_the_shelf_edge_are_missing(self) -> None:
        grid = self.grid([2, 2], [name(2, 1)])
        plan = plan_block_shift(grid, {name(2, 1), name(2, 2)}, 1, 0)
        self.assertEqual(plan.missing, (name(2, 1),))

    def test_empty_cells_past_the_edge_are_ignored(self) -> None:
        # Row 1 is wider than Row 2: an empty third cell has nothing to carry up.
        grid = self.grid([3, 2], [name(1, 1)])
        plan = plan_block_shift(grid, {name(1, 1), name(1, 2), name(1, 3)}, 1, 0)
        self.assertEqual((plan.moves, plan.missing), ({name(1, 1): name(2, 1)}, ()))
        self.assertEqual(set(plan.selection), {name(2, 1), name(2, 2)})

    def test_occupied_target_outside_the_block_is_blocked(self) -> None:
        grid = self.grid([2, 2], [name(1, 1), name(2, 1)])
        self.assertEqual(plan_block_shift(grid, {name(1, 1)}, 1, 0).blocked, (name(2, 1),))


class ShiftSlotContentsTests(WorkspaceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.db = WarehouseDatabase(self.folder / "warehouse.db")
        self.db.import_products({"P1": "Bolts", "P2": "Nuts", "P3": "Washers", "E1": "Extra"})
        self.db.commit_shelf("1", "A", [1, 1, 1, 1], {
            "P1": Placement(name(1, 1), 5, TIME),
            "P2": Placement(name(2, 1), 6, TIME),
            "P3": Placement(name(3, 1), 7, TIME),
        }, set(), side="1")
        self.slot = {row: self.db.get_slot_by_name(name(row, 1)).slot_id for row in range(1, 5)}

    def snapshot(self):
        with closing(self.db.connect()) as connection:
            return {table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                    for table in ("placements", "exception_placements", "wait_to_update_csv")}

    def test_chained_rows_move_together_with_their_extra_locations(self) -> None:
        self.db.add_to_on_hand({"E1": 3}, TIME)
        self.db.assign_on_hand_to_slot(self.slot[1], TIME, ["E1"])
        self.db.assign_exception("E1", self.slot[2], TIME, 3)
        moved = self.db.shift_slot_contents({self.slot[2]: self.slot[3], self.slot[3]: self.slot[4]})
        self.assertEqual(moved, 3)
        placements = self.db.get_placement_details()
        self.assertEqual((placements["P1"].slot_name, placements["P2"].slot_name, placements["P3"].slot_name),
                         (name(1, 1), name(3, 1), name(4, 1)))
        self.assertEqual(set(self.db.find_product_locations("E1")[1]), {name(1, 1), name(3, 1)})
        self.assertEqual(self.db.get_slot_contents(self.slot[2]), [])

    def test_occupied_target_outside_the_moves_changes_nothing(self) -> None:
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, name(2, 1)):
            self.db.shift_slot_contents({self.slot[1]: self.slot[2]})
        self.assertEqual(self.snapshot(), before)

    def test_two_cells_into_one_or_missing_cells_are_rejected(self) -> None:
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.db.shift_slot_contents({self.slot[2]: self.slot[4], self.slot[3]: self.slot[4]})
        with self.assertRaises(KeyError):
            self.db.shift_slot_contents({self.slot[3]: 999_999})
        with self.assertRaises(ValueError):
            self.db.shift_slot_contents({})
        self.assertEqual(self.snapshot(), before)

    def test_failed_write_rolls_back_every_move(self) -> None:
        with closing(self.db.connect()) as connection, connection:
            connection.execute("""CREATE TRIGGER reject_move BEFORE UPDATE ON placements
                                  WHEN NEW.product_id = 'P3' BEGIN SELECT RAISE(ABORT, 'move failed'); END""")
        before = self.snapshot()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "move failed"):
            self.db.shift_slot_contents({self.slot[2]: self.slot[3], self.slot[3]: self.slot[4]})
        self.assertEqual(self.snapshot(), before)


class TkTestCase(unittest.TestCase):
    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)


class GridDragSelectTests(TkTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.picked = []
        self.grid_widget = ShelfGridCanvas(self.root, on_select=self.picked.append, drag_select=True)
        self.grid_widget.pack()
        self.grid_widget.show(build_grid("1", "1", "A", [2, 2], [name(1, 1)]))
        self.root.update_idletasks()
        self.canvas = self.grid_widget.canvas

    def centre(self, slot_name):
        x1, y1, x2, y2 = self.canvas.coords(self.grid_widget._items[slot_name][0])
        return int((x1 + x2) / 2), int((y1 + y2) / 2)

    def drag(self, start, end, *, cancel=False):
        self.grid_widget._press(SimpleNamespace(x=start[0], y=start[1]))
        self.grid_widget._motion(SimpleNamespace(x=end[0], y=end[1]))
        if cancel:
            self.grid_widget._cancel_drag()
        self.grid_widget._release(SimpleNamespace(x=end[0], y=end[1]))

    def test_dragging_a_box_marks_every_cell_it_touches(self) -> None:
        self.drag(self.centre(name(2, 1)), self.centre(name(1, 2)))
        self.assertEqual(self.grid_widget.marked, {name(r, c) for r in (1, 2) for c in (1, 2)})
        self.assertEqual(self.picked, [])

    def test_dragging_from_a_marked_cell_unmarks(self) -> None:
        self.grid_widget.set_marked({name(1, 1), name(1, 2), name(2, 1)})
        self.drag(self.centre(name(1, 1)), self.centre(name(1, 2)))
        self.assertEqual(self.grid_widget.marked, {name(2, 1)})

    def test_a_plain_click_still_picks_one_cell(self) -> None:
        point = self.centre(name(2, 2))
        self.drag(point, (point[0] + 1, point[1]))
        self.assertEqual([cell.slot_name for cell in self.picked], [name(2, 2)])
        self.assertEqual(self.grid_widget.marked, set())

    def test_escape_cancels_the_drag(self) -> None:
        self.drag(self.centre(name(2, 1)), self.centre(name(1, 2)), cancel=True)
        self.assertEqual(self.grid_widget.marked, set())

    def test_another_shelf_clears_the_block(self) -> None:
        self.grid_widget.set_marked({name(1, 1)})
        self.grid_widget.show(build_grid("1", "1", "B", [2]))
        self.assertEqual(self.grid_widget.marked, set())


class ShiftBlockViewTests(WorkspaceTestCase):
    def setUp(self) -> None:
        super().setUp()
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.db = WarehouseDatabase(self.folder / "warehouse.db")
        self.db.import_products({"P1": "Bolts", "P2": "Nuts"})
        self.db.commit_shelf("1", "A", [2, 2, 2], {
            "P1": Placement(name(1, 1), 5, TIME), "P2": Placement(name(2, 2), 6, TIME),
        }, set(), side="1")
        self.on_changed = Mock()
        self.view = CellTransferView(self.root, self.db, self.on_changed, lambda: True)
        self.view.refresh()
        self.pane = self.view.left

    def test_up_moves_the_block_and_queues_web_updates(self) -> None:
        self.pane.shelf_grid.set_marked({name(r, c) for r in (1, 2) for c in (1, 2)})
        with patch("ui.desktop.cell_transfer_view.messagebox.askyesno", return_value=True):
            self.view.shift_block(self.pane, 1, 0)
        placements = self.db.get_placement_details()
        self.assertEqual((placements["P1"].slot_name, placements["P2"].slot_name), (name(2, 1), name(3, 2)))
        self.assertEqual({(u.product_id, u.location_id) for u in self.view.last_changed_updates},
                         {("P1", name(2, 1)), ("P2", name(3, 2))})
        self.assertEqual(self.pane.shelf_grid.marked, {name(r, c) for r in (2, 3) for c in (1, 2)})
        self.on_changed.assert_called_once()

    def test_pressing_twice_moves_the_block_again(self) -> None:
        # The panes only patch counts after a move, so the next press must read the shelf fresh.
        self.view.on_changed = lambda _m, _u, slot_names: [self.pane.refresh_cell(n) for n in slot_names]
        self.pane.shelf_grid.set_marked({name(1, 1)})
        with patch("ui.desktop.cell_transfer_view.messagebox.askyesno", return_value=True):
            self.view.shift_block(self.pane, 1, 0)
            self.view.shift_block(self.pane, 1, 0)
        self.assertEqual(self.db.get_placement_details()["P1"].slot_name, name(3, 1))

    def test_steps_box_moves_further(self) -> None:
        self.pane.shelf_grid.set_marked({name(1, 1)})
        self.pane.shift_steps.set("2")
        with patch("ui.desktop.cell_transfer_view.messagebox.askyesno", return_value=True):
            self.pane.shift_buttons["up"].invoke()
        self.assertEqual(self.db.get_placement_details()["P1"].slot_name, name(3, 1))

    def test_past_the_top_row_asks_for_a_new_row_and_changes_nothing(self) -> None:
        self.pane.shelf_grid.set_marked({name(2, 2)})
        with patch("ui.desktop.cell_transfer_view.messagebox.showerror") as error, \
                patch("ui.desktop.cell_transfer_view.messagebox.askyesno") as confirm:
            self.view.shift_block(self.pane, 2, 0)
        self.assertIn("Tab 1", error.call_args.args[1])
        confirm.assert_not_called()
        self.assertEqual(self.db.get_placement_details()["P2"].slot_name, name(2, 2))

    def test_occupied_target_is_named_and_nothing_moves(self) -> None:
        self.pane.shelf_grid.set_marked({name(1, 1)})
        with patch("ui.desktop.cell_transfer_view.messagebox.showerror") as error:
            self.view.shift_block(self.pane, 1, 1)
        self.assertIn(name(2, 2), error.call_args.args[1])
        self.assertEqual(self.db.get_placement_details()["P1"].slot_name, name(1, 1))

    def test_declined_confirm_and_blocked_changes_do_nothing(self) -> None:
        self.pane.shelf_grid.set_marked({name(1, 1)})
        with patch("ui.desktop.cell_transfer_view.messagebox.askyesno", return_value=False):
            self.view.shift_block(self.pane, 1, 0)
        self.view.can_change = lambda: False
        self.view.shift_block(self.pane, 1, 0)
        self.assertEqual(self.db.get_placement_details()["P1"].slot_name, name(1, 1))
        self.on_changed.assert_not_called()


def b_name(row: int, cell: int) -> str:
    return f"L1-2B{row}-{cell}"


class CellsInIdOrderTests(unittest.TestCase):
    def test_row_one_first_then_cell_one_first_even_when_reversed(self) -> None:
        grid = build_grid("1", "1", "A", [3, 3], revert_location_id=True)
        marked = {name(2, 1), name(1, 3), name(1, 1), name(2, 2)}
        self.assertEqual([cell.slot_name for cell in cells_in_id_order(grid, marked)],
                         [name(1, 1), name(1, 3), name(2, 1), name(2, 2)])


class BlockSwitchViewTests(WorkspaceTestCase):
    """Two same-size blocks trade contents pair by pair in location-ID order."""

    def setUp(self) -> None:
        super().setUp()
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.db = WarehouseDatabase(self.folder / "warehouse.db")
        self.db.import_products({"P1": "Bolts", "P2": "Nuts", "P3": "Washers", "E1": "Extra"})
        self.db.commit_shelf("1", "A", [4], {
            "P1": Placement(name(1, 1), 5, TIME), "P2": Placement(name(1, 3), 6, TIME),
        }, set(), side="1")
        self.db.commit_shelf("1", "B", [2, 2], {"P3": Placement(b_name(2, 2), 7, TIME)}, set(), side="2")
        self.on_changed = Mock()
        self.view = CellTransferView(self.root, self.db, self.on_changed, lambda: True)
        self.view.refresh()
        self.view.left.load_shelf(self.db.get_slot_by_name(name(1, 1)).shelf_id)
        self.view.right.load_shelf(self.db.get_slot_by_name(b_name(1, 1)).shelf_id)

    def locations(self):
        details = self.db.get_placement_details()
        return {pid: details[pid].slot_name for pid in ("P1", "P2", "P3")}

    def test_blocks_of_different_shapes_switch_in_id_order(self) -> None:
        # One row of 4 on the left, two rows of 2 on the right.
        self.db.add_to_on_hand({"E1": 1}, TIME)
        self.db.assign_on_hand_to_slot(self.db.get_slot_by_name(b_name(1, 1)).slot_id, TIME, ["E1"])
        self.db.assign_exception("E1", self.db.get_slot_by_name(name(1, 4)).slot_id, TIME, 1)
        self.view.left.shelf_grid.set_marked({name(1, c) for c in range(1, 5)})
        self.view.right.shelf_grid.set_marked({b_name(r, c) for r in (1, 2) for c in (1, 2)})
        with patch("ui.desktop.cell_transfer_view.messagebox.askyesno", return_value=True) as confirm:
            self.view.swap_cells()
        self.assertIn(f"{name(1, 1)} ↔ {b_name(1, 1)}", confirm.call_args.args[1])
        self.assertEqual(self.locations(), {"P1": b_name(1, 1), "P2": b_name(2, 1), "P3": name(1, 4)})
        # E1's main cell 2B1-1 pairs with 1A1-1; its extra cell 1A1-4 pairs with 2B2-2.
        self.assertEqual(set(self.db.find_product_locations("E1")[1]), {name(1, 1), b_name(2, 2)})
        self.assertEqual({u.product_id for u in self.view.last_changed_updates}, {"P1", "P2", "P3", "E1"})
        self.on_changed.assert_called_once()

    def test_different_cell_counts_change_nothing(self) -> None:
        self.view.left.shelf_grid.set_marked({name(1, 1), name(1, 2)})
        self.view.right.shelf_grid.set_marked({b_name(1, 1)})
        with patch("ui.desktop.cell_transfer_view.messagebox.showerror") as error:
            self.view.swap_cells()
        self.assertIn("Left block: 2 cells", error.call_args.args[1])
        self.assertIn("Right block: 1 cell", error.call_args.args[1])
        self.assertEqual(self.locations(), {"P1": name(1, 1), "P2": name(1, 3), "P3": b_name(2, 2)})

    def test_a_block_on_one_side_only_changes_nothing(self) -> None:
        self.view.left.shelf_grid.set_marked({name(1, 1)})
        with patch("ui.desktop.cell_transfer_view.messagebox.showinfo") as info:
            self.view.swap_cells()
        self.assertIn("Clear block", info.call_args.args[1])
        self.assertEqual(self.locations()["P1"], name(1, 1))

    def test_overlapping_blocks_change_nothing(self) -> None:
        self.view.right.load_shelf(self.view.left.current_shelf_id)
        self.view.left.shelf_grid.set_marked({name(1, 1), name(1, 2)})
        self.view.right.shelf_grid.set_marked({name(1, 2), name(1, 3)})
        with patch("ui.desktop.cell_transfer_view.messagebox.showerror") as error:
            self.view.swap_cells()
        self.assertIn(name(1, 2), error.call_args.args[1])
        self.assertEqual(self.locations()["P1"], name(1, 1))

    def test_without_blocks_switch_still_trades_the_two_clicked_cells(self) -> None:
        self.view.left._select_coordinates(1, 1)
        self.view.right._select_coordinates(2, 2)
        with patch("ui.desktop.cell_transfer_view.messagebox.askyesno", return_value=True):
            self.view.swap_cells()
        self.assertEqual(self.locations(), {"P1": b_name(2, 2), "P2": name(1, 3), "P3": name(1, 1)})


if __name__ == "__main__":
    unittest.main()

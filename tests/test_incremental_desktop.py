"""Cell and row refreshes update what is on screen in place instead of rebuilding it."""

from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from mapper.persistence.database import Placement
from mapper.services.shelf_grid import EMPTY_COLOR, FILLED_COLOR, SELECTED_COLOR, STAGED_COLOR, build_grid
from ui.desktop.state_actions import StateActions
from ui.desktop.widgets import ShelfGridCanvas, sync_tree_rows


class Tree:
    """Just enough of ttk.Treeview to watch which rows are touched."""

    def __init__(self):
        self.order = []
        self.rows = {}
        self.deleted = []

    def get_children(self):
        return tuple(self.order)

    def exists(self, item_id):
        return item_id in self.rows

    def delete(self, *item_ids):
        for item_id in item_ids:
            self.deleted.append(item_id)
            self.order.remove(item_id)
            del self.rows[item_id]

    def insert(self, _parent, _index, *, iid, values, tags):
        self.order.append(iid)
        self.rows[iid] = {"values": tuple(map(str, values)), "tags": tags}

    def item(self, item_id, option=None, **updates):
        if updates:
            self.rows[item_id] = {**self.rows[item_id], **{
                key: tuple(map(str, value)) if key == "values" else value for key, value in updates.items()}}
        return self.rows[item_id][option] if option else self.rows[item_id]

    def set_children(self, _parent, *item_ids):
        self.order = list(item_ids)


class ShelfGridCanvasTests(TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.selected = []
        self.grid = ShelfGridCanvas(self.root, on_select=self.selected.append)

    def test_counts_and_selection_recolor_cells_in_place(self):
        self.grid.show(build_grid("1", "1", "A", [2], []))
        items = dict(self.grid._items)
        self.assertEqual(self.grid.cell_fill("L1-1A1-1"), EMPTY_COLOR)

        self.grid.set_count("L1-1A1-1", 2)
        self.assertEqual(self.grid.cell_fill("L1-1A1-1"), FILLED_COLOR)
        self.assertIn("2 products", self.grid.cell_text("L1-1A1-1"))
        self.grid.set_count("L1-1A1-2", 0, staged=1)
        self.assertEqual(self.grid.cell_fill("L1-1A1-2"), STAGED_COLOR)
        self.grid.select("L1-1A1-1")
        self.assertEqual(self.grid.cell_fill("L1-1A1-1"), SELECTED_COLOR)
        self.assertEqual(self.grid._items, items)

    def test_same_shelf_reuses_drawing_and_new_layout_redraws(self):
        self.grid.show(build_grid("1", "1", "A", [2], []))
        items = dict(self.grid._items)
        self.grid.show(build_grid("1", "1", "A", [2], ["L1-1A1-2"]), selected="L1-1A1-2")
        self.assertEqual(self.grid._items, items)
        self.assertEqual(self.grid.cell_fill("L1-1A1-2"), SELECTED_COLOR)
        self.grid.show(build_grid("1", "1", "A", [3], []))
        self.assertIn("L1-1A1-3", self.grid)
        self.assertIsNone(self.grid.selected)

    def test_clicking_a_cell_reports_it(self):
        self.grid.show(build_grid("1", "1", "A", [1], []))
        rect, _text = self.grid._items["L1-1A1-1"]
        self.grid.canvas.find_withtag = lambda tag: (rect,) if tag == "current" else ()
        self.grid._clicked(None)
        self.assertEqual([cell.slot_name for cell in self.selected], ["L1-1A1-1"])

    def test_message_clears_the_grid(self):
        self.grid.show(build_grid("1", "1", "A", [1], []))
        self.grid.show_message("Choose a shelf")
        self.assertNotIn("L1-1A1-1", self.grid)
        self.assertIsNone(self.grid.key)


class IncrementalDesktopTests(TestCase):
    def test_row_reconciliation_keeps_unaffected_item(self):
        tree = Tree()
        sync_tree_rows(tree, [
            ("hand::P1", ("P1", "Bolts", 2), ()),
            ("hand::P2", ("P2", "Washers", 1), ()),
        ])
        unaffected = tree.rows["hand::P2"]
        sync_tree_rows(tree, [
            ("hand::P2", ("P2", "Washers", 1), ()),
            ("hand::P1", ("P1", "Bolts", 3), ()),
        ])
        self.assertIs(tree.rows["hand::P2"], unaffected)
        self.assertEqual(tree.deleted, [])
        self.assertEqual(tree.rows["hand::P1"]["values"][2], "3")
        self.assertEqual(tree.get_children(), ("hand::P2", "hand::P1"))
        sync_tree_rows(tree, [("hand::P1", ("P1", "Bolts", 3), ())])
        self.assertEqual(tree.deleted, ["hand::P2"])

    def test_only_loaded_transfer_cells_are_queried(self):
        app = StateActions()
        left = SimpleNamespace(shelf_grid={"A"}, refresh_cell=Mock())
        right = SimpleNamespace(shelf_grid={"B"}, refresh_cell=Mock())
        app.cell_transfer = SimpleNamespace(left=left, right=right)
        app.notebook = SimpleNamespace(select=lambda: str(app.cell_transfer))
        app.assignments = SimpleNamespace()
        app.primal_view = SimpleNamespace(shelf_grid=set())
        app.shelf_browser = SimpleNamespace(current_shelf_id=None, shelf_grid=set())
        app.database = Mock()
        app.database.get_slot_by_name.side_effect = lambda name: SimpleNamespace(slot_id=name)
        app.database.get_slot_contents.side_effect = lambda slot_id: [(slot_id, "", Placement(slot_id, 1, None))]

        app.refresh_visible_cells(("A", "B", "C"))
        self.assertEqual(app.database.get_slot_by_name.call_count, 2)
        left.refresh_cell.assert_called_once()
        right.refresh_cell.assert_called_once()

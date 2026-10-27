"""Run with python -m unittest tests.test_label_printer_app."""

from types import SimpleNamespace
import tkinter as tk
import unittest

from mapper.persistence.database import WarehouseDatabase
from tests.support import WorkspaceTestCase
from utils.labels.app import LabelPrinterApp


class CellDragSelectionTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        path = self.folder / "warehouse.db"
        WarehouseDatabase(path).save_shelf("1", "A", [3, 3])
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.addCleanup(self.root.destroy)
        self.app = LabelPrinterApp(self.root, path)
        self.root.update()
        self.app.draw_shelf()
        self.slots = {
            (cell.row_number, cell.slot_number): slot_id
            for slot_id, (cell, _) in self.app.cell_boxes.items()
        }

    def point(self, row, cell):
        _, (x1, y1, x2, y2) = self.app.cell_boxes[self.slots[row, cell]]
        return SimpleNamespace(x=int((x1 + x2) / 2), y=int((y1 + y2) / 2))

    def marked(self):
        return {key for key, slot_id in self.slots.items() if slot_id in self.app.marked}

    def drag(self, start, end, *, cancel=False):
        self.app.on_canvas_press(start)
        self.app.on_canvas_drag(SimpleNamespace(x=(start.x + end.x) // 2, y=(start.y + end.y) // 2))
        self.app.on_canvas_drag(end)
        if cancel:
            self.app.cancel_cell_drag()
        self.app.on_canvas_release(end)

    def test_drag_selects_every_cell_the_box_touches(self):
        # Row 2 is drawn above row 1, so this box covers the left two cells of both rows.
        self.drag(self.point(2, 1), self.point(1, 2))
        self.assertEqual(self.marked(), {(2, 1), (2, 2), (1, 1), (1, 2)})
        self.assertIn("Selected 4", self.app.status_text.get())

    def test_drag_from_a_selected_cell_deselects(self):
        self.drag(self.point(2, 1), self.point(1, 2))
        self.drag(self.point(1, 2), self.point(1, 3))
        self.assertEqual(self.marked(), {(2, 1), (2, 2), (1, 1)})

    def test_click_and_tiny_moves_still_toggle_one_cell(self):
        target = self.point(1, 3)
        self.app.on_canvas_press(target)
        self.app.on_canvas_release(target)
        self.assertEqual(self.marked(), {(1, 3)})
        self.drag(target, SimpleNamespace(x=target.x + 2, y=target.y + 1))
        self.assertEqual(self.marked(), set())

    def test_escape_cancels_without_changing_the_selection(self):
        self.drag(self.point(2, 1), self.point(1, 3), cancel=True)
        self.assertEqual(self.marked(), set())
        self.assertIsNone(self.app.drag)


if __name__ == "__main__":
    unittest.main()

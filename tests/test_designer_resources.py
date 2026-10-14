"""Shelf row editor rebuilds must release their old Tk callbacks."""

import tkinter as tk
from unittest import TestCase

from ui.desktop.designer import ShelfDesigner


class ShelfDesignerResourceTests(TestCase):
    def test_rebuilding_rows_does_not_accumulate_tcl_commands(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        try:
            designer = ShelfDesigner(root, lambda: None, lambda _count: True, lambda: None)
            designer.pack()
            initial_count = len(root.tk.call("info", "commands"))
            for _ in range(30):
                designer.prepare_row_inputs(layout=[4, 4, 4], notify=False)
            self.assertEqual(len(root.tk.call("info", "commands")), initial_count)
        finally:
            root.destroy()

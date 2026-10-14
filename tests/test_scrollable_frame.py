"""Repeated shelf redraws must not retain mouse-wheel callbacks."""

import tkinter as tk
from unittest import TestCase

from ui.desktop.widgets import ScrollableFrame


class ScrollableFrameTests(TestCase):
    def test_rebinding_wheel_events_keeps_callback_count_flat(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        try:
            scroll = ScrollableFrame(root, horizontal=True, vertical=True)
            scroll.pack()
            persistent = (scroll, scroll.canvas, scroll.inner)
            original_counts = [len(widget._tclCommands or []) for widget in persistent]

            for _ in range(30):
                scroll.bind_wheel_events()
            self.assertEqual(
                [len(widget._tclCommands or []) for widget in persistent],
                original_counts,
            )

            cell = tk.Button(scroll.inner, text="cell")
            cell.pack()
            scroll.bind_wheel_events()
            new_cell_count = len(cell._tclCommands or [])
            self.assertGreater(new_cell_count, 0)
            scroll.bind_wheel_events()
            self.assertEqual(len(cell._tclCommands or []), new_cell_count)
        finally:
            root.destroy()

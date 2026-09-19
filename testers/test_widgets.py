"""Interaction checks for shared Tkinter widgets without a display."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from mapper.widgets import ScrollableFrame


class ScrollableFrameTests(unittest.TestCase):
    def make_frame(self):
        frame = ScrollableFrame.__new__(ScrollableFrame)
        frame.canvas = Mock()
        frame.horizontal = True
        frame.vertical = True
        return frame

    def test_shift_wheel_scrolls_the_shelf_horizontally(self):
        frame = self.make_frame()

        result = frame._shift_scroll_horizontal(
            SimpleNamespace(delta=-120, num=None)
        )

        self.assertEqual(result, "break")
        frame.canvas.xview_scroll.assert_called_once_with(1, "units")

    def test_normal_wheel_scrolls_the_shelf_vertically(self):
        frame = self.make_frame()

        result = frame._scroll_vertical(
            SimpleNamespace(delta=-120, num=None, state=0)
        )

        self.assertEqual(result, "break")
        frame.canvas.yview_scroll.assert_called_once_with(1, "units")

    def test_shift_wheel_does_not_also_scroll_vertically(self):
        frame = self.make_frame()

        self.assertIsNone(frame._scroll_vertical(
            SimpleNamespace(widget=frame, delta=-120, num=None, state=0x0001)
        ))
        frame.canvas.yview_scroll.assert_not_called()

    def test_wheel_events_are_bound_to_every_shelf_widget(self):
        frame = self.make_frame()
        grandchild = SimpleNamespace(
            bind=Mock(), winfo_children=Mock(return_value=[])
        )
        child = SimpleNamespace(
            bind=Mock(), winfo_children=Mock(return_value=[grandchild])
        )
        frame.bind = Mock()
        frame.winfo_children = Mock(return_value=[child])

        frame.bind_wheel_events()

        for widget in (frame, child, grandchild):
            widget.bind.assert_any_call("<MouseWheel>", frame._scroll_vertical)
            widget.bind.assert_any_call(
                "<Shift-MouseWheel>", frame._shift_scroll_horizontal
            )


if __name__ == "__main__":
    unittest.main()

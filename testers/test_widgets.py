"""Interaction checks for shared Tkinter widgets without a display."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from mapper.widgets import ScrollableFrame


class ScrollableFrameTests(unittest.TestCase):
    def make_frame(self, *, visible=True):
        frame = ScrollableFrame.__new__(ScrollableFrame)
        frame.canvas = Mock()
        frame.winfo_ismapped = Mock(return_value=visible)
        return frame

    def test_shift_wheel_anywhere_scrolls_the_visible_shelf(self):
        frame = self.make_frame()
        outside = SimpleNamespace(master=None)

        result = frame._shift_scroll_horizontal(
            SimpleNamespace(widget=outside, delta=-120, num=None)
        )

        self.assertEqual(result, "break")
        frame.canvas.xview_scroll.assert_called_once_with(1, "units")

    def test_hidden_shelf_ignores_shift_wheel(self):
        frame = self.make_frame(visible=False)
        outside = SimpleNamespace(master=None)

        self.assertIsNone(frame._shift_scroll_horizontal(
            SimpleNamespace(widget=outside, delta=-120, num=None)
        ))
        frame.canvas.xview_scroll.assert_not_called()

    def test_normal_wheel_anywhere_scrolls_visible_shelf_vertically(self):
        frame = self.make_frame()
        outside = SimpleNamespace(master=None)

        result = frame._scroll_vertical(
            SimpleNamespace(widget=outside, delta=-120, num=None, state=0)
        )

        self.assertEqual(result, "break")
        frame.canvas.yview_scroll.assert_called_once_with(1, "units")

    def test_shift_wheel_does_not_also_scroll_vertically(self):
        frame = self.make_frame()

        self.assertIsNone(frame._scroll_vertical(
            SimpleNamespace(widget=frame, delta=-120, num=None, state=0x0001)
        ))
        frame.canvas.yview_scroll.assert_not_called()


if __name__ == "__main__":
    unittest.main()

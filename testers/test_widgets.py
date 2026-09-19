"""Interaction checks for shared Tkinter widgets without a display."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from mapper.widgets import ScrollableFrame


class ScrollableFrameTests(unittest.TestCase):
    def make_frame_and_child(self):
        frame = ScrollableFrame.__new__(ScrollableFrame)
        frame.canvas = Mock()
        child = SimpleNamespace(master=SimpleNamespace(master=frame))
        return frame, child

    def test_shift_wheel_scrolls_horizontally_under_the_pointer(self):
        frame, child = self.make_frame_and_child()

        result = frame._shift_scroll_horizontal(
            SimpleNamespace(widget=child, delta=-120, num=None)
        )

        self.assertEqual(result, "break")
        frame.canvas.xview_scroll.assert_called_once_with(1, "units")

    def test_shift_wheel_outside_this_frame_is_ignored(self):
        frame, _child = self.make_frame_and_child()
        outside = SimpleNamespace(master=None)

        self.assertIsNone(frame._shift_scroll_horizontal(
            SimpleNamespace(widget=outside, delta=-120, num=None)
        ))
        frame.canvas.xview_scroll.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""Interaction checks for shared Tkinter widgets without a display."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from mapper.widgets import ScrollableFrame


class ScrollableFrameTests(unittest.TestCase):
    def make_frame(self, *, smooth=True):
        frame = ScrollableFrame.__new__(ScrollableFrame)
        frame.canvas = Mock()
        frame.horizontal = True
        frame.vertical = True
        frame.smooth = smooth
        frame._scroll_remaining = {"x": 0, "y": 0}
        frame._scroll_after_ids = {"x": None, "y": None}
        frame.after = Mock(return_value="after-id")
        return frame

    def test_shift_wheel_scrolls_the_shelf_horizontally(self):
        frame = self.make_frame()

        result = frame._shift_scroll_horizontal(
            SimpleNamespace(delta=-120, num=None)
        )

        self.assertEqual(result, "break")
        frame.canvas.xview_scroll.assert_called_once_with(18, "units")
        self.assertEqual(frame._scroll_remaining["x"], 54)
        frame.after.assert_called_once()

    def test_normal_wheel_scrolls_the_shelf_vertically(self):
        frame = self.make_frame()

        result = frame._scroll_vertical(
            SimpleNamespace(delta=-120, num=None, state=0)
        )

        self.assertEqual(result, "break")
        frame.canvas.yview_scroll.assert_called_once_with(18, "units")
        self.assertEqual(frame._scroll_remaining["y"], 54)
        frame.after.assert_called_once()

    def test_repeated_wheel_input_accumulates_in_the_current_animation(self):
        frame = self.make_frame()
        event = SimpleNamespace(delta=-120, num=None, state=0)

        frame._scroll_vertical(event)
        frame._scroll_vertical(event)

        frame.canvas.yview_scroll.assert_called_once_with(18, "units")
        self.assertEqual(frame._scroll_remaining["y"], 126)
        frame.after.assert_called_once()

    def test_non_smooth_frames_keep_single_unit_scrolls(self):
        frame = self.make_frame(smooth=False)

        frame._scroll_vertical(
            SimpleNamespace(delta=-120, num=None, state=0)
        )

        frame.canvas.yview_scroll.assert_called_once_with(1, "units")
        frame.after.assert_not_called()

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

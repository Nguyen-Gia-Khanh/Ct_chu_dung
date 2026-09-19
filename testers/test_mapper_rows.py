"""Headless checks use real Tcl variables and record the widgets' grid commands.

These check row ordering and controller behavior; they do not verify native
Windows rendering, fonts, or mouse interaction.
"""

import tkinter as tk
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

from mapper.app import WarehouseMapperApp
from mapper.assignment_view import AssignmentView
from mapper.common import application_directory
from mapper.database import Placement
from mapper.designer import ShelfDesigner


class RowOrderTests(unittest.TestCase):
    def setUp(self):
        self.tcl = tk.Tcl()
        self.created_widgets = []

        def record_widget(parent, **options):
            widget = Mock()
            self.created_widgets.append((parent, options, widget))
            return widget

        for module, names in (
            ("mapper.designer.ttk", ("Label", "Spinbox", "Separator")),
            ("mapper.assignment_view.tk", ("Frame", "Label", "Button")),
        ):
            for name in names:
                patcher = patch(f"{module}.{name}", side_effect=record_widget)
                patcher.start()
                self.addCleanup(patcher.stop)

        self.designer = SimpleNamespace(
            _root=lambda: self.tcl, tk=self.tcl.tk,
            floor_var=tk.StringVar(self.tcl, "1"),
            shelf_code_var=tk.StringVar(self.tcl, "A"),
            row_count_var=tk.StringVar(self.tcl, "3"),
            row_inputs=[],
            row_editor_scroll=SimpleNamespace(inner=Mock()),
            add_row_button=Mock(), remove_row_button=Mock(),
            can_resize=Mock(return_value=True), on_rows_changed=Mock(),
        )
        self.designer.row_editor_scroll.inner.winfo_children.return_value = []
        for name in ("prepare_row_inputs", "validated_layout", "add_row", "remove_top_row"):
            setattr(self.designer, name, MethodType(getattr(ShelfDesigner, name), self.designer))
        self.designer.prepare_row_inputs([6, 6, 10], notify=False)

    def displayed_labels(self, parent):
        labels = []
        for widget_parent, options, widget in self.created_widgets:
            text = options.get("text", "")
            if widget_parent is parent and text.startswith("Row ") and widget.grid.called:
                labels.append((widget.grid.call_args.kwargs["row"], text))
        return [text for _, text in sorted(labels)]

    def test_designer_displays_highest_row_first(self):
        self.assertEqual(
            self.displayed_labels(self.designer.row_editor_scroll.inner),
            ["Row 3", "Row 2", "Row 1 — ground"],
        )
        self.assertEqual(self.designer.validated_layout()[2], [6, 6, 10])

    def test_add_button_preserves_lower_values_and_places_new_row_above_them(self):
        self.created_widgets.clear()
        self.designer.add_row()
        self.assertEqual(self.designer.validated_layout()[2], [6, 6, 10, 4])
        self.assertEqual(
            self.displayed_labels(self.designer.row_editor_scroll.inner),
            ["Row 4", "Row 3", "Row 2", "Row 1 — ground"],
        )

    def test_remove_button_and_typed_decrease_keep_bottom_rows(self):
        self.designer.remove_top_row()
        self.assertEqual(self.designer.validated_layout()[2], [6, 6])
        self.designer.row_count_var.set("1")
        self.designer.prepare_row_inputs()
        self.assertEqual(self.designer.validated_layout()[2], [6])
        self.designer.remove_top_row()
        self.assertEqual(self.designer.validated_layout()[2], [6])

    def test_occupied_top_row_rejection_keeps_inputs_unchanged(self):
        self.designer.can_resize.return_value = False
        self.designer.remove_top_row()
        self.assertEqual(self.designer.row_count_var.get(), "3")
        self.assertEqual(self.designer.validated_layout()[2], [6, 6, 10])

    def test_assignment_view_uses_same_ground_up_order_and_slot_names(self):
        view = SimpleNamespace(
            shelf_scroll=SimpleNamespace(
                inner=Mock(), canvas=Mock(), bind_wheel_events=Mock(),
            ),
            slot_buttons={}, selected_slot_text=tk.StringVar(self.tcl), on_select=Mock(),
        )
        view.shelf_scroll.inner.winfo_children.return_value = []
        self.created_widgets.clear()
        AssignmentView.render_shelf(view, "1", "A", [6, 6, 10], {}, None)
        self.assertEqual(
            self.displayed_labels(view.shelf_scroll.inner),
            ["Row 3", "Row 2", "Row 1 — ground"],
        )
        self.assertEqual(len(view.slot_buttons), 22)
        self.assertIn("L1-1A1-2", view.slot_buttons)
        self.assertIn("L1-1A3-10", view.slot_buttons)
        row_frames = [widget for parent, options, widget in self.created_widgets
                      if parent is view.shelf_scroll.inner and options.get("height") == 72]
        self.assertEqual(len(row_frames), 3)
        for row_number, (frame, count) in enumerate(zip(row_frames, (6, 6, 10)), start=1):
            buttons = [(options, widget) for parent, options, widget in self.created_widgets
                       if parent is frame and "command" in options]
            self.assertEqual([options["text"].split("\n")[0] for options, widget in buttons],
                             [f"A{row_number}-{number}" for number in range(1, count + 1)])
            self.assertEqual([widget.grid.call_args.kwargs["column"] for options, widget in buttons],
                             list(range(count)))
        for parent, options, _ in self.created_widgets:
            if options.get("text", "").startswith("A1-2\n") and "command" in options:
                options["command"]()
                break
        view.on_select.assert_called_once_with("L1-1A1-2")

    def test_database_default_stays_beside_entry_point(self):
        self.assertEqual(application_directory(), Path(__file__).resolve().parent)

    def test_occupied_last_cell_blocks_preview_shrink_for_saved_and_staged_products(self):
        for staged in (False, True):
            with self.subTest(staged=staged), patch("mapper.app.messagebox.showerror"):
                app = WarehouseMapperApp.__new__(WarehouseMapperApp)
                app.current_layout = [3]
                app.preview_key = ("1", "A")
                app.selected_slot = "1-A-R01-C03"
                app.designer = SimpleNamespace(validated_layout=Mock(return_value=("1", "A", [2])))
                app.committed_locations = {} if staged else {"P1": app.selected_slot}
                app.staged_assignments = {"P1": Placement(app.selected_slot, 8, "2000-01-01T09:00:00+00:00")} if staged else {}
                app.pending_unassignments = set()
                self.assertFalse(app.build_shelf_preview())
                self.assertEqual(app.current_layout, [3])
                self.assertEqual(app.selected_slot, "1-A-R01-C03")

    def test_staged_products_survive_adding_top_row(self):
        app = WarehouseMapperApp.__new__(WarehouseMapperApp)
        app.designer = self.designer
        app.current_layout = [6, 6, 10]
        app.preview_key = ("1", "A")
        app.current_shelf_id = None
        app.committed_locations = {"P1": "1-A-R01-C01"}
        assignment = Placement("1-A-R02-C06", 8, "2026-09-15T09:00:00+00:00")
        app.staged_assignments = {"P2": assignment}
        app.pending_unassignments = set()
        app.selected_slot = "1-A-R02-C06"
        app.refresh_all_views = Mock()
        app.notebook = Mock()
        app.status_text = tk.StringVar(self.tcl)
        self.designer.on_rows_changed = app.on_rows_changed
        self.designer.can_resize = app.can_resize_rows
        self.designer.add_row()
        self.assertEqual(app.current_layout, [6, 6, 10, 4])
        self.assertEqual(app.staged_assignments, {"P2": assignment})
        self.assertEqual(app.committed_locations, {"P1": "1-A-R01-C01"})
        self.assertEqual(app.selected_slot, "1-A-R02-C06")


if __name__ == "__main__":
    unittest.main()

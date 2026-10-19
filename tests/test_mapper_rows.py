"""Headless checks use real Tcl variables and record the widgets' grid commands.

These check row ordering and controller behavior; they do not verify native
Windows rendering, fonts, or mouse interaction.
"""

import tkinter as tk
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

from ui.desktop.app import WarehouseMapperApp
from mapper.core.common import application_directory
from mapper.persistence.database import Placement
from ui.desktop.designer import ShelfDesigner


class RowOrderTests(unittest.TestCase):
    def setUp(self):
        self.tcl = tk.Tcl()
        self.created_widgets = []

        def record_widget(parent, **options):
            widget = Mock()
            self.created_widgets.append((parent, options, widget))
            return widget

        for module, names in (
            ("ui.desktop.designer.ttk", ("Label", "Spinbox", "Separator")),
        ):
            for name in names:
                patcher = patch(f"{module}.{name}", side_effect=record_widget)
                patcher.start()
                self.addCleanup(patcher.stop)

        self.designer = SimpleNamespace(
            _root=lambda: self.tcl, tk=self.tcl.tk,
            floor_var=tk.StringVar(self.tcl, "1"),
            side_var=tk.StringVar(self.tcl, "1"),
            shelf_code_var=tk.StringVar(self.tcl, "A"),
            row_count_var=tk.StringVar(self.tcl, "3"),
            row_inputs=[], _row_trace_names=[],
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
        self.assertEqual(self.designer.validated_layout()[3], [6, 6, 10])

    def test_add_button_preserves_lower_values_and_places_new_row_above_them(self):
        self.created_widgets.clear()
        self.designer.add_row()
        self.assertEqual(self.designer.validated_layout()[3], [6, 6, 10, 4])
        self.assertEqual(
            self.displayed_labels(self.designer.row_editor_scroll.inner),
            ["Row 4", "Row 3", "Row 2", "Row 1 — ground"],
        )

    def test_remove_button_and_typed_decrease_keep_bottom_rows(self):
        self.designer.remove_top_row()
        self.assertEqual(self.designer.validated_layout()[3], [6, 6])
        self.designer.row_count_var.set("1")
        self.designer.prepare_row_inputs()
        self.assertEqual(self.designer.validated_layout()[3], [6])
        self.designer.remove_top_row()
        self.assertEqual(self.designer.validated_layout()[3], [6])

    def test_occupied_top_row_rejection_keeps_inputs_unchanged(self):
        self.designer.can_resize.return_value = False
        self.designer.remove_top_row()
        self.assertEqual(self.designer.row_count_var.get(), "3")
        self.assertEqual(self.designer.validated_layout()[3], [6, 6, 10])

    def test_database_default_stays_beside_entry_point(self):
        self.assertEqual(application_directory(), Path(__file__).resolve().parents[1])

    def test_occupied_last_cell_blocks_preview_shrink_for_saved_and_staged_products(self):
        for staged in (False, True):
            with self.subTest(staged=staged), patch("ui.desktop.app.messagebox.showerror"):
                app = WarehouseMapperApp.__new__(WarehouseMapperApp)
                app.database = Mock(get_shelf_id=Mock(return_value=None))
                app.current_layout = [3]
                app.preview_key = ("1", "1", "A")
                app.selected_slot = "L1-1A1-3"
                app.designer = SimpleNamespace(validated_layout=Mock(return_value=("1", "1", "A", [2])))
                app.committed_locations = {} if staged else {"P1": app.selected_slot}
                app.staged_assignments = {"P1": Placement(app.selected_slot, 8, "2000-01-01T09:00:00+00:00")} if staged else {}
                app.pending_unassignments = set()
                self.assertFalse(app.build_shelf_preview())
                self.assertEqual(app.current_layout, [3])
                self.assertEqual(app.selected_slot, "L1-1A1-3")

    def test_staged_products_survive_adding_top_row(self):
        app = WarehouseMapperApp.__new__(WarehouseMapperApp)
        app.designer = self.designer
        app.current_layout = [6, 6, 10]
        app.preview_key = ("1", "1", "A")
        app.current_shelf_id = None
        app.committed_locations = {"P1": "L1-1A1-1"}
        assignment = Placement("L1-1A2-6", 8, "2026-09-15T09:00:00+00:00")
        app.staged_assignments = {"P2": assignment}
        app.pending_unassignments = set()
        app.selected_slot = "L1-1A2-6"
        app.database = Mock(get_shelf_id=Mock(return_value=None))
        app.render_shelf = Mock()
        app.notebook = Mock()
        app.status_text = tk.StringVar(self.tcl)
        self.designer.on_rows_changed = app.on_rows_changed
        self.designer.can_resize = app.can_resize_rows
        self.designer.add_row()
        self.assertEqual(app.current_layout, [6, 6, 10, 4])
        self.assertEqual(app.staged_assignments, {"P2": assignment})
        self.assertEqual(app.committed_locations, {"P1": "L1-1A1-1"})
        self.assertEqual(app.selected_slot, "L1-1A2-6")


if __name__ == "__main__":
    unittest.main()

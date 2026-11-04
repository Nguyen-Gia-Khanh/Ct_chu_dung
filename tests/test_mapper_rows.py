"""Row editor ordering and controller behavior on a hidden Tk window.

These check row ordering and controller behavior; they do not verify native
Windows rendering, fonts, or mouse interaction. Occupied removals (ghost cells)
are covered in tests/test_tab1_row_edit.py.
"""

import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock

from ui.desktop.app import WarehouseMapperApp
from mapper.core.common import application_directory
from mapper.persistence.database import Placement
from ui.desktop.designer import ShelfDesigner


class RowOrderTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.designer = ShelfDesigner(self.root, lambda: None, Mock())
        self.designer.pack()
        self.designer.prepare_row_inputs([6, 6, 10], notify=False)

    def test_designer_displays_highest_row_first(self):
        self.assertEqual(self.designer.row_labels(), ["Row 3", "Row 2", "Row 1 — ground"])
        self.assertEqual(self.designer.validated_layout()[3], [6, 6, 10])

    def test_insert_at_the_top_bar_preserves_lower_values_and_places_new_row_above_them(self):
        self.designer.insert_row()
        self.assertEqual(self.designer.validated_layout()[3], [6, 6, 10, 4])
        self.assertEqual(self.designer.row_labels(), ["Row 4", "Row 3", "Row 2", "Row 1 — ground"])

    def test_top_row_removal_and_typed_decrease_keep_bottom_rows(self):
        self.designer.remove_row(3)
        self.assertEqual(self.designer.validated_layout()[3], [6, 6])
        self.designer.row_count_var.set("1")
        self.designer.prepare_row_inputs()
        self.assertEqual(self.designer.validated_layout()[3], [6])
        self.designer.remove_row(1)
        self.assertEqual(self.designer.validated_layout()[3], [6])

    def test_database_default_stays_beside_entry_point(self):
        self.assertEqual(application_directory(), Path(__file__).resolve().parents[1])

    def test_staged_products_survive_adding_top_row(self):
        app = WarehouseMapperApp.__new__(WarehouseMapperApp)
        app.designer = self.designer
        app.current_layout = [6, 6, 10]
        app.preview_key = ("1", "1", "A")
        app.preview_revert_location_id = False
        app._preview_renames, app._preview_plan = {}, None
        app.current_shelf_id = None
        app.committed_locations = {"P1": "L1-1A1-1"}
        assignment = Placement("L1-1A2-6", 8, "2026-09-15T09:00:00+00:00")
        app.staged_assignments = {"P2": assignment}
        app.pending_unassignments = set()
        app.selected_slot = "L1-1A2-6"
        app.database = Mock(get_shelf_id=Mock(return_value=None))
        app.render_shelf = Mock()
        app.notebook = Mock()
        app.status_text = tk.StringVar(self.root)
        self.designer.on_rows_changed = app.on_rows_changed
        self.designer.insert_row()
        self.assertEqual(app.current_layout, [6, 6, 10, 4])
        self.assertEqual(app.staged_assignments, {"P2": assignment})
        self.assertEqual(app.committed_locations, {"P1": "L1-1A1-1"})
        self.assertEqual(app.selected_slot, "L1-1A2-6")


if __name__ == "__main__":
    unittest.main()

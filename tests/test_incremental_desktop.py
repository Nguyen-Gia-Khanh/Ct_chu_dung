"""Cell and row refreshes must reuse widgets without a Tk display."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from mapper.persistence.database import Placement
from ui.desktop.assignment_view import AssignmentView
from ui.desktop.cell_transfer_view import CellTransferPane
from ui.desktop.location_assignment_view import LocationAssignmentView
from ui.desktop.primal_queue_view import PrimalQueueView
from ui.desktop.state_actions import StateActions
from ui.desktop.widgets import shelf_cell_visual, sync_tree_rows


class Button:
    def __init__(self):
        self.options = {}
        self.calls = 0

    def configure(self, **options):
        self.options.update(options)
        self.calls += 1

    def cget(self, name):
        return self.options[name]


class Tree:
    def __init__(self):
        self.order = []
        self.rows = {}
        self.deleted = []

    def get_children(self):
        return tuple(self.order)

    def exists(self, item_id):
        return item_id in self.rows

    def delete(self, item_id):
        self.deleted.append(item_id)
        self.order.remove(item_id)
        del self.rows[item_id]

    def insert(self, _parent, index, *, iid, values, tags):
        self.order.insert(index if isinstance(index, int) else len(self.order), iid)
        self.rows[iid] = {"values": tuple(map(str, values)), "tags": tags}

    def item(self, item_id, option=None, **updates):
        if updates:
            self.rows[item_id].update({
                key: tuple(map(str, value)) if key == "values" else value
                for key, value in updates.items()
            })
        return self.rows[item_id][option] if option else self.rows[item_id]

    def index(self, item_id):
        return self.order.index(item_id)

    def move(self, item_id, _parent, index):
        self.order.remove(item_id)
        self.order.insert(index, item_id)


class IncrementalDesktopTests(TestCase):
    def test_selected_assignment_cell_changes_count_and_color_in_place(self):
        button = Button()
        view = SimpleNamespace(
            slot_buttons={"A": button}, slot_labels={"A": "A1-1"},
            slot_counts={"A": (0, 0)}, selected_slot="A",
        )
        view._cell_visual = lambda name: AssignmentView._cell_visual(view, name)

        AssignmentView.refresh_cell(view, "A", (0, 1))
        self.assertIs(view.slot_buttons["A"], button)
        self.assertEqual(button.options["background"], "#fff2b2")
        self.assertEqual(button.options["borderwidth"], 3)
        self.assertEqual(button.options["font"], ("Segoe UI", 9, "bold"))
        self.assertIn("1 product", button.options["text"])

        AssignmentView.refresh_cell(view, "A", (2, 0))
        self.assertEqual(button.options["background"], "#d9ead3")
        self.assertIn("2 products", button.options["text"])
        AssignmentView.refresh_cell(view, "A", (0, 0))
        self.assertEqual(button.options["background"], "#f7f7f7")
        self.assertEqual(button.options["borderwidth"], 3)

    def test_primal_movement_updates_only_source_and_destination(self):
        buttons = {name: Button() for name in ("A", "B", "C")}
        view = SimpleNamespace(
            slot_buttons=buttons, slot_labels={name: name for name in buttons},
            selected_slot_name="B",
            current_contents=[("P1", "Bolts", Placement("A", 4, None))],
            _refresh_slot_contents=Mock(),
        )
        view._cell_visual = lambda name: PrimalQueueView._cell_visual(view, name)
        PrimalQueueView.refresh_cell(view, "A", [])
        PrimalQueueView.refresh_cell(view, "B", [
            ("P1", "Bolts", Placement("B", 4, None))
        ])
        self.assertEqual(buttons["A"].options["background"], "#f7f7f7")
        self.assertEqual(buttons["B"].options["background"], "#cfe8ff")
        self.assertEqual(buttons["B"].options["borderwidth"], 3)
        self.assertEqual(buttons["C"].calls, 0)
        view._refresh_slot_contents.assert_called_once()

    def test_transfer_refreshes_both_cells_for_switch_or_combine(self):
        buttons = {name: Button() for name in ("A", "B", "C")}
        pane = SimpleNamespace(
            slot_buttons=buttons, slot_labels={name: name for name in buttons},
            selected_address=SimpleNamespace(slot_name="A"),
            current_contents=[("P1", "Bolts", Placement("A", 4, None))],
            _refresh_contents=Mock(),
        )
        pane._cell_count = lambda name: CellTransferPane._cell_count(pane, name)
        pane._cell_visual = lambda name: CellTransferPane._cell_visual(pane, name)
        CellTransferPane.refresh_cell(pane, "A", [])
        CellTransferPane.refresh_cell(pane, "B", [
            ("P1", "Bolts", Placement("B", 4, None))
        ])
        self.assertEqual(buttons["A"].options["borderwidth"], 3)
        self.assertEqual(buttons["A"].options["background"], "#f7f7f7")
        self.assertEqual(buttons["B"].options["background"], "#d9ead3")
        self.assertEqual(buttons["C"].calls, 0)

    def test_assignment_preview_keeps_its_existing_count_format(self):
        button = Button()
        button.options["text"] = "1-01\n0 products"
        view = SimpleNamespace(
            shelf_slot_names={"A": (1, 1)}, shelf_slot_buttons={(1, 1): button},
            shelf_cell_colors={(1, 1): "#f7f7f7"}, _selected_shelf_cell=(1, 1),
        )
        LocationAssignmentView.refresh_shelf_cell(view, "A", 1)
        self.assertEqual(button.options["text"], "1-01\n1 product")
        self.assertEqual(button.options["background"], "#cfe8ff")
        button.options["text"] = "1-01\n1"
        LocationAssignmentView.refresh_shelf_cell(view, "A", 2)
        self.assertEqual(button.options["text"], "1-01\n2")

    def test_row_reconciliation_keeps_unaffected_item(self):
        tree = Tree()
        sync_tree_rows(tree, [
            ("hand::P1", ("P1", "Bolts", 2), ()),
            ("hand::P2", ("P2", "Washers", 1), ()),
        ])
        unaffected = tree.rows["hand::P2"]
        sync_tree_rows(tree, [
            ("hand::P1", ("P1", "Bolts", 3), ()),
            ("hand::P2", ("P2", "Washers", 1), ()),
        ])
        self.assertIs(tree.rows["hand::P2"], unaffected)
        self.assertEqual(tree.deleted, [])
        self.assertEqual(tree.rows["hand::P1"]["values"][2], "3")

    def test_only_loaded_transfer_cells_are_queried(self):
        app = StateActions()
        left = SimpleNamespace(slot_buttons={"A": Button()}, refresh_cell=Mock())
        right = SimpleNamespace(slot_buttons={"B": Button()}, refresh_cell=Mock())
        app.cell_transfer = SimpleNamespace(left=left, right=right)
        app.notebook = SimpleNamespace(select=lambda: str(app.cell_transfer))
        app.assignments = SimpleNamespace()
        app.primal_view = SimpleNamespace(slot_buttons={})
        app.shelf_browser = SimpleNamespace(current_shelf_id=None, view=SimpleNamespace(slot_buttons={}))
        app.database = Mock()
        app.database.get_slot_by_name.side_effect = lambda name: SimpleNamespace(slot_id=name)
        app.database.get_slot_contents.side_effect = lambda slot_id: [(slot_id, "", Placement(slot_id, 1, None))]

        app.refresh_visible_cells(("A", "B", "C"))
        self.assertEqual(app.database.get_slot_by_name.call_count, 2)
        left.refresh_cell.assert_called_once()
        right.refresh_cell.assert_called_once()

    def test_visual_state_matches_saved_empty_and_selected(self):
        self.assertEqual(shelf_cell_visual("A", 0)["background"], "#f7f7f7")
        self.assertEqual(shelf_cell_visual("A", 1)["background"], "#d9ead3")
        self.assertEqual(
            shelf_cell_visual("A", 1, selected=True, highlight_selected=True)["background"],
            "#cfe8ff",
        )

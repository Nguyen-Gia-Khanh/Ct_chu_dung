"""Tab 2 source restoration and persistent gray queue rows."""

from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mapper.persistence.database import Placement, WarehouseDatabase
from tests.support import WorkspaceTestCase
from tests.test_incremental_desktop import Tree
from ui.desktop.assignment_actions import AssignmentActions
from ui.desktop.catalog_actions import CatalogActions


FIRST = "2026-10-02T08:00:00+07:00"
SECOND = "2026-10-02T09:00:00+07:00"


class Actions(CatalogActions, AssignmentActions):
    pass


class ProductSourceTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.folder / "warehouse.db"
        self.db = WarehouseDatabase(self.path)
        self.db.import_products({"P1": "Bolts", "P2": "Washers"})
        self.db.import_catalog_products({"C1": ("Catalog part", "Part")})
        self.db.commit_shelf("1", "A", [2], {}, set(), side="1")
        self.first = self.db.get_slot_address("1", "1", "A", 1, 1)
        self.second = self.db.get_slot_address("1", "1", "A", 1, 2)

    def pull(self, *ids):
        names = {pid: ("Catalog part", "Part") for pid in ids}
        self.db.force_pull_to_queue(ids, FIRST, catalog_records=names)

    def test_catalog_product_returns_to_catalog_after_restart(self):
        self.pull("C1")
        self.db.add_to_on_hand({"C1": 5}, FIRST)
        db = WarehouseDatabase(self.path)
        db.dequeue_on_hand(["C1"], SECOND, restore_origin=True)
        self.assertNotIn("C1", dict(db.get_products()))
        self.assertEqual(db.get_catalog_products(), [("C1", "Catalog part", "Part")])
        self.assertEqual(db.get_on_hand_products(), {})
        self.assertEqual(db.get_returned_queue_products(), {})

    def test_repeated_catalog_pull_keeps_original_catalog_source(self):
        self.pull("C1")
        self.pull("C1")
        self.db.add_to_on_hand({"C1": 5}, FIRST)
        self.db.dequeue_on_hand(["C1"], SECOND, restore_origin=True)
        self.assertNotIn("C1", dict(self.db.get_products()))

    def test_queue_product_returns_with_current_stock_and_legacy_fallback(self):
        self.pull("P1")
        self.db.add_to_on_hand({"P1": 9, "P2": 4}, FIRST)
        self.db.dequeue_on_hand(["P1", "P2"], SECOND, restore_origin=True)
        returned = self.db.get_returned_queue_products()
        self.assertEqual((returned["P1"].stock_qty, returned["P2"].stock_qty), (9, 4))
        self.assertEqual(set(dict(self.db.get_products())), {"P1", "P2"})

    def test_shelf_return_preserves_original_stock_and_timestamp(self):
        self.db.add_to_on_hand({"P1": 7}, FIRST)
        self.db.assign_on_hand_to_slot(self.first.slot_id, FIRST)
        self.db.move_slot_to_on_hand(self.first.slot_id, SECOND, ["P1"])
        self.db.update_on_hand_stock("P1", 20)
        db = WarehouseDatabase(self.path)
        db.dequeue_on_hand(["P1"], SECOND, restore_origin=True)
        self.assertEqual(db.get_placement_details()["P1"], Placement(self.first.slot_name, 7, FIRST))
        self.assertEqual(db.get_on_hand_products(), {})

    def test_catalog_pull_restores_all_shelf_locations(self):
        self.db.add_to_on_hand({"P1": 7}, FIRST)
        self.db.assign_on_hand_to_slot(self.first.slot_id, FIRST)
        self.db.assign_exception("P1", self.second.slot_id)
        original = self.db.get_all_placement_items()
        self.pull("P1")
        self.assertEqual(self.db.get_all_placement_items(), [])
        self.db.add_to_on_hand({"P1": 7}, SECOND)
        self.db.dequeue_on_hand(["P1"], SECOND, restore_origin=True)
        self.assertEqual(self.db.get_all_placement_items(), original)

    def test_new_shelf_move_replaces_old_catalog_origin(self):
        self.pull("C1")
        self.db.add_to_on_hand({"C1": 5}, FIRST)
        self.db.assign_on_hand_to_slot(self.first.slot_id, FIRST)
        self.db.move_slot_to_on_hand(self.first.slot_id, SECOND)
        self.db.dequeue_on_hand(["C1"], SECOND, restore_origin=True)
        self.assertEqual(self.db.get_placement_details()["C1"], Placement(self.first.slot_name, 5, FIRST))

    def test_missing_source_rolls_back_entire_selected_return(self):
        self.pull("C1")
        self.db.add_to_on_hand({"P1": 7}, FIRST)
        self.db.assign_on_hand_to_slot(self.first.slot_id, FIRST)
        self.db.move_slot_to_on_hand(self.first.slot_id, SECOND)
        self.db.add_to_on_hand({"C1": 5}, FIRST)
        with closing(self.db.connect()) as connection, connection:
            connection.execute("DELETE FROM slots WHERE slot_id = ?", (self.first.slot_id,))
        with self.assertRaises(KeyError):
            self.db.dequeue_on_hand(["C1", "P1"], SECOND, restore_origin=True)
        self.assertEqual(set(self.db.get_on_hand_products()), {"P1", "C1"})
        self.assertIn("C1", dict(self.db.get_products()))

    def test_catalog_return_preserves_new_exception_assignment(self):
        self.pull("C1")
        self.db.add_to_on_hand({"C1": 5}, FIRST)
        self.db.assign_exception("C1", self.second.slot_id)
        with self.assertRaises(ValueError):
            self.db.dequeue_on_hand(["C1"], SECOND, restore_origin=True)
        self.assertIn("C1", self.db.get_on_hand_products())
        self.assertIn("C1", dict(self.db.get_products()))
        self.assertEqual(self.db.get_product_locations("C1"), [self.second.slot_name])

    def make_actions(self):
        app = Actions()
        app.products = {"P1": "Bolts", "P2": "Washers"}
        app.product_search = {"P1": "p1 bolts", "P2": "p2 washers"}
        app.committed_locations = {}
        app.committed_placements = {}
        app.staged_assignments = {}
        app.pending_unassignments = set()
        app.on_hand_products = {}
        app.returned_queue_products = {}
        app.transferred_stock = {}
        app.search_after_id = None
        app.queue_shift_clicks = 0
        app.queue_shift_timer = None
        app.status_text = Mock()
        app.root = Mock()
        app.database = Mock()
        app.reconcile_inventory_products = Mock()
        app.assignments = SimpleNamespace(
            queue_tree=Tree(), on_hand_tree=Mock(), whole_mode=False,
            search_var=SimpleNamespace(get=lambda: ""), queue_count_text=Mock(),
            set_queue_button_clicks=Mock(), search_location_text=Mock(),
        )
        return app

    def test_assigned_queue_row_is_retained_and_grayed_in_place(self):
        app = self.make_actions()
        app.refresh_product_queue()
        app.committed_locations["P1"] = self.first.slot_name
        app.committed_placements["P1"] = Placement(self.first.slot_name, 7, FIRST)
        app.refresh_product_queue()
        tree = app.assignments.queue_tree
        self.assertEqual(tree.get_children(), ("product::P1", "product::P2"))
        self.assertEqual(tree.item("product::P1", "tags"), ("assigned",))
        self.assertEqual(tree.item("product::P1", "values"), ("P1", "Bolts", "7"))
        self.assertEqual(tree.deleted, [])

    def test_shift_queue_transfer_skips_gray_rows(self):
        app = self.make_actions()
        app.products["ABCDE2"] = app.products.pop("P2")
        app.product_search["ABCDE2"] = app.product_search.pop("P2")
        app.committed_locations["P1"] = self.first.slot_name
        app.committed_placements["P1"] = Placement(self.first.slot_name, 7, FIRST)
        app.selected_address = self.second
        app.refresh_product_queue()
        app.move_selected_to_on_hand(to_shelf=True)
        records = app.database.assign_catalog_direct_to_slot.call_args.args[2]
        self.assertEqual(records, {"ABCDE2": ("Washers", "")})

    def test_normal_queue_transfer_skips_gray_selection(self):
        app = self.make_actions()
        app.committed_locations["P1"] = self.first.slot_name
        app.assignments.queue_tree.selection = lambda: ("product::P1",)
        with patch("ui.desktop.assignment_actions.messagebox.showinfo"):
            app.move_selected_to_on_hand()
        app.database.add_to_on_hand.assert_not_called()

    def test_dequeue_action_reconciles_restored_shelf_and_catalog_state(self):
        app = self.make_actions()
        app.on_hand_products = {"P1": SimpleNamespace(stock_qty=7)}
        app.assignments.on_hand_tree.selection.return_value = ("hand::P1",)
        app.dequeue_selected_on_hand()
        self.assertTrue(app.database.dequeue_on_hand.call_args.kwargs["restore_origin"])
        app.reconcile_inventory_products.assert_called_once_with(["P1"])

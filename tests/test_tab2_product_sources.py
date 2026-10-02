"""Tab 2 source restoration and persistent gray queue rows."""

from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mapper.persistence.database import Placement, WarehouseDatabase
from tests.support import WorkspaceTestCase
from tests.test_incremental_desktop import Tree
from ui.desktop.assignment_actions import AssignmentActions
from ui.desktop.catalog_actions import CatalogActions
from ui.desktop.state_actions import StateActions


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

    def test_shelf_removal_goes_to_on_hand_then_dequeue_to_total_queue(self):
        self.db.add_to_on_hand({"P1": 7}, FIRST)
        self.db.assign_on_hand_to_slot(self.first.slot_id, FIRST)
        self.db.move_slot_to_on_hand(self.first.slot_id, SECOND, ["P1"])
        self.assertEqual(self.db.get_placement_details(), {})
        self.assertEqual(self.db.get_on_hand_products()["P1"].stock_qty, 7)
        self.db.update_on_hand_stock("P1", 20)
        db = WarehouseDatabase(self.path)
        db.dequeue_on_hand(["P1"], SECOND, restore_origin=True)
        self.assertEqual(db.get_placement_details(), {})
        self.assertEqual(db.get_returned_queue_products()["P1"].stock_qty, 20)
        self.assertEqual(db.get_on_hand_products(), {})

    def test_catalog_pull_does_not_restore_shelf_locations_on_dequeue(self):
        self.db.add_to_on_hand({"P1": 7}, FIRST)
        self.db.assign_on_hand_to_slot(self.first.slot_id, FIRST)
        self.db.assign_exception("P1", self.second.slot_id)
        self.pull("P1")
        self.assertEqual(self.db.get_all_placement_items(), [])
        self.db.add_to_on_hand({"P1": 7}, SECOND)
        self.db.dequeue_on_hand(["P1"], SECOND, restore_origin=True)
        self.assertEqual(self.db.get_all_placement_items(), [])
        self.assertEqual(self.db.get_returned_queue_products()["P1"].stock_qty, 7)

    def test_catalog_membership_survives_assignment_and_shelf_removal(self):
        self.pull("C1")
        self.db.add_to_on_hand({"C1": 5}, FIRST)
        self.db.assign_on_hand_to_slot(self.first.slot_id, FIRST)
        self.db.move_slot_to_on_hand(self.first.slot_id, SECOND)
        self.assertEqual(self.db.get_on_hand_products()["C1"].stock_qty, 5)
        self.db.dequeue_on_hand(["C1"], SECOND, restore_origin=True)
        self.assertNotIn("C1", dict(self.db.get_products()))
        self.assertEqual(self.db.get_placement_details(), {})
        self.assertEqual(self.db.get_catalog_products(), [("C1", "Catalog part", "Part")])

    def test_dequeue_does_not_depend_on_former_shelf_existing(self):
        self.pull("C1")
        self.db.add_to_on_hand({"P1": 7}, FIRST)
        self.db.assign_on_hand_to_slot(self.first.slot_id, FIRST)
        self.db.move_slot_to_on_hand(self.first.slot_id, SECOND)
        self.db.add_to_on_hand({"C1": 5}, FIRST)
        with closing(self.db.connect()) as connection, connection:
            connection.execute("DELETE FROM slots WHERE slot_id = ?", (self.first.slot_id,))
        self.db.dequeue_on_hand(["C1", "P1"], SECOND, restore_origin=True)
        self.assertEqual(self.db.get_on_hand_products(), {})
        self.assertNotIn("C1", dict(self.db.get_products()))
        self.assertEqual(self.db.get_returned_queue_products()["P1"].stock_qty, 7)

    def test_direct_catalog_assignment_keeps_catalog_membership(self):
        self.db.assign_catalog_direct_to_slot(self.first.slot_id, FIRST, {"C1": ("Catalog part", "Part")})
        self.db.move_slot_to_on_hand(self.first.slot_id, SECOND)
        self.db.dequeue_on_hand(["C1"], SECOND, restore_origin=True)
        self.assertNotIn("C1", dict(self.db.get_products()))

    def test_queue_csv_import_establishes_queue_membership(self):
        self.pull("C1")
        self.db.import_products({"C1": "Now a queue product"})
        self.db.add_to_on_hand({"C1": 5}, FIRST)
        self.db.dequeue_on_hand(["C1"], SECOND, restore_origin=True)
        self.assertIn("C1", dict(self.db.get_products()))
        self.assertEqual(self.db.get_returned_queue_products()["C1"].stock_qty, 5)

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
        app.product_shortened_names = {"P1": "Bolts", "P2": "Washers"}
        app.catalog_products = {"C1": ("Catalog part", "Part")}
        app.catalog_only_products = set()
        app.selected_address = self.first
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
        self.assertEqual(tree.get_children(), ("product::P2", "product::P1"))
        self.assertEqual(tree.item("product::P1", "tags"), ("assigned",))
        self.assertEqual(tree.item("product::P1", "values"), ("P1", "Bolts", "7"))
        self.assertEqual(tree.deleted, [])

    def test_search_keeps_ready_matches_above_assigned_matches(self):
        app = self.make_actions()
        app.assignments.search_var = SimpleNamespace(get=lambda: "p")
        app.committed_locations["P1"] = self.first.slot_name
        app.committed_placements["P1"] = Placement(self.first.slot_name, 7, FIRST)
        app.refresh_product_queue()
        self.assertEqual(app.assignments.queue_tree.get_children(), ("product::P2", "product::P1"))

    def test_returned_rows_have_no_highlight_or_sort_priority(self):
        app = self.make_actions()
        app.returned_queue_products["P2"] = SimpleNamespace(stock_qty=4)
        app.refresh_product_queue()
        self.assertEqual(app.assignments.queue_tree.get_children(), ("product::P1", "product::P2"))
        self.assertEqual(app.assignments.queue_tree.item("product::P2", "tags"), ())
        self.assertEqual(app.assignments.queue_tree.item("product::P2", "values")[2], "4")

    def test_on_hand_product_is_unassigned_and_not_gray(self):
        app = self.make_actions()
        app.on_hand_products["P1"] = SimpleNamespace(stock_qty=7)
        app.refresh_product_queue()
        self.assertEqual(app.assignments.queue_tree.item("product::P1", "tags"), ())
        self.assertFalse(app.is_queue_product_available("P1"))

    def test_shift_queue_transfer_skips_gray_rows(self):
        app = self.make_actions()
        app.products["ABCDE2"] = app.products.pop("P2")
        app.product_search["ABCDE2"] = app.product_search.pop("P2")
        app.committed_locations["P1"] = self.first.slot_name
        app.committed_placements["P1"] = Placement(self.first.slot_name, 7, FIRST)
        app.selected_address = self.second
        app.refresh_product_queue()
        app.assign_queue_selection_to_address(to_shelf=True)
        records = app.database.assign_catalog_direct_to_slot.call_args.args[2]
        self.assertEqual(records, {"ABCDE2": ("Washers", "")})

    def test_normal_queue_transfer_skips_gray_selection(self):
        app = self.make_actions()
        app.committed_locations["P1"] = self.first.slot_name
        app.assignments.queue_tree.selection = lambda: ("product::P1",)
        with patch("ui.desktop.assignment_actions.messagebox.showinfo"):
            app.assign_queue_selection_to_address()
        app.database.add_to_on_hand.assert_not_called()

    def test_dequeue_action_reconciles_restored_shelf_and_catalog_state(self):
        app = self.make_actions()
        app.on_hand_products = {"P1": SimpleNamespace(stock_qty=7)}
        app.assignments.on_hand_tree.selection.return_value = ("hand::P1",)
        app.dequeue_selected_on_hand()
        self.assertTrue(app.database.dequeue_on_hand.call_args.kwargs["restore_origin"])
        app.reconcile_inventory_products.assert_called_once_with(["P1"])

    def test_normal_catalog_click_assigns_to_shelf_without_queue_or_on_hand(self):
        app = self.make_actions()
        app.database = self.db
        app.assignments.catalog_tree = Mock()
        app.assignments.catalog_tree.selection.return_value = ("catalog::C1",)
        with patch("ui.desktop.assignment_actions.StockQuantityDialog") as dialog:
            dialog.return_value.result = {"C1": 13}
            app.assign_catalog_selection_to_address()
        self.assertEqual(self.db.get_placement_details()["C1"].stock_qty, 13)
        self.assertEqual(self.db.get_on_hand_products(), {})
        self.assertEqual(self.db.get_returned_queue_products(), {})
        self.assertEqual(self.db.get_catalog_only_product_ids(), {"C1"})
        app.products["C1"] = "Catalog part"
        app.product_search["C1"] = "c1 catalog part"
        app.catalog_only_products = WarehouseDatabase(self.path).get_catalog_only_product_ids()
        app.refresh_product_queue()
        self.assertNotIn("product::C1", app.assignments.queue_tree.get_children())
        self.db.move_slot_to_on_hand(self.first.slot_id, SECOND)
        self.db.dequeue_on_hand(["C1"], SECOND, restore_origin=True)
        self.assertNotIn("C1", dict(self.db.get_products()))

    def test_normal_queue_click_assigns_selected_products_directly(self):
        app = self.make_actions()
        app.database = self.db
        app.assignments.queue_tree.selection = lambda: ("product::P1", "product::P2")
        with patch("ui.desktop.assignment_actions.StockQuantityDialog") as dialog:
            dialog.return_value.result = {"P1": 7, "P2": 11}
            app.assign_queue_selection_to_address()
        self.assertEqual(self.db.get_on_hand_products(), {})
        self.assertEqual(self.db.get_placement_details()["P1"].stock_qty, 7)
        self.assertEqual(self.db.get_placement_details()["P2"].stock_qty, 11)
        self.assertEqual(self.db.get_catalog_only_product_ids(), set())

    def test_cancel_normal_catalog_assignment_has_no_inventory_changes(self):
        app = self.make_actions()
        app.database = self.db
        app.assignments.catalog_tree = Mock()
        app.assignments.catalog_tree.selection.return_value = ("catalog::C1",)
        with patch("ui.desktop.assignment_actions.StockQuantityDialog") as dialog:
            dialog.return_value.result = None
            app.assign_catalog_selection_to_address()
        self.assertNotIn("C1", dict(self.db.get_products()))
        self.assertEqual(self.db.get_placement_details(), {})
        app.reconcile_inventory_products.assert_not_called()

    def test_catalog_assignment_requires_loaded_address_before_stock_dialog(self):
        app = self.make_actions()
        app.selected_address = None
        app.assignments.catalog_tree = Mock()
        app.assignments.catalog_tree.selection.return_value = ("catalog::C1",)
        with patch("ui.desktop.assignment_actions.StockQuantityDialog") as dialog, patch(
            "ui.desktop.assignment_actions.messagebox.showinfo"
        ):
            app.assign_catalog_selection_to_address()
        dialog.assert_not_called()
        app.database.assign_catalog_direct_to_slot.assert_not_called()

    def test_narrow_readback_updates_catalog_membership_before_queue_refresh(self):
        self.db.assign_catalog_direct_to_slot(self.first.slot_id, FIRST, {"C1": ("Catalog part", "Part")})
        app = self.make_actions()
        app.database = self.db
        app.catalog_search = {}
        app.product_id_lookup = {}
        app.remember_imported_products = lambda records: StateActions.remember_imported_products(app, records)
        app.apply_inventory_changes = Mock()
        StateActions.reconcile_inventory_products(app, ["C1"])
        self.assertIn("C1", app.catalog_only_products)
        app.refresh_product_queue()
        self.assertNotIn("product::C1", app.assignments.queue_tree.get_children())

    def test_invalid_direct_assignment_rolls_back_catalog_import(self):
        with self.assertRaises(KeyError):
            self.db.assign_catalog_direct_to_slot(-1, FIRST, {"C1": ("Catalog part", "Part")}, quantities={"C1": 4})
        self.assertNotIn("C1", dict(self.db.get_products()))

    def test_catalog_shift_assignment_also_stays_out_of_total_queue(self):
        app = self.make_actions()
        app.database = self.db
        app.assignments.catalog_tree = Mock()
        app.assignments.catalog_tree.selection.return_value = ("catalog::C1",)
        app.assign_catalog_selection_to_address(to_shelf=True)
        self.assertEqual(self.db.get_placement_details()["C1"].stock_qty, 999)
        self.assertEqual(self.db.get_catalog_only_product_ids(), {"C1"})

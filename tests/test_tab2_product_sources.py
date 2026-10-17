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
        self.db.import_catalog_products({"C1": ("Catalog part", '')})
        self.db.commit_shelf("1", "A", [2], {}, set(), side="1")
        self.first = self.db.get_slot_address("1", "1", "A", 1, 1)
        self.second = self.db.get_slot_address("1", "1", "A", 1, 2)












    def make_actions(self):
        app = Actions()
        app.products = {"P1": "Bolts", "P2": "Washers"}
        app.product_search = {"P1": "p1 bolts", "P2": "p2 washers"}
        app.product_brand_names = {"P1": "Bolts", "P2": "Washers"}
        app.catalog_products = {"C1": ("Catalog part", "Part")}
        app.selected_address = self.first
        app.committed_locations = {}
        app.committed_placements = {}
        app.staged_assignments = {}
        app.pending_unassignments = set()
        app.on_hand_products = {}
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
        self.assertEqual(tree.item("product::P1", "values"), ("P1", "Bolts", self.first.slot_name))
        self.assertEqual(tree.deleted, [])

    def test_search_keeps_ready_matches_above_assigned_matches(self):
        app = self.make_actions()
        app.assignments.search_var = SimpleNamespace(get=lambda: "p")
        app.committed_locations["P1"] = self.first.slot_name
        app.committed_placements["P1"] = Placement(self.first.slot_name, 7, FIRST)
        app.refresh_product_queue()
        self.assertEqual(app.assignments.queue_tree.get_children(), ("product::P2", "product::P1"))


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
        self.assertEqual(set(dict(self.db.get_products())), {"P1", "P2"})

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
        self.assertNotIn("C1", app.products)
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
        self.assertNotIn("C1", dict(self.db.get_products()))

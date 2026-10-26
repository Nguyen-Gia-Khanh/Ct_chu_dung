"""Set-based persistence operations, shared search/location helpers, and application services."""

from __future__ import annotations

from mapper.core.common import plain_header, split_locations
from mapper.core.search import ProductIndex
from mapper.features.csv_import import CSVData, prepare_import, read_csv, write_product_names
from mapper.persistence.database import Placement, WarehouseDatabase
from mapper.services.assignment import shift_prefix_error, shift_transfer
from mapper.services.cell_lookup import find_cell
from mapper.services.shelf_grid import build_grid, load_grid
from mapper.services.uploads import location_updates, upload_products
from tests.support import WorkspaceTestCase

FIRST = "2026-10-01T08:00:00+00:00"
SECOND = "2026-10-01T09:00:00+00:00"


class HelperTests(WorkspaceTestCase):
    def test_split_locations_accepts_every_separator_and_iterables(self) -> None:
        self.assertEqual(split_locations("A, B;C|D\nA"), ("A", "B", "C", "D"))
        self.assertEqual(split_locations(("A", " ", "B", "A")), ("A", "B"))
        self.assertEqual(split_locations(None), ())

    def test_plain_header_folds_vietnamese(self) -> None:
        self.assertEqual(plain_header("Mã hàng"), "mahang")
        self.assertEqual(plain_header("VỊ TRÍ LƯU TRỮ"), "vitriluutru")

    def test_product_index_matches_names_and_ranks_exact_id_first(self) -> None:
        index = ProductIndex([("ABC12", "Ốc vít", "Fastener"), ("ABC1", "Bolt", ""), ("XYZ", "Other", "")])
        self.assertEqual(sorted(index.matches("oc vit")), ["ABC12"])
        self.assertEqual(sorted(index.matches("abc")), ["ABC1", "ABC12"])
        self.assertEqual(index.top(index.matches("abc12"), "abc12"), ["ABC12"])
        self.assertEqual(index.top(["ABC12", "ABC1"], "abc1"), ["ABC1", "ABC12"])
        self.assertEqual(index.top(["ABC1", "ABC12"], "", before=lambda pid: pid == "ABC1"), ["ABC12", "ABC1"])
        index.remove(["XYZ"])
        self.assertIsNone(index.exact_id("xyz"))
        self.assertEqual(index.exact_id(" abc-1 "), "ABC1")

    def test_prepare_import_skips_blank_names_and_rejects_conflicts(self) -> None:
        data = CSVData(["code", "name"], [["P1", "Bolts"], ["P2", " "], ["", "No ID"], ["P3"], ["p-1", "Bolts"]])
        prepared = prepare_import(data, 0, 1)
        self.assertEqual(prepared.records, {"P1": ("Bolts", None)})
        self.assertEqual((prepared.skipped, prepared.duplicates), (3, 1))
        with self.assertRaisesRegex(ValueError, "different names"):
            prepare_import(CSVData(["code", "name"], [["P1", "A"], ["P-1", "B"]]), 0, 1)
        with self.assertRaisesRegex(ValueError, "No valid"):
            prepare_import(CSVData(["code", "name"], [["P1", " "]]), 0, 1)

    def test_write_product_names_keeps_delimiter_and_updates_or_appends(self) -> None:
        path = self.folder / "products.csv"
        path.write_text("Mã hàng;Tên hàng;Nhóm\nP-1;Old;G\n", encoding="utf-8")
        write_product_names(path, {"P1": "New", "P2": "Added"})
        data = read_csv(path)
        self.assertEqual(data.rows, [["P1", "New", "G"], ["P2", "Added", ""]])
        self.assertIn(";", path.read_text(encoding="utf-8-sig").splitlines()[0])


class SetBasedOperationTests(WorkspaceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.db = WarehouseDatabase(self.folder / "warehouse.db")
        self.db.import_products({"ABCDE1": "One", "ABCDE2": "Two", "ZZZZZ9": "Other"})
        self.db.commit_shelf("1", "A", [3], {}, set(), side="1")
        self.a1, self.a2, self.a3 = (self.db.get_slot_address("1", "1", "A", 1, cell) for cell in (1, 2, 3))

    def test_move_slot_to_on_hand_promotes_extra_locations_and_queues_the_rest(self) -> None:
        self.db.add_to_on_hand({"ABCDE1": 4, "ABCDE2": 5}, FIRST)
        self.db.assign_on_hand_to_slot(self.a1.slot_id, SECOND)
        self.db.assign_exception("ABCDE1", self.a2.slot_id, SECOND)
        self.db.assign_exception("ABCDE1", self.a3.slot_id, SECOND)

        self.assertEqual(self.db.move_slot_to_on_hand(self.a1.slot_id, SECOND), 2)

        self.assertEqual(self.db.get_product_locations("ABCDE1"), [self.a2.slot_name, self.a3.slot_name])
        self.assertEqual(self.db.get_placement_details()["ABCDE1"].stock_qty, 4)
        self.assertEqual(set(self.db.get_on_hand_products()), {"ABCDE2"})
        self.assertEqual(self.db.get_on_hand_products()["ABCDE2"].stock_qty, 5)
        self.assertEqual({row["slot_name"] for row in self.db.get_exception_staging()},
                         {self.a2.slot_name, self.a3.slot_name})

    def test_move_product_to_on_hand_removes_every_location(self) -> None:
        self.db.add_to_on_hand({"ABCDE1": 4}, FIRST)
        self.db.assign_on_hand_to_slot(self.a1.slot_id, SECOND)
        self.db.assign_exception("ABCDE1", self.a2.slot_id, SECOND)
        self.assertEqual(self.db.move_product_to_on_hand("ABCDE1", SECOND), 2)
        self.assertEqual(self.db.get_product_locations("ABCDE1"), [])
        self.assertEqual(self.db.get_on_hand_products()["ABCDE1"].stock_qty, 4)
        self.assertEqual(self.db.get_exception_staging(), [])

    def test_shift_transfer_revert_restores_every_table(self) -> None:
        self.db.add_to_on_hand({"ABCDE1": 7}, FIRST)
        self.db.assign_exception("ABCDE2", self.a2.slot_id, FIRST)
        before = {
            "placements": self.db.get_all_placement_items(),
            "on_hand": self.db.get_on_hand_products(),
            "staging": self.db.get_exception_staging(),
            "queue": self.db.get_product_records(),
        }
        moved, revert = shift_transfer(self.db, self.a1.slot_id, {"ABCDE1": ("One", ""), "ABCDE2": ("Two", "")})
        self.assertEqual(moved, 2)
        self.assertEqual(self.db.get_placement_details()["ABCDE1"], Placement(self.a1.slot_name, 7, self.db.get_placement_details()["ABCDE1"].assigned_at))
        self.assertEqual(self.db.get_placement_details()["ABCDE2"].stock_qty, 999)
        # The staged CSV row followed ABCDE2 from cell 2 to cell 1.
        self.assertEqual([row["slot_name"] for row in self.db.get_exception_staging()], [self.a1.slot_name])

        self.assertEqual(self.db.revert_shift_transfer(revert), 2)
        self.assertEqual(self.db.get_all_placement_items(), before["placements"])
        self.assertEqual(self.db.get_on_hand_products(), before["on_hand"])
        self.assertEqual(self.db.get_exception_staging(), before["staging"])
        self.assertEqual(self.db.get_product_records(), before["queue"])

    def test_revert_refuses_after_a_product_moved(self) -> None:
        _moved, revert = shift_transfer(self.db, self.a1.slot_id, {"ABCDE1": ("One", "")})
        self.db.swap_slot_contents(self.a1.slot_id, self.a2.slot_id)
        with self.assertRaisesRegex(ValueError, "has moved"):
            self.db.revert_shift_transfer(revert)

    def test_commit_shelf_returns_unassigned_products_with_their_stock(self) -> None:
        self.db.add_to_on_hand({"ABCDE1": 3}, FIRST)
        self.db.assign_on_hand_to_slot(self.a3.slot_id, SECOND)
        self.db.assign_exception("ABCDE1", self.a1.slot_id, SECOND)
        self.db.commit_shelf("1", "A", [2], {}, {"ABCDE1"}, side="1", shelf_id=self.a1.shelf_id)
        self.assertEqual(self.db.get_product_locations("ABCDE1"), [])
        self.assertEqual(self.db.get_on_hand_products()["ABCDE1"].stock_qty, 3)
        self.assertEqual(self.db.get_shelf(self.a1.shelf_id)[3], [2])

    def test_layout_shrink_names_the_first_occupied_cell(self) -> None:
        self.db.assign_exception("ABCDE1", self.a3.slot_id, SECOND)
        with self.assertRaisesRegex(ValueError, self.a3.slot_name):
            self.db.save_shelf("1", "A", [1], shelf_id=self.a1.shelf_id)

    def test_add_to_on_hand_rejects_placed_products_before_writing(self) -> None:
        self.db.assign_exception("ABCDE1", self.a1.slot_id, SECOND)
        with self.assertRaisesRegex(ValueError, "ABCDE1 is already assigned"):
            self.db.add_to_on_hand({"ABCDE2": 1, "ABCDE1": 2}, FIRST)
        self.assertEqual(self.db.get_on_hand_products(), {})

    def test_location_sets_and_upload_jobs_use_every_saved_location(self) -> None:
        self.db.assign_exception("ABCDE1", self.a2.slot_id, SECOND, stock_qty=5)
        self.db.assign_exception("ABCDE1", self.a1.slot_id, SECOND)
        self.assertEqual(self.db.get_location_sets(["ABCDE1", "ZZZZZ9"]),
                         {"ABCDE1": (self.a1.slot_name, self.a2.slot_name)})
        updates = location_updates(self.db, ["ABCDE1", "ZZZZZ9"])
        self.assertEqual([update.location_ids for update in updates], [(self.a1.slot_name, self.a2.slot_name), ()])
        placement = self.db.get_placement_details()["ABCDE1"]
        self.assertEqual(upload_products(self.db, [("ABCDE1", placement)])[0].stock_qty, 5)
        with self.assertRaisesRegex(ValueError, "no recorded quantity"):
            upload_products(self.db, [("ABCDE1", Placement(self.a1.slot_name, None, None))])

    def test_multi_location_products_and_staged_summary(self) -> None:
        self.db.assign_exception("ABCDE1", self.a1.slot_id, SECOND)
        self.db.assign_exception("ABCDE1", self.a2.slot_id, SECOND)
        self.assertEqual(self.db.get_multi_location_products(),
                         [("ABCDE1", "One", (self.a1.slot_name, self.a2.slot_name))])
        summary = self.db.get_staged_exception_summary()
        self.assertEqual(summary[0]["staged_locations"], f"{self.a1.slot_name}, {self.a2.slot_name}")
        # Only products new to the catalog still need adding there.
        self.assertEqual(self.db.add_staged_to_catalog(), 0)
        self.db.assign_exception("NEW1", self.a3.slot_id, SECOND)
        self.assertEqual(self.db.add_staged_to_catalog(["NEW1", "ABCDE1"]), 1)
        self.assertEqual(self.db.add_staged_to_catalog(), 0)


class ServiceTests(WorkspaceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.db = WarehouseDatabase(self.folder / "warehouse.db")
        self.db.import_products({"P1": "One"})
        self.shelf_id = self.db.save_shelf("1", "A", [2, 1], side="2")

    def test_shift_prefix_rule(self) -> None:
        self.assertIsNone(shift_prefix_error(["ABCDE1", "ABCDE2"]))
        self.assertIsNotNone(shift_prefix_error(["ABCDE1", "ZZZZZ2"]))
        self.assertIsNotNone(shift_prefix_error(["ABC"]))

    def test_grid_lists_rows_top_down_with_explicit_reverse_direction(self) -> None:
        grid = build_grid("1", "2", "A", [2, 1], ["L1-2A1-2", "L1-2A1-2"], revert_location_id=True)
        self.assertEqual([[(c.row, c.cell, c.count) for c in row] for row in grid.rows],
                         [[(2, 1, 0)], [(1, 2, 2), (1, 1, 0)]])
        self.assertEqual(grid.layout, (2, 1))
        loaded, contents = load_grid(self.db, self.shelf_id)
        self.assertEqual((loaded.key, contents), (("1", "2", "A"), []))

    def test_find_cell_by_product_location_and_shelf_name(self) -> None:
        slot = self.db.get_slot_address("1", "2", "A", 1, 2)
        self.db.assign_exception("P1", slot.slot_id, SECOND)
        self.assertEqual(find_cell(self.db, "p-1").address, slot)
        self.assertEqual(find_cell(self.db, slot.slot_name).address, slot)
        self.assertEqual(find_cell(self.db, "shelf a").shelf_id, self.shelf_id)
        self.assertEqual(find_cell(self.db, "nothing").shelves, [])

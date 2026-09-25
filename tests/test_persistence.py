"""Protect the stock and location transactions used by Tkinter."""

from __future__ import annotations

from mapper.persistence.database import Placement, WarehouseDatabase
from tests.support import WorkspaceTestCase


FIRST = "2026-09-20T08:00:00+00:00"
SECOND = "2026-09-20T09:00:00+00:00"


class PersistenceTests(WorkspaceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.path = self.folder / "warehouse.db"
        self.db = WarehouseDatabase(self.path)
        self.db.import_products({"P1": "Bolts", "P2": "Washers"})
        self.db.commit_shelf("1", "A", [2], {}, set(), side="1")
        self.first = self.db.get_slot_address("1", "1", "A", 1, 1)
        self.second = self.db.get_slot_address("1", "1", "A", 1, 2)

    def test_on_hand_assignment_is_atomic_and_survives_reopen(self) -> None:
        self.db.add_to_on_hand({"P1": 12, "P2": 4}, FIRST)
        with self.assertRaises(KeyError):
            self.db.assign_on_hand_to_slot(self.first.slot_id, SECOND, ["P1", "MISSING"])
        self.assertEqual(set(self.db.get_on_hand_products()), {"P1", "P2"})
        self.assertEqual(self.db.get_placement_details(), {})

        self.db.assign_on_hand_to_slot(self.first.slot_id, SECOND, ["P1"])
        reopened = WarehouseDatabase(self.path)
        self.assertEqual(reopened.get_placement_details()["P1"], Placement(self.first.slot_name, 12, SECOND))
        self.assertEqual(reopened.get_on_hand_products()["P2"].stock_qty, 4)

    def test_cell_transfer_keeps_quantities_and_timestamps(self) -> None:
        self.db.add_to_on_hand({"P1": 12, "P2": 4}, FIRST)
        self.db.assign_on_hand_to_slot(self.first.slot_id, SECOND, ["P1"])
        self.db.assign_on_hand_to_slot(self.second.slot_id, SECOND, ["P2"])

        self.assertEqual(self.db.swap_slot_contents(self.first.slot_id, self.second.slot_id), (1, 1))
        self.assertEqual(self.db.get_placement_details()["P1"], Placement(self.second.slot_name, 12, SECOND))
        self.assertEqual(self.db.get_placement_details()["P2"], Placement(self.first.slot_name, 4, SECOND))

    def test_exception_registration_remains_separate_from_catalog(self) -> None:
        self.db.assign_exception("E1", self.first.slot_id, product_name="Exception")
        self.assertEqual(len(self.db.get_exception_staging()), 1)
        self.assertEqual(self.db.add_staged_to_catalog(["E1"]), 1)
        self.assertIn("E1", {row[0] for row in self.db.get_catalog_products()})

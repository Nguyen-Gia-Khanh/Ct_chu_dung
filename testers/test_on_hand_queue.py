"""Persistent on-hand and address-first assignment database tests."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import tempfile
import unittest

from mapper.database import Placement, WarehouseDatabase


FIRST_TIME = "2026-09-20T08:00:00+00:00"
SECOND_TIME = "2026-09-20T09:00:00+00:00"


class OnHandQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "warehouse.db"
        self.database = WarehouseDatabase(self.path)
        self.database.import_products({"P1": "Bolts", "P2": "Washers"})
        self.shelf_id = self.database.commit_shelf("1", "A", [2], {}, set(), side="1")
        self.address = self.database.get_slot_address("1", "1", "A", 1, 2)
        self.assertIsNotNone(self.address)

    def test_on_hand_batch_survives_reopen_and_excludes_no_product_data(self) -> None:
        self.database.add_to_on_hand({"P1": 12, "P2": 4}, FIRST_TIME)

        reopened = WarehouseDatabase(self.path)
        products = reopened.get_on_hand_products()

        self.assertEqual(set(products), {"P1", "P2"})
        self.assertEqual(products["P1"].stock_qty, 12)
        self.assertEqual(products["P1"].queued_at, FIRST_TIME)
        self.assertEqual(reopened.get_placement_details(), {})

    def test_assign_all_on_hand_to_exact_address_is_atomic(self) -> None:
        self.database.add_to_on_hand({"P1": 12, "P2": 4}, FIRST_TIME)

        count = self.database.assign_on_hand_to_slot(self.address.slot_id, SECOND_TIME)

        self.assertEqual(count, 2)
        self.assertEqual(self.database.get_on_hand_products(), {})
        expected_slot = self.address.slot_name
        self.assertEqual(
            self.database.get_placement_details(),
            {
                "P1": Placement(expected_slot, 12, SECOND_TIME),
                "P2": Placement(expected_slot, 4, SECOND_TIME),
            },
        )

    def test_move_complete_address_back_to_on_hand_preserves_stock(self) -> None:
        self.database.add_to_on_hand({"P1": 12, "P2": 4}, FIRST_TIME)
        self.database.assign_on_hand_to_slot(self.address.slot_id, SECOND_TIME)

        count = self.database.move_slot_to_on_hand(self.address.slot_id, FIRST_TIME)

        self.assertEqual(count, 2)
        self.assertEqual(self.database.get_placement_details(), {})
        self.assertEqual(
            {
                key: item.stock_qty
                for key, item in self.database.get_on_hand_products().items()
            },
            {"P1": 12, "P2": 4},
        )

    def test_dequeue_all_returns_products_to_unassigned_state(self) -> None:
        self.database.add_to_on_hand({"P1": 12, "P2": 4}, FIRST_TIME)

        self.assertEqual(self.database.clear_on_hand(), 2)
        self.assertEqual(self.database.get_on_hand_products(), {})
        self.assertEqual(
            set(product_id for product_id, _name in self.database.get_products()),
            {"P1", "P2"},
        )

    def test_assigned_product_cannot_also_enter_on_hand(self) -> None:
        self.database.commit_shelf(
            "1",
            "A",
            [2],
            {"P1": Placement(self.address.slot_name, 5, FIRST_TIME)},
            set(),
            side="1",
            shelf_id=self.shelf_id,
        )

        with self.assertRaises(ValueError):
            self.database.add_to_on_hand({"P1": 5}, SECOND_TIME)

        self.assertEqual(self.database.get_on_hand_products(), {})
        self.assertIn("P1", self.database.get_placement_details())

    def test_opening_existing_database_adds_queue_table_without_changing_data(
        self,
    ) -> None:
        self.database.add_to_on_hand({"P1": 3}, FIRST_TIME)
        with closing(self.database.connect()) as connection, connection:
            connection.execute("DROP TABLE on_hand_queue")

        reopened = WarehouseDatabase(self.path)

        self.assertEqual(reopened.get_on_hand_products(), {})
        self.assertEqual(reopened.get_shelf(self.shelf_id), ("1", "1", "A", [2]))


if __name__ == "__main__":
    unittest.main()

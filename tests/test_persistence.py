"""Protect the stock and location transactions used by Tkinter."""

from __future__ import annotations

from unittest.mock import patch

from mapper.api.read_routes import ReadRoutes
from mapper.api.write_routes import WriteRoutes
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

    def test_csv_reimports_keep_locations_and_overlay_queue_names(self) -> None:
        self.db.import_catalog_products({
            "P1": ("Temporary warehouse name", "Temporary"),
            "W1": ("Warehouse name", "Warehouse"),
        })
        self.db.add_to_on_hand({"P1": 12}, FIRST)
        self.db.assign_on_hand_to_slot(self.first.slot_id, SECOND, ["P1"])

        route = WriteRoutes()
        replies = []
        route._send_json = replies.append
        route._send_error_json = lambda error: self.fail(str(error))
        mapping = {"code_col": "code", "name_col": "name"}
        with patch("mapper.api.write_routes._get_database", return_value=self.db):
            route._handle_api_post("/api/import-csv", {
                "mode": "new", "mapping": mapping,
                "data": {"rows": [
                    {"code": "P1", "name": "Formatted queue name"},
                    {"code": "P3", "name": "New queue name"},
                ]},
            })
            self.assertTrue(replies[-1]["success"])
            self.assertEqual(self.db.get_placement_details()["P1"], Placement(self.first.slot_name, 12, SECOND))
            self.assertEqual(dict((pid, name) for pid, name, _ in self.db.get_catalog_products()), {
                "P1": "Temporary warehouse name", "W1": "Warehouse name",
            })
            self.assertEqual(dict((pid, name) for pid, name, _ in self.db.get_display_catalog_products()), {
                "P1": "Formatted queue name", "P2": "Washers",
                "P3": "New queue name", "W1": "Warehouse name",
            })

            reader = ReadRoutes()
            responses = []
            reader._send_json = responses.append
            with patch("mapper.api.read_routes._get_database", return_value=self.db):
                reader._handle_api_get("/api/products/catalog", {})
            self.assertEqual({item["product_id"]: item["product_name"] for item in responses[-1]}, {
                "P1": "Formatted queue name", "P2": "Washers",
                "P3": "New queue name", "W1": "Warehouse name",
            })

            route._handle_api_post("/api/import-csv", {
                "mode": "return", "mapping": mapping,
                "data": {"rows": [
                    {"code": "P1", "name": "Final warehouse name"},
                    {"code": "W1", "name": "Renamed warehouse item"},
                ]},
            })
        self.assertTrue(replies[-1]["success"])
        display = {pid: name for pid, name, _ in self.db.get_display_catalog_products()}
        self.assertEqual(display["P1"], "Formatted queue name")
        self.assertEqual(display["W1"], "Renamed warehouse item")
        self.assertEqual(self.db.get_placement_details()["P1"], Placement(self.first.slot_name, 12, SECOND))

    def test_web_csv_import_rejects_blank_names(self) -> None:
        route = WriteRoutes()
        errors = []
        route._send_json = lambda response: self.fail(str(response))
        route._send_error_json = errors.append
        with patch("mapper.api.write_routes._get_database", return_value=self.db):
            route._handle_api_post("/api/import-csv", {
                "mode": "new", "mapping": {"code_col": "code", "name_col": "name"},
                "data": {"rows": [{"code": "P1", "name": " "}]},
            })
        self.assertEqual(len(errors), 1)
        self.assertEqual(dict(self.db.get_products())["P1"], "Bolts")

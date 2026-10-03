"""Multi-location lookup and web-update preparation without a browser."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mapper.api.write_routes import WriteRoutes
from mapper.features.location_comparison import compare_locations
from mapper.features.web_upload import LocationUpdate, UploadProduct, WebsiteUploader
from mapper.persistence.database import Placement, WarehouseDatabase
from tests.support import WorkspaceTestCase
from ui.desktop.location_comparison_view import LocationComparisonView
from ui.desktop.web_actions import WebActions


class MultiLocationTests(WorkspaceTestCase):
    def test_existing_product_can_be_found_and_grouped_after_exception_assignment(self) -> None:
        db = WarehouseDatabase(self.folder / "warehouse.db")
        db.import_products({"P1": "Bolts", "P2": "Washers"})
        db.commit_shelf("1", "A", [2], {}, set(), side="1")
        first = db.get_slot_address("1", "1", "A", 1, 1)
        second = db.get_slot_address("1", "1", "A", 1, 2)
        db.add_to_on_hand({"P1": 7}, "2026-09-20T08:00:00+00:00")
        db.assign_on_hand_to_slot(first.slot_id, "2026-09-20T09:00:00+00:00", ["P1"])
        db.assign_exception("P1", second.slot_id)

        expected = tuple(sorted((first.slot_name, second.slot_name)))
        self.assertEqual(db.find_product_locations("P1"), ("Bolts", expected))
        self.assertEqual(db.find_product_locations("P2"), ("Washers", ()))
        self.assertEqual(db.find_product_locations("UNKNOWN"), None)
        self.assertEqual(db.get_multi_location_products(), [("P1", "Bolts", expected)])

        actions = object.__new__(WebActions)
        actions.database = db
        self.assertEqual(actions._saved_location_sets({"P1"}), {"P1": expected})
        with patch.object(actions, "_web_placements", return_value=[
            ("P1", Placement(first.slot_name, 7, None))
        ]):
            self.assertEqual(actions._location_updates()[0].location_ids, expected)

        received = []

        def run_batch(products, _progress, _item_done, *, location_only, save):
            self.assertTrue(location_only)
            self.assertTrue(save)
            received.extend(products)

        uploader = SimpleNamespace(
            run_batch=run_batch,
        )
        route = WriteRoutes()
        replies = []
        route._send_json = replies.append
        with (
            patch("mapper.api.write_routes._get_database", return_value=db),
            patch("mapper.api.write_routes._get_uploader", return_value=uploader),
        ):
            route._handle_api_post("/api/web/modify-location", {
                "items": [
                    {"product_id": "P1", "slot_name": first.slot_name},
                    {"product_id": "P1", "slot_name": second.slot_name},
                ]
            })
        self.assertEqual([item.location_ids for item in received], [expected])
        self.assertEqual(replies[-1]["count"], 1)

    def test_comparison_resyncs_all_local_locations(self) -> None:
        differences, missing = compare_locations(
            {"P1": ["A", "B"]}, {"P1": "A"}
        )
        self.assertEqual(missing, [])
        self.assertEqual(differences[0].true_location, "A, B")
        self.assertTrue(differences[0].can_resync)
        view = SimpleNamespace(differences=differences, resynced={})
        self.assertEqual(
            LocationComparisonView.pending_updates(view)[0].location_ids,
            ("A", "B"),
        )

    def test_pipe_delimited_web_locations_match_local_locations(self) -> None:
        differences, missing = compare_locations(
            {"50605-KVR-600": ["L1-4D9-3", "L1-4D9-4"]},
            {"50605-KVR-600": "L1-4D9-3|L1-4D9-4"},
        )
        self.assertEqual(differences, [])
        self.assertEqual(missing, [])


class WebSelectionTests(unittest.TestCase):
    def test_updates_normalize_distinct_location_sets(self) -> None:
        update = LocationUpdate("P1", ("A", "B", "A"))
        self.assertEqual(update.location_ids, ("A", "B"))
        self.assertEqual(update.location_id, "A, B")
        self.assertEqual(LocationUpdate("P1", "").location_ids, ())
        self.assertEqual(UploadProduct("P1", 3, "A; B").location_ids, ("A", "B"))

    def test_web_selector_receives_the_complete_id_set(self) -> None:
        update = LocationUpdate("P1", ("A", "B"))
        uploader = WebsiteUploader(page=SimpleNamespace(), step_delay=0)
        with patch.object(
            uploader, "_dom", side_effect=lambda action, *_args: "" if action == "errors" else True
        ) as dom:
            uploader._select_location_ids(update, {"A": "11", "B": "22"})
        self.assertEqual(dom.call_args_list[0].args[0], "location_pick_ids")
        self.assertEqual(
            dom.call_args_list[0].args[2],
            {"ids": ["11", "22"], "names": ["A", "B"]},
        )


if __name__ == "__main__":
    unittest.main()

"""Selection scope and serial execution checks for KiotViet web batches."""

import unittest
from queue import Empty, Queue
from types import SimpleNamespace
from unittest.mock import ANY, Mock, call, patch

from mapper.app import WarehouseMapperApp
from mapper.database import Placement, SlotAddress
from mapper.web_upload import LocationUpdate, UploadProduct


LOCATION = "L1-1A1-1"
FIRST_TIME = "2000-01-01T09:00:00+00:00"


class WebBatchTests(unittest.TestCase):
    def make_app(self, *, all_products: bool) -> WarehouseMapperApp:
        app = WarehouseMapperApp.__new__(WarehouseMapperApp)
        app.assignments = SimpleNamespace(
            contents_tree=Mock(),
            on_hand_tree=Mock(),
            web_batch_mode_var=Mock(),
            web_batch_mode_check=Mock(),
            modify_location_button=Mock(),
            upload_button=Mock(),
            upload_status_text=Mock(),
        )
        app.assignments.web_batch_mode_var.get.return_value = all_products
        app.database = Mock()
        app.selected_address = SlotAddress(7, 3, "1", "1", "A", 1, 1, LOCATION)
        app.website_uploader = Mock()
        app.website_uploader.is_connected.return_value = True
        app.root = Mock()
        app.status_text = Mock()
        app.web_upload_busy = False
        app.web_upload_action = "upload"
        return app

    @staticmethod
    def contents(*quantities: int | None):
        return [
            (
                f"P{index}",
                f"Product {index}",
                Placement(LOCATION, quantity, FIRST_TIME),
            )
            for index, quantity in enumerate(quantities, start=1)
        ]

    @staticmethod
    def queued_events(events: Queue) -> list[tuple]:
        collected = []
        while True:
            try:
                collected.append(events.get_nowait())
            except Empty:
                return collected

    def test_single_mode_uses_exactly_the_clicked_product(self):
        app = self.make_app(all_products=False)
        app.assignments.contents_tree.selection.return_value = ("saved::P2",)
        app.database.get_slot_contents.return_value = self.contents(4, 9)

        placements = app._web_placements("Modify location")

        self.assertEqual(
            placements,
            [("P2", Placement(LOCATION, 9, FIRST_TIME))],
        )

    def test_all_products_mode_needs_no_row_selection(self):
        app = self.make_app(all_products=True)
        app.assignments.contents_tree.selection.return_value = ()
        app.database.get_slot_contents.return_value = self.contents(4, 9)

        placements = app._web_placements("Modify location")

        self.assertEqual(
            [product_id for product_id, _placement in placements],
            ["P1", "P2"],
        )
        app.assignments.contents_tree.selection.assert_not_called()

    def test_stock_batch_is_rejected_before_start_if_any_quantity_is_unknown(self):
        app = self.make_app(all_products=True)
        app.database.get_slot_contents.return_value = self.contents(4, None)

        with self.assertRaisesRegex(ValueError, "P2 has no recorded quantity"):
            app._upload_products()

    @patch("mapper.app.Thread")
    def test_start_captures_all_products_mode_for_the_worker(self, thread: Mock):
        app = self.make_app(all_products=True)
        products = [LocationUpdate("P1", LOCATION)]

        app._start_web_update(products, location_only=True)

        worker_args = thread.call_args.kwargs["args"]
        self.assertEqual(worker_args[0], products)
        self.assertTrue(worker_args[2])
        self.assertTrue(worker_args[3])
        thread.return_value.start.assert_called_once_with()
        app.assignments.web_batch_mode_check.configure.assert_called_once_with(
            state="disabled"
        )

    def test_location_batch_runs_in_order_and_forces_each_save(self):
        app = self.make_app(all_products=True)
        app.website_uploader.modify_location.side_effect = ["saved P1", "saved P2"]
        products = [LocationUpdate("P1", LOCATION), LocationUpdate("P2", LOCATION)]
        events = Queue()

        app._run_web_upload(
            products,
            events,
            location_only=True,
            save_each_product=True,
        )

        self.assertEqual(
            app.website_uploader.modify_location.call_args_list,
            [
                call(products[0], ANY, save=True),
                call(products[1], ANY, save=True),
            ],
        )
        queued = self.queued_events(events)
        self.assertEqual(
            queued[-1],
            ("done", f"Updated web locations for 2 products at {LOCATION}."),
        )
        self.assertTrue(any("[1/2] Finished P1" in event[1] for event in queued))

    def test_stock_batch_uses_the_same_serial_worker(self):
        app = self.make_app(all_products=True)
        app.website_uploader.upload.side_effect = ["saved P1", "saved P2"]
        products = [
            UploadProduct("P1", 4, LOCATION),
            UploadProduct("P2", 9, LOCATION),
        ]
        events = Queue()

        app._run_web_upload(
            products,
            events,
            location_only=False,
            save_each_product=True,
        )

        self.assertEqual(
            app.website_uploader.upload.call_args_list,
            [
                call(products[0], ANY, save=True),
                call(products[1], ANY, save=True),
            ],
        )
        self.assertEqual(
            self.queued_events(events)[-1],
            ("done", f"Uploaded stock and web locations for 2 products at {LOCATION}."),
        )

    def test_batch_stops_on_first_failure_and_identifies_the_product(self):
        app = self.make_app(all_products=True)
        app.website_uploader.modify_location.side_effect = [
            "saved P1",
            RuntimeError("boom"),
        ]
        products = [
            LocationUpdate("P1", LOCATION),
            LocationUpdate("P2", LOCATION),
            LocationUpdate("P3", LOCATION),
        ]
        events = Queue()

        app._run_web_upload(
            products,
            events,
            location_only=True,
            save_each_product=True,
        )

        self.assertEqual(app.website_uploader.modify_location.call_count, 2)
        error = self.queued_events(events)[-1]
        self.assertEqual(error[0], "error")
        self.assertIn("stopped after 1/3", error[1])
        self.assertIn("Failed at P2", error[1])
        self.assertIn("boom", error[1])
        self.assertTrue(error[2])


class WebServerShelvesTests(unittest.TestCase):
    def setUp(self) -> None:
        import http.server
        import os
        import tempfile
        import threading
        from mapper.database import WarehouseDatabase
        from mapper.web_server import WarehouseApiHandler
        import mapper.web_server

        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = f"{self.temp_dir.name}/test_shelves.db"
        self.db = WarehouseDatabase(self.db_path)
        self.orig_get_db = mapper.web_server._get_database
        mapper.web_server._get_database = lambda: WarehouseDatabase(self.db_path)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), WarehouseApiHandler)
        self.port = self.server.server_port
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

    def tearDown(self) -> None:
        import mapper.web_server
        self.server.shutdown()
        mapper.web_server._get_database = self.orig_get_db
        self.temp_dir.cleanup()

    def test_post_shelves_creates_shelf_and_appears_in_get(self) -> None:
        import json
        import urllib.request

        payload = {
            "floor": "1",
            "side": "1",
            "shelf": "K",
            "rows_count": 3,
            "default_cols": 6,
            "custom_row_cols": {"1": 4, "2": 5, "3": 6},
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/shelves",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["success"])
            self.assertEqual(data["shelf"], "K")
            self.assertEqual(data["rows_count"], 3)
            shelf_id = data["id"]

        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/shelves") as resp:
            shelves = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(len(shelves), 1)
            self.assertEqual(shelves[0]["shelf"], "K")
            self.assertEqual(shelves[0]["id"], shelf_id)

        # Test DELETE
        del_req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/shelves/{shelf_id}",
            method="DELETE",
        )
        with urllib.request.urlopen(del_req) as resp:
            self.assertEqual(resp.status, 200)

        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/shelves") as resp:
            shelves = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(len(shelves), 0)


if __name__ == "__main__":
    unittest.main()

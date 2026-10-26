"""The desktop sidecar speaks line-delimited JSON over stdio against a real database."""

from __future__ import annotations

import json
import subprocess
import sys
from itertools import count
from pathlib import Path

from mapper.persistence.database import WarehouseDatabase
from tests.support import WorkspaceTestCase

ROOT = Path(__file__).resolve().parents[1]


class SidecarTests(WorkspaceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.path = self.folder / "warehouse.db"
        db = WarehouseDatabase(self.path)
        db.import_products({"ABCDE1": ("Ốc vít", "Bolt"), "ABCDE2": "Washers", "ZZZ9": "Other"})
        db.import_catalog_products({"C1": ("Catalog part", "")})
        db.save_shelf("1", "A", [3], side="1")
        self.first, self.second, self.third = (db.get_slot_address("1", "1", "A", 1, cell) for cell in (1, 2, 3))
        # stderr goes to a file: an unread pipe would block the sidecar once full.
        self.log = open(self.folder / "sidecar.log", "wb")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "mapper.rpc", "--db", str(self.path)], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log)
        self.addCleanup(self._stop)
        self.ids = count(1)
        self.events = []
        ready = self._read()
        self.assertEqual(ready["event"], "ready")

    def _stop(self) -> None:
        if self.process.poll() is None:
            self.process.stdin.write(b'{"id": 0, "method": "shutdown"}\n')
            self.process.stdin.flush()
            self.process.wait(timeout=10)
        for stream in (self.process.stdin, self.process.stdout, self.log):
            stream.close()

    def _read(self) -> dict:
        line = self.process.stdout.readline()
        self.assertTrue(line, (self.folder / "sidecar.log").read_text(encoding="utf-8", errors="replace"))
        return json.loads(line)

    def call(self, method: str, **params):
        request_id = next(self.ids)
        self.process.stdin.write((json.dumps({"id": request_id, "method": method, "params": params}) + "\n").encode())
        self.process.stdin.flush()
        while True:
            message = self._read()
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(f"{message['error']['type']}: {message['error']['message']}")
                return message["result"]
            self.events.append(message)

    def test_search_assign_and_changes_round_trip(self) -> None:
        found = self.call("products.search", query="oc vit", scope="hot", order="queue")
        self.assertEqual([row["product_id"] for row in found["rows"]], ["ABCDE1"])
        self.assertEqual((found["total"], found["ready"]), (1, 1))

        result = self.call("assign.shift_queue", slot_id=self.first.slot_id, product_ids=["ABCDE1", "ABCDE2"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["changes"]["slots"], [self.first.slot_name])
        self.assertEqual(result["changes"]["products"], ["ABCDE1", "ABCDE2"])

        found = self.call("products.search", query="abcde", scope="hot", order="queue")
        self.assertEqual({row["location"] for row in found["rows"]}, {self.first.slot_name})
        self.assertEqual(found["rows"][0]["stock"], 999)
        self.assertEqual(found["ready"], 0)
        grid = self.call("shelves.grid", shelf_id=self.first.shelf_id)
        self.assertEqual([cell["count"] for cell in grid["rows"][0]], [2, 0, 0])

        self.assertTrue(self.call("assign.can_revert"))
        self.call("assign.revert")
        self.assertEqual(self.call("products.search", query="abcde", scope="hot")["rows"][0]["location"], "")

    def test_errors_come_back_as_data(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "ValueError: Cannot transfer"):
            self.call("assign.shift_queue", slot_id=self.first.slot_id, product_ids=["ABCDE1", "ZZZ9"])
        with self.assertRaisesRegex(RuntimeError, "LookupError"):
            self.call("no.such.method")
        self.assertEqual(self.call("app.info")["max_rows"], 750)

    def test_combine_asks_before_merging_shared_products(self) -> None:
        self.call("exceptions.assign", product_id="C1", slot_id=self.first.slot_id, stock=4)
        self.call("exceptions.assign", product_id="C1", slot_id=self.second.slot_id)
        self.assertEqual(self.call("cells.combine", source_slot_id=self.first.slot_id,
                                   target_slot_id=self.second.slot_id), {"needs_merge": ["C1"]})
        merged = self.call("cells.combine", source_slot_id=self.first.slot_id,
                           target_slot_id=self.second.slot_id, merge=True)
        self.assertEqual(merged["changes"]["products"], ["C1"])
        self.assertEqual(self.call("exceptions.find", product_id="c-1")["locations"], [self.second.slot_name])
        contents = self.call("cells.contents", slot_id=self.second.slot_id)
        self.assertEqual([(row["product_id"], row["stock"]) for row in contents], [("C1", 4)])

    def test_designer_preview_guards_occupied_cells(self) -> None:
        self.call("exceptions.assign", product_id="C1", slot_id=self.third.slot_id)
        with self.assertRaisesRegex(RuntimeError, self.third.slot_name):
            self.call("designer.preview", floor="1", side="1", code="A", layout=[2], shelf_id=self.first.shelf_id)
        preview = self.call("designer.preview", floor="1", side="1", code="A", layout=[3, 2], shelf_id=self.first.shelf_id)
        self.assertEqual(preview["layout"], [3, 2])
        self.assertEqual(preview["rows"][1][2]["count"], 1)
        committed = self.call("designer.commit", floor="1", side="1", code="A", layout=[3, 2], shelf_id=self.first.shelf_id)
        self.assertTrue(committed["changes"]["shelves"])
        self.assertEqual(len(self.call("shelves.grid", shelf_id=self.first.shelf_id)["rows"]), 2)

    def test_designer_reverse_id_round_trip_and_preview(self) -> None:
        sid = self.first.shelf_id
        self.call("exceptions.assign", product_id="C1", slot_id=self.first.slot_id, stock=4)
        preview = self.call("designer.preview", floor="1", side="1", code="A", layout=[3],
                            shelf_id=sid, revert_location_id=True)
        self.assertTrue(preview["revert_location_id"])
        self.assertEqual([c["cell"] for c in preview["rows"][0]], [3, 2, 1])
        self.assertEqual(preview["rows"][0][0]["count"], 1)
        self.assertFalse(self.call("shelves.grid", shelf_id=sid)["revert_location_id"])
        self.call("designer.commit", floor="1", side="1", code="A", layout=[3],
                  shelf_id=sid, revert_location_id=True)
        self.assertTrue(self.call("shelves.grid", shelf_id=sid)["revert_location_id"])
        # Existing callers that omit the setting preserve it.
        self.call("designer.commit", floor="1", side="1", code="A", layout=[3], shelf_id=sid)
        self.assertEqual([c["cell"] for c in self.call("designer.preview", floor="1", side="1", code="A",
                                                    layout=[3], shelf_id=sid)["rows"][0]], [3, 2, 1])

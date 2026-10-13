"""Exercise the actual HTTP receiver without touching warehouse data."""

import http.client
import json
import threading

from barcode_web.server import ScanStore, ScannerServer
from tests.support import WorkspaceTestCase


class BarcodeWebTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.store = ScanStore(self.folder)
        self.server = ScannerServer(("127.0.0.1", 0), self.store, "test-token", {
            "phone_urls": ["https://192.168.1.2:8765/#test-token"],
            "setup_urls": ["http://192.168.1.2:8766/setup"],
        })
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, payload=None, *, token="test-token", content_type="application/json"):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": content_type}
        body = json.dumps(payload).encode() if payload is not None else None
        connection.request(method, path, body, headers)
        response = connection.getresponse()
        status, body = response.status, response.read()
        connection.close()
        return status, body

    def test_text_delivery_retry_and_reload(self):
        payload = {"id": "scan-123", "text": " 00123\x1dViệt <script> ", "format": "Code128"}
        self.assertEqual(self.request("POST", "/api/scans", payload)[0], 200)
        status, body = self.request("POST", "/api/scans", payload)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["duplicate"])
        self.assertEqual(len(self.store.recent()), 1)
        self.assertEqual(self.store.recent()[0]["text"], payload["text"])
        restored = ScanStore(self.folder)
        self.assertEqual(restored.recent(), self.store.recent())
        self.assertTrue(restored.add(payload)["duplicate"])
        self.assertEqual(json.loads(self.request("GET", "/api/scans")[1])[0]["text"], payload["text"])
        with self.store.path.open("a", encoding="utf-8") as output:
            output.write("\nnull\n[]\n{}\nnot-json\n")
        self.assertEqual(ScanStore(self.folder).recent(), self.store.recent())

    def test_rejects_images_extra_fields_invalid_json_and_missing_session(self):
        payload = {"id": "scan-123", "text": "0123", "format": "Code128"}
        self.assertEqual(self.request("POST", "/api/scans", payload, token="wrong")[0], 403)
        self.assertEqual(self.request("GET", "/api/scans", token="wrong")[0], 403)
        self.assertEqual(self.request("GET", "/api/scans", token="é")[0], 403)
        self.assertEqual(self.request("POST", "/api/scans", {**payload, "image": "pixels"})[0], 400)
        self.assertEqual(self.request("POST", "/api/scans", payload, content_type="image/jpeg")[0], 415)
        self.assertEqual(self.request("POST", "/api/scans", {**payload, "text": "x" * 4097})[0], 400)
        self.assertEqual(self.request("POST", "/api/scans", [payload])[0], 400)
        self.assertEqual(self.request("POST", "/api/scans", {**payload, "text": ""})[0], 400)
        self.assertEqual(self.request("POST", "/api/scans", {**payload, "id": "bad\nID"})[0], 400)
        self.assertEqual(self.request("POST", "/api/scans", {**payload, "text": "x" * 40000})[0], 413)
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        connection.request("POST", "/api/scans", b"{broken-json", {
            "Authorization": "Bearer test-token", "Content-Type": "application/json"})
        response = connection.getresponse()
        self.assertEqual(response.status, 400)
        response.read()
        connection.close()
        self.assertFalse(self.store.path.exists())

    def test_assets_session_and_private_files(self):
        for path in ("/scan", "/receiver", "/worker.js", "/processing.js", "/vendor/reader.js", "/vendor/zxing_reader.wasm"):
            self.assertEqual(self.request("GET", path)[0], 200, path)
        self.assertEqual(json.loads(self.request("GET", "/api/session")[1])["token"], "test-token")
        for path in ("/../data/warehouse_locations.db", "/certs/rootCA-key.pem", "/rootCA-key.pem", "/scans.jsonl", "/server.py"):
            self.assertEqual(self.request("GET", path)[0], 404, path)

    def test_failed_save_is_not_acknowledged(self):
        from unittest.mock import patch
        with patch.object(self.store, "add", side_effect=OSError("disk full")):
            status, body = self.request("POST", "/api/scans", {"id": "scan-1", "text": "001", "format": "EAN13"})
        self.assertEqual(status, 503)
        self.assertIn("Could not save", json.loads(body)["error"])

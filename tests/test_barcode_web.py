"""Exercise the actual HTTP receiver without touching warehouse data."""

import http.client
import json
import threading
import io
import ssl
from contextlib import closing, redirect_stdout, redirect_stderr

from barcode_web.server import ScanStore, ScannerServer, phone_address, DATA
from barcode_web.lookup import WarehouseLookup
from tests.test_barcode_lookup import create_test_warehouse
from tests.support import WorkspaceTestCase


class BarcodeWebTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.store = ScanStore(self.folder)
        self.server = ScannerServer(("127.0.0.1", 0), self.store, "test-token", {
            "phone_urls": ["https://192.168.1.2:8765/#test-token"],
            "setup_urls": ["http://192.168.1.2:8766/setup"],
        }, lookup=WarehouseLookup(create_test_warehouse(self.folder / "warehouse.db")))
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

    def test_scan_returns_locations_and_retry_queries_current_database(self):
        import sqlite3
        payload = {"id": "location-1", "text": "001234567890", "format": "Code128"}
        status, body = self.request("POST", "/api/scans", payload)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["lookup"]["locations"], ["L1-1A2-3", "L2-2B4-5"])
        with closing(sqlite3.connect(self.server.lookup.path)) as connection, connection:
            connection.execute("DELETE FROM exception_placements WHERE product_id='00123-456-7890'")
        answer = json.loads(self.request("POST", "/api/scans", payload)[1])
        self.assertTrue(answer["duplicate"])
        self.assertEqual(answer["lookup"]["locations"], ["L1-1A2-3"])
        self.assertEqual(len(self.store.recent()), 1)

    def test_failed_database_lookup_is_retryable(self):
        import sqlite3
        from unittest.mock import patch
        payload = {"id": "location-1", "text": "001234567890", "format": "Code128"}
        with patch.object(self.server.lookup, "find", side_effect=sqlite3.OperationalError("database locked")):
            status, body = self.request("POST", "/api/scans", payload)
        self.assertEqual(status, 503)
        self.assertIn("Warehouse lookup failed", json.loads(body)["error"])
        self.assertFalse(self.store.recent())
        self.assertEqual(self.request("POST", "/api/scans", payload)[0], 200)

    def test_one_phone_address_with_private_network_preference_and_fallback(self):
        import os
        from unittest.mock import patch, Mock
        addresses = ["192.168.1.21", "192.168.1.13", "172.31.64.1"]
        if os.name == "nt":
            with patch("barcode_web.server.subprocess.run", return_value=Mock(returncode=0, stdout="192.168.1.13\n")):
                self.assertEqual(phone_address(addresses), "192.168.1.13")
            with patch("barcode_web.server.subprocess.run", side_effect=OSError("network selection unavailable")):
                self.assertEqual(phone_address(addresses), "192.168.1.21")
        self.assertIsNone(phone_address([]))

    def test_second_scanner_cannot_share_the_existing_port(self):
        with self.assertRaises(OSError):
            ScannerServer(self.server.server_address, self.store, "another-token", self.server.info)

    def test_certificate_rejections_and_disconnects_do_not_dump_tracebacks(self):
        from unittest.mock import patch, Mock
        output, errors = io.StringIO(), io.StringIO()
        rejection = ssl.SSLError("certificate rejected")
        rejection.reason = "SSLV3_ALERT_CERTIFICATE_UNKNOWN"
        failures = [rejection, rejection, ConnectionResetError(), BrokenPipeError(), TimeoutError(), ssl.SSLEOFError()]
        with redirect_stdout(output), redirect_stderr(errors):
            with patch.object(self.server, "finish_request", side_effect=failures):
                for _failure in failures:
                    self.server.process_request_thread(Mock(), ("192.168.1.19", 57030))
            with patch("barcode_web.server.time.monotonic", return_value=self.server.last_connection_note + 61):
                with patch.object(self.server, "finish_request", side_effect=rejection):
                    self.server.process_request_thread(Mock(), ("192.168.1.19", 57031))
        self.assertEqual(output.getvalue().count("needs certificate trust setup"), 2)
        self.assertIn("http://192.168.1.2:8766/setup", output.getvalue())
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(self.request("GET", "/api/session")[0], 200)

    def test_unexpected_application_errors_keep_diagnostics(self):
        from unittest.mock import patch, Mock
        with patch.object(self.server, "finish_request", side_effect=ValueError("unexpected bug")):
            with patch("http.server.ThreadingHTTPServer.handle_error") as diagnostics:
                self.server.process_request_thread(Mock(), ("127.0.0.1", 1234))
        diagnostics.assert_called_once()

    def test_real_tls_rejection_then_trusted_location_lookup(self):
        from unittest.mock import patch
        certs = DATA / "certs"
        if not all((certs / name).exists() for name in ("server.pem", "server-key.pem", "rootCA.pem")):
            self.skipTest("Run the launcher once to generate local HTTPS certificates")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certs / "server.pem", certs / "server-key.pem")
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True, do_handshake_on_connect=False)
        self.server.secure = True
        noticed = threading.Event()
        output, errors = io.StringIO(), io.StringIO()
        original_print = print
        def capture_note(*args, **kwargs):
            original_print(*args, **kwargs)
            if args and "needs certificate trust setup" in str(args[0]):
                noticed.set()
        with redirect_stdout(output), redirect_stderr(errors), patch("builtins.print", side_effect=capture_note):
            # This isolated client has no trusted CAs; verification stays enabled.
            untrusted = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            for _ in range(2):
                connection = http.client.HTTPSConnection(*self.server.server_address, context=untrusted, timeout=5)
                try:
                    with self.assertRaises(ssl.SSLCertVerificationError):
                        connection.request("GET", "/")
                finally:
                    connection.close()
            self.assertTrue(noticed.wait(3), "certificate rejection should show one friendly setup note")
            trusted = ssl.create_default_context(cafile=certs / "rootCA.pem")
            connection = http.client.HTTPSConnection(*self.server.server_address, context=trusted, timeout=5)
            try:
                connection.request("POST", "/api/scans", json.dumps({
                    "id": "trusted-tls", "text": "001234567890", "format": "Code128"}), {
                    "Authorization": "Bearer test-token", "Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["lookup"]["locations"], ["L1-1A2-3", "L2-2B4-5"])
            finally:
                connection.close()
        self.assertEqual(output.getvalue().count("needs certificate trust setup"), 1)
        self.assertEqual(errors.getvalue(), "")

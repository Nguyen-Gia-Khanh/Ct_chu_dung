"""Exercise the actual HTTP receiver without touching warehouse data."""

import http.client
import json
import threading
import io
import ssl
from contextlib import closing, redirect_stdout, redirect_stderr

from barcode_web.server import ScanStore, ScannerServer, load_token, phone_address, DATA
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
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode() if payload is not None else None
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

    def test_receiver_shows_latest_100_scans_and_log_keeps_all(self):
        for index in range(105):
            self.store.add({"id": f"scan-{index}", "text": f"PART{index}", "format": "Code 39"})
        shown = json.loads(self.request("GET", "/api/scans")[1])
        self.assertEqual(len(shown), 100)
        self.assertEqual((shown[0]["text"], shown[-1]["text"]), ("PART104", "PART5"))
        self.assertEqual(len(self.store.path.read_text(encoding="utf-8").splitlines()), 105)
        self.assertEqual(len(ScanStore(self.folder).recent()), 100, "a restart also loads only the latest 100")
        self.assertTrue(self.store.add({"id": "scan-0", "text": "PART0", "format": "Code 39"})["duplicate"],
                        "duplicate protection still covers scans no longer shown")

    def test_saved_phone_token_authenticates_after_server_restart(self):
        token = load_token(self.folder)
        self.server.token = token
        payload = {"id": "restart-1", "text": "001234567890", "format": "Code128"}
        self.assertEqual(self.request("POST", "/api/scans", payload, token=token)[0], 200)
        info, lookup = self.server.info, self.server.lookup
        self.close_server()
        self.server = ScannerServer(("127.0.0.1", 0), ScanStore(self.folder),
                                    load_token(self.folder), info, lookup=lookup)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.assertEqual(json.loads(self.request("GET", "/api/session")[1])["token"], token)
        status, body = self.request("POST", "/api/scans", payload, token=token)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["duplicate"])
        self.assertEqual(json.loads(body)["lookup"]["locations"], ["L1-1A2-3", "L2-2B4-5"])
        self.assertEqual(self.request("GET", "/api/scans", token="wrong")[0], 403)
        self.assertEqual(self.request("GET", "/session-token.txt", token=token)[0], 404)

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
        for path in ("/scan", "/receiver", "/setup", "/decoder-worker.js", "/robust39.js", "/icon.svg",
                     "/manifest.webmanifest", "/vendor/reader.js", "/vendor/zxing_reader.wasm"):
            self.assertEqual(self.request("GET", path)[0], 200, path)
        session = json.loads(self.request("GET", "/api/session")[1])
        self.assertEqual(session["token"], "test-token")
        self.assertEqual(session["untrusted_phones"], [])
        for path in ("/../data/warehouse_locations.db", "/certs/rootCA-key.pem", "/rootCA-key.pem", "/scans.jsonl",
                     "/server.py", "/worker.js", "/processing.js"):
            self.assertEqual(self.request("GET", path)[0], 404, path)

    def test_trust_check_qr_codes_and_trust_info(self):
        status, body = self.request("GET", "/trust-check", token="")
        self.assertEqual((status, body), (204, b""))
        self.server.info["https_port"] = 8765
        self.assertEqual(json.loads(self.request("GET", "/api/trust-info", token="")[1]), {"https_port": 8765})
        for target in ("phone", "setup"):
            status, body = self.request("GET", f"/api/qr?target={target}", token="")
            self.assertEqual(status, 200)
            self.assertIn(b"<svg viewBox=", body)
        self.assertEqual(self.request("GET", "/api/qr?target=token", token="")[0], 404)
        from unittest.mock import patch
        with patch("barcode_web.server.ipaddress.ip_address") as address:
            address.return_value.is_loopback = False
            self.assertEqual(self.request("GET", "/api/qr?target=phone", token="")[0], 403)
            self.assertEqual(self.request("GET", "/api/session", token="")[0], 403)

    def test_partial_barcode_resolves_only_a_unique_catalog_id(self):
        def resolve(pattern, **kwargs):
            status, body = self.request("POST", "/api/resolve", {"pattern": pattern}, **kwargs)
            return status, json.loads(body)
        self.assertEqual(resolve("0012345678?0"), (200, {"ok": True, "status": "unique", "product_id": "001234567890"}))
        self.assertEqual(resolve("ZZZZ?")[1]["status"], "none")
        for invalid in ("0012345678", "00?2?4?678", "AB?", "0012345678?0'--"):
            self.assertEqual(resolve(invalid)[0], 400, invalid)
        self.assertEqual(resolve("0012345678?0", token="wrong")[0], 403)
        self.assertEqual(self.request("POST", "/api/resolve", {"pattern": "0012?", "extra": 1})[0], 400)
        self.assertFalse(self.store.path.exists(), "resolving must not record a scan")

    def test_failed_save_is_not_acknowledged(self):
        from unittest.mock import patch
        with patch.object(self.store, "add", side_effect=OSError("disk full")):
            status, body = self.request("POST", "/api/scans", {"id": "scan-1", "text": "001", "format": "EAN13"})
        self.assertEqual(status, 503)
        self.assertIn("Could not save", json.loads(body)["error"])

    def test_frames_decode_without_saving_and_keep_auth_and_limits(self):
        import cv2
        import numpy as np
        import zxingcpp
        frame = np.asarray(zxingcpp.write_barcode(zxingcpp.BarcodeFormat.Code128, "001234567890", 660, 240))
        jpeg = cv2.imencode(".jpg", frame)[1].tobytes()
        status, body = self.request("POST", "/api/frames", jpeg, content_type="image/jpeg")
        self.assertEqual(status, 200)
        answer = json.loads(body)
        self.assertEqual(answer["results"][0]["text"], "001234567890")
        self.assertGreaterEqual(answer["milliseconds"], 0)
        self.assertFalse(self.store.path.exists(), "image processing must not persist frames or scans")
        self.assertEqual(self.request("POST", "/api/frames", jpeg, token="wrong", content_type="image/jpeg")[0], 403)
        self.assertEqual(self.request("POST", "/api/frames", {}, content_type="application/json")[0], 415)
        self.assertEqual(self.request("POST", "/api/frames", b"not jpeg", content_type="image/jpeg")[0], 400)
        self.assertEqual(self.request("POST", "/api/frames", b"x" * 1_000_001, content_type="image/jpeg")[0], 413)
        self.server.frame_slot.acquire()
        try:
            self.assertEqual(self.request("POST", "/api/frames", jpeg, content_type="image/jpeg")[0], 429)
        finally:
            self.server.frame_slot.release()
        # Invalid requests and busy responses must not strand the processing slot.
        self.assertEqual(self.request("POST", "/api/frames", jpeg, content_type="image/jpeg")[0], 200)

    def test_scan_returns_locations_and_retry_queries_current_database(self):
        import sqlite3
        payload = {"id": "location-1", "text": "001234567890", "format": "Code128"}
        status, body = self.request("POST", "/api/scans", payload)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["lookup"]["locations"], ["L1-1A2-3", "L2-2B4-5"])
        with closing(sqlite3.connect(self.server.lookup.path)) as connection, connection:
            connection.execute("DELETE FROM exception_placements WHERE product_id='001234567890'")
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

    def test_optional_cell_data_is_validated_current_and_not_saved(self):
        import sqlite3
        payload = {"id": "cells-1", "text": "001234567890", "format": "Code128"}
        for invalid in (None, "true", 1, [], {}):
            self.assertEqual(self.request("POST", "/api/scans", {
                **payload, "include_cell_contents": invalid})[0], 400)
        for flag in (False, True):
            status, body = self.request("POST", "/api/scans", {**payload, "include_cell_contents": flag})
            self.assertEqual(status, 200)
            self.assertEqual("cells" in json.loads(body)["lookup"], flag)
        self.assertNotIn("include_cell_contents", self.store.recent()[0])
        with closing(sqlite3.connect(self.server.lookup.path)) as connection, connection:
            connection.execute("DELETE FROM placements WHERE product_id='CAT001'")
        answer = json.loads(self.request("POST", "/api/scans", {**payload, "include_cell_contents": True})[1])
        self.assertTrue(answer["duplicate"])
        self.assertEqual(len(answer["lookup"]["cells"][1]["products"]), 1)
        self.assertEqual(len(self.store.recent()), 1)

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
        session = json.loads(self.request("GET", "/api/session")[1])
        self.assertEqual([phone["address"] for phone in session["untrusted_phones"]], ["192.168.1.19"],
                         "the receiver names each phone whose browser rejected the certificate")
        self.server.alerts.clear("192.168.1.19")
        self.assertEqual(json.loads(self.request("GET", "/api/session")[1])["untrusted_phones"], [])

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


class PersistentScannerLinkTests(WorkspaceTestCase):
    def test_token_is_saved_reused_and_can_be_reset(self):
        folder = self.folder / "scanner"
        token = load_token(folder)
        self.assertRegex(token, r"^[A-Za-z0-9_-]{32}$")
        path = folder / "session-token.txt"
        self.assertEqual(path.read_text(encoding="ascii"), token)
        self.assertEqual(load_token(folder), token)
        path.unlink()
        self.assertNotEqual(load_token(folder), token)

    def test_invalid_saved_tokens_fail_without_silently_changing_the_link(self):
        path = self.folder / "session-token.txt"
        for invalid in ("", "short", "a" * 32 + "\nextra", "a" * 31 + "!"):
            path.write_text(invalid, encoding="ascii")
            with self.assertRaisesRegex(ValueError, "Invalid scanner token"):
                load_token(self.folder)
            self.assertEqual(path.read_text(encoding="ascii"), invalid)

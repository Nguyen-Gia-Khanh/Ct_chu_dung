"""Isolated Chrome fake-camera check. No real camera, CA trust, or live database."""

import json
from pathlib import Path
import subprocess
import threading

from playwright.sync_api import sync_playwright

from barcode_web.server import ScanStore, ScannerServer
from barcode_web.lookup import WarehouseLookup
from tests.test_barcode_lookup import create_test_warehouse
from tests.support import WorkspaceTestCase


class BarcodeBrowserTest(WorkspaceTestCase):
    def test_fake_camera_decodes_sends_and_stops_at_phone_sizes(self):
        fixtures = subprocess.check_output([
            "node", "-e",
            "const f=require('./tests/test_barcode_web.js');const r={};"
            "for(const n of ['code128','qr']){const i=f[n]();"
            "r[n]={width:i.width,height:i.height,data:Array.from(i.data)};}"
            "process.stdout.write(JSON.stringify(r));",
        ], cwd=Path(__file__).resolve().parents[1], text=True)
        store = ScanStore(self.folder)
        server = ScannerServer(("127.0.0.1", 0), store, "browser-test", {
            "phone_urls": ["https://192.168.1.2:8765/#browser-test"],
            "setup_urls": ["http://192.168.1.2:8766/setup"],
        }, lookup=WarehouseLookup(create_test_warehouse(self.folder / "warehouse.db")))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        preview = Path(__file__).resolve().parents[1] / "tmp/barcode-web-preview"
        preview.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            self.addCleanup(lambda: browser.close() if browser.is_connected() else None)
            for width, height in [(393, 851), (375, 812)]:
                page = browser.new_page(viewport={"width": width, "height": height})
                errors = []
                uploaded_frames = []
                requested_workers = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: requested_workers.append(request.url) if "/worker.js" in request.url else None)
                def frame_upload(route):
                    uploaded_frames.append(route.request.post_data_buffer)
                    if width == 393 and len(uploaded_frames) == 1:
                        route.abort()
                    else:
                        route.continue_()
                page.route("**/api/frames", frame_upload)
                page.add_init_script("""
                    const fixtures = FIXTURES;
                    const source = document.createElement('canvas');
                    source.width = 1280; source.height = 720;
                    const ctx = source.getContext('2d');
                    window.fakeLabel = 'code128';
                    function draw() {
                      ctx.fillStyle = 'white'; ctx.fillRect(0, 0, 1280, 720);
                      if (fixtures[window.fakeLabel]) {
                        const f = fixtures[window.fakeLabel];
                        ctx.putImageData(new ImageData(new Uint8ClampedArray(f.data), f.width, f.height),
                                         (1280 - f.width) / 2, (720 - f.height) / 2);
                      }
                      requestAnimationFrame(draw);
                    }
                    draw();
                    navigator.mediaDevices.getUserMedia = async () => {
                      window.fakeStream = source.captureStream(30);
                      return window.fakeStream;
                    };
                """.replace("FIXTURES", fixtures))
                page.goto(base + "/scan#browser-test")
                cell_option = page.get_by_role("checkbox", name="Include cell contents")
                self.assertFalse(cell_option.is_checked())
                if width == 393:
                    cell_option.check()
                    attempts = []
                    def fail_first_post(route):
                        if route.request.method == "POST":
                            attempts.append(route.request.post_data_json)
                            if len(attempts) == 1:
                                route.abort()
                                return
                        route.continue_()
                    page.route("**/api/scans", fail_first_post)
                page.get_by_role("button", name="Start camera").click()
                if width == 393:
                    page.get_by_role("button", name="Retry sending").wait_for(state="visible")
                    self.assertFalse(store.recent(), "failed network delivery cannot be acknowledged")
                    page.get_by_role("button", name="Retry sending").click()
                page.wait_for_function("document.querySelector('#delivery').textContent === 'Received by laptop.'")
                if width == 393:
                    self.assertEqual(attempts[0], attempts[1], "retry must reuse the delivery ID and text")
                self.assertEqual(page.locator("#result").inner_text(), "001234567890")
                self.assertTrue(uploaded_frames)
                self.assertTrue(all(frame.startswith(b"\xff\xd8") for frame in uploaded_frames))
                self.assertFalse(requested_workers, "the phone must not load its old WASM decoding worker")
                self.assertIn("00123-456-7890", page.locator("#product").inner_text())
                self.assertEqual(page.locator("#locations").inner_text(), "L1-1A2-3\nL2-2B4-5")
                if width == 393:
                    self.assertTrue(attempts[0]["include_cell_contents"])
                    self.assertEqual(page.locator("#cells caption").all_text_contents(), ["L1-1A2-3", "L2-2B4-5"])
                    self.assertEqual(page.locator("#cells tbody tr").count(), 3)
                    self.assertIn("CAT-001", page.locator("#cells").inner_text())
                    self.assertIn("Catalog exception", page.locator("#cells").inner_text())
                else:
                    self.assertTrue(page.locator("#cells").is_hidden())
                self.assertEqual(page.evaluate("location.hash"), "")
                page.wait_for_timeout(2500)
                self.assertEqual(len(store.recent()), 1 if width == 393 else 3)
                self.assertEqual(page.evaluate("document.body.scrollWidth <= innerWidth"), True)
                print(f"Chrome {width}x{height}: {page.locator('#rate').inner_text()}")
                page.screenshot(path=str(preview / f"scanner-{width}.png"), full_page=True)
                cell_option.uncheck()
                self.assertTrue(page.locator("#cells").is_hidden())
                self.assertEqual(page.locator("#cells table").count(), 0)
                page.evaluate("window.fakeLabel = 'qr'")
                page.wait_for_function("document.querySelector('#result').textContent === 'warehouse-test-001'")
                page.wait_for_function("document.querySelector('#delivery').textContent === 'Received by laptop.'")
                self.assertEqual(store.recent()[0]["text"], "warehouse-test-001")
                self.assertEqual(page.locator("#locations").inner_text(), "Barcode not found in the warehouse.")
                self.assertTrue(page.locator("#cells").is_hidden())
                page.get_by_role("button", name="Stop", exact=True).click()
                frame_count = len(uploaded_frames)
                page.wait_for_timeout(250)
                self.assertEqual(len(uploaded_frames), frame_count, "stopping must halt frame uploads")
                self.assertEqual(page.evaluate("window.fakeStream.getTracks().every(t => t.readyState === 'ended')"), True)
                self.assertTrue(page.get_by_role("button", name="Start camera").is_enabled())
                self.assertFalse(errors, errors)
                page.close()
            receiver = browser.new_page(viewport={"width": 1000, "height": 760})
            receiver.goto(base + "/receiver")
            receiver.wait_for_function("document.querySelector('#scans').children.length === 4")
            self.assertIn("warehouse-test-001", receiver.locator("#scans").inner_text())
            receiver.screenshot(path=str(preview / "receiver.png"))
            receiver.close()
            browser.close()

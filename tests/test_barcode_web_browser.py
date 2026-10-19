"""Isolated Chrome fake-camera check. No real camera, CA trust, or live database."""

import json
from pathlib import Path
import subprocess
import threading

from playwright.sync_api import sync_playwright

from barcode_web.server import ScanStore, ScannerServer, load_token
from barcode_web.lookup import WarehouseLookup
from tests.test_barcode_lookup import create_test_warehouse
from tests.support import WorkspaceTestCase


class BarcodeBrowserTest(WorkspaceTestCase):
    def test_compact_preview_preserves_original_decode_pixels(self):
        server = ScannerServer(("127.0.0.1", 0), ScanStore(self.folder), "crop-test", {})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/scan#crop-test"
        with sync_playwright() as playwright:
            with playwright.chromium.launch(channel="chrome", headless=True) as browser:
                for viewport in [(393, 851), (320, 568), (393, 600), (851, 393)]:
                    for sensor in [(1920, 1080), (1080, 1920)]:
                        with self.subTest(viewport=viewport, sensor=sensor):
                            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
                            page.goto(url)
                            page.evaluate("""async ([width, height]) => {
                                const source = document.createElement('canvas');
                                source.width = width; source.height = height;
                                const ctx = source.getContext('2d');
                                const gradient = ctx.createLinearGradient(0, 0, width, height);
                                gradient.addColorStop(0, 'red'); gradient.addColorStop(1, 'blue');
                                ctx.fillStyle = gradient; ctx.fillRect(0, 0, width, height);
                                ctx.fillStyle = 'white';
                                for (let x = 0; x < width; x += 37) ctx.fillRect(x, 0, 9, height);
                                video.srcObject = source.captureStream(1);
                                await video.play();
                            }""", sensor)
                            snapshot = """() => {
                                const crop = windowCrop();
                                const pixels = (canvas, context, maxWidth) => {
                                    draw(canvas, context, crop, maxWidth);
                                    const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
                                    let hash = 2166136261;
                                    for (const byte of data) hash = Math.imul(hash ^ byte, 16777619);
                                    return [canvas.width, canvas.height, hash];
                                };
                                return {crop, phone: pixels(phoneCanvas, phoneContext, MAX_PHONE_WIDTH),
                                    laptop: pixels(laptopCanvas, laptopContext, MAX_UPLOAD_WIDTH)};
                            }"""
                            compact = page.evaluate(snapshot)
                            camera = page.locator(".camera").bounding_box()
                            guide = page.locator("#window").bounding_box()
                            self.assertGreater(camera["height"], 0)
                            self.assertGreaterEqual(guide["y"], camera["y"])
                            self.assertLessEqual(guide["y"] + guide["height"], camera["y"] + camera["height"])

                            # Recreate the camera markup/CSS before the compact-layout change.
                            page.evaluate("""() => {
                                const inner = document.querySelector('.camera-view');
                                inner.replaceWith(...inner.childNodes);
                            }""")
                            page.add_style_tag(content="""
                                .camera { aspect-ratio: 4 / 3; max-height: 42dvh; }
                                @media (orientation: landscape) and (max-height: 520px) {
                                    .camera { aspect-ratio: auto; max-height: none; }
                                }
                            """)
                            original = page.evaluate(snapshot)
                            for key, value in original["crop"].items():
                                self.assertAlmostEqual(compact["crop"][key], value, places=7)
                            self.assertEqual(compact["phone"], original["phone"])
                            self.assertEqual(compact["laptop"], original["laptop"])
                            if viewport[0] < viewport[1]:
                                self.assertLess(camera["height"], page.locator(".camera").bounding_box()["height"])
                            page.evaluate("video.srcObject.getTracks().forEach(track => track.stop())")
                            page.close()

    def test_phone_access_survives_server_restart_and_restored_tab(self):
        token = load_token(self.folder)
        info = {"phone_urls": [], "setup_urls": []}
        server = ScannerServer(("127.0.0.1", 0), ScanStore(self.folder), token, info)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def close_server():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.addCleanup(close_server)
        address = server.server_address
        url = f"http://127.0.0.1:{server.server_port}/scan"
        pending = {"id": "restored-tab", "text": "001234567890", "format": "Code128"}
        with sync_playwright() as playwright:
            with playwright.chromium.launch(channel="chrome", headless=True) as browser:
                context = browser.new_context()
                page = context.new_page()
                page.goto(f"{url}#{token}")
                page.evaluate("scan => sessionStorage.setItem('pending-scan', JSON.stringify(scan))", pending)
                page.reload()
                self.assertEqual(page.url, url, "access key stays out of the displayed URL")
                close_server()
                page.get_by_role("button", name="Retry sending").click()
                page.wait_for_function("document.querySelector('#delivery').textContent.startsWith('Not received:')")
                server = ScannerServer(address, ScanStore(self.folder), load_token(self.folder), info)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                page.get_by_role("button", name="Retry sending").click()
                page.wait_for_function("document.querySelector('#delivery').textContent === 'Received by laptop.'")
                page.reload()
                self.assertEqual(page.evaluate("token"), token)

                # A restored mobile tab can retain its URL/local storage but lose session storage.
                saved_state = context.storage_state()
                context.close()
                context = browser.new_context(storage_state=saved_state)
                page = context.new_page()
                page.goto(url)
                self.assertIsNone(page.evaluate("sessionStorage.getItem('scanner-token')"))
                self.assertEqual(page.evaluate("token"), token)
                self.assertEqual(page.evaluate("""async () => (await fetch('/api/scans', {
                    headers: {Authorization: `Bearer ${token}`}
                })).status"""), 200)
                page.evaluate("scan => sessionStorage.setItem('pending-scan', JSON.stringify(scan))", pending)
                page.reload()
                page.get_by_role("button", name="Retry sending").click()
                page.wait_for_function("document.querySelector('#delivery').textContent === 'Received by laptop.'")
                self.assertEqual(len(server.store.recent()), 1, "retry must not duplicate the scan")

                # Upgrade an old page whose access key exists only in session storage.
                page.evaluate("""key => {
                    localStorage.removeItem('scanner-token');
                    sessionStorage.setItem('scanner-token', key);
                }""", token)
                page.reload()
                self.assertEqual(page.evaluate("localStorage.getItem('scanner-token')"), token)

                # Temporary server failures must not tell the phone to replace its link.
                page.route("**/api/scans", lambda route: route.fulfill(status=503, body="Unavailable"))
                page.get_by_role("button", name="Start camera").click()
                page.wait_for_function("document.querySelector('#status').textContent.startsWith('Laptop is unavailable.')")
                page.unroute("**/api/scans")

                # Explicitly opening a replacement link overrides any remembered key.
                page.goto(url + "#replacement-token")
                page.wait_for_function("token === 'replacement-token'")
                self.assertEqual(page.evaluate("token"), "replacement-token")
                self.assertEqual(page.evaluate("localStorage.getItem('scanner-token')"), "replacement-token")
                self.assertEqual(page.url, url)
                page.get_by_role("button", name="Start camera").click()
                page.wait_for_function("document.querySelector('#status').textContent.startsWith('Phone link expired.')")
                context.close()

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
                # 393: frames are decoded on the phone. 375: the phone decoder cannot load, so the
                # page falls back to uploading frames to the laptop (and retries a failed upload).
                on_phone = width == 393
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: requested_workers.append(request.url)
                        if "/decoder-worker.js" in request.url else None)
                if not on_phone:
                    page.route("**/decoder-worker.js", lambda route: route.fulfill(status=404, body="blocked"))
                def frame_upload(route):
                    uploaded_frames.append(route.request.post_data_buffer)
                    if not on_phone and len(uploaded_frames) == 1:
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
                if on_phone:
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
                if on_phone:
                    page.get_by_role("button", name="Retry sending").wait_for(state="visible")
                    self.assertFalse(store.recent(), "failed network delivery cannot be acknowledged")
                    page.get_by_role("button", name="Retry sending").click()
                page.wait_for_function("document.querySelector('#delivery').textContent === 'Received by laptop.'")
                if on_phone:
                    self.assertEqual(attempts[0], attempts[1], "retry must reuse the delivery ID and text")
                self.assertEqual(page.locator("#result").inner_text(), "001234567890")
                self.assertTrue(requested_workers, "the phone decoder worker is loaded")
                if on_phone:
                    self.assertFalse(uploaded_frames, "decoded on the phone: no camera frames leave it")
                    self.assertEqual(page.locator("#link-state").inner_text(), "Scanning on phone")
                else:
                    self.assertGreaterEqual(len(uploaded_frames), 2, "first upload failed, a later one decoded")
                    self.assertTrue(all(frame.startswith(b"\xff\xd8") for frame in uploaded_frames))
                    self.assertEqual(page.locator("#link-state").inner_text(), "Scanning on laptop")
                self.assertEqual(page.locator("#badge").inner_text(), "Found")
                self.assertIn("001234567890", page.locator("#product").inner_text())
                self.assertEqual(page.locator("#locations").inner_text(), "L1-1A2-3\nL2-2B4-5")
                self.assertEqual(page.locator("#locations .loc").count(), 2)
                if on_phone:
                    self.assertTrue(attempts[0]["include_cell_contents"])
                    self.assertEqual(page.locator("#cells caption").all_text_contents(), ["L1-1A2-3", "L2-2B4-5"])
                    self.assertEqual(page.locator("#cells tbody tr").count(), 3)
                    self.assertIn("CAT001", page.locator("#cells").inner_text())
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

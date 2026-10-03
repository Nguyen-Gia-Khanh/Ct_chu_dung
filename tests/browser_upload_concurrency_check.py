"""Opt-in real Chrome check: python -m tests.browser_upload_concurrency_check.

Uses the debugging Chrome on port 9222 and temporary localhost pages only.
Delays response bodies, switches tabs, and never contacts the KiotViet API.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Lock, Thread
from time import monotonic, sleep
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from mapper.features.web_upload import LocationUpdate, WebsiteUploader


def main():
    starts, responses, completed, errors = {}, {}, [], []
    state_lock, done = Lock(), Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            body = b"""<kv-product-form><form><div><div></div><div>
            <a></a><a></a><a></a><a id="save" href="#">Save</a>
            </div></div></form></kv-product-form><script>
            document.querySelector('#save').onclick = () => {
              fetch('/api/products/photo', {method:'POST', body:JSON.stringify(window.product)});
              // Deliberately close early: DOM closure must NOT complete the job.
              document.querySelector('kv-product-form').remove();
            };</script>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            product = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            sku = product['Code']
            with state_lock:
                starts[sku] = monotonic()
            body = json.dumps({'Data': product}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.flush()  # Headers arrive before the delayed response body.
            sleep(3 if sku == 'P0' else 0.15)
            with state_lock:
                responses[sku] = monotonic()
            self.wfile.write(body)
            self.wfile.flush()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}/'

    def new_tab(uploader):
        uploader.page = uploader.browser.contexts[0].new_page()
        uploader._prepare_page()

    def modify(uploader, product, progress, *, save):
        uploader.page.goto(url, wait_until='domcontentloaded')
        uploader._kiotviet_id = str(int(product.product_id[1:]) + 1)
        uploader.page.evaluate('product => window.product = product',
                              {'Id': int(uploader._kiotviet_id), 'Code': product.product_id})
        return uploader._save_product(product, progress, location_only=True)

    def item_done(sku):
        with state_lock:
            assert sku in responses, f'{sku} completed before its response body'
            completed.append(sku)

    def batch():
        try:
            with patch.object(WebsiteUploader, '_choose_tab'), \
                    patch.object(WebsiteUploader, '_new_upload_tab', new_tab), \
                    patch.object(WebsiteUploader, 'modify_location', modify):
                WebsiteUploader(store_url='https://test.kiotviet.vn/man/#/Products').run_batch(
                    [LocationUpdate(f'P{i}', 'A') for i in range(6)],
                    lambda _text: None, item_done, location_only=True, save=True, tab_count=2)
        except Exception as error:
            errors.append(error)
        finally:
            done.set()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp('http://127.0.0.1:9222')
            observer = browser.contexts[0].new_page()
            observer.goto('about:blank')
            worker = Thread(target=batch, daemon=True)
            worker.start()
            deadline = monotonic() + 30
            switches = 0
            try:
                while not done.is_set() and monotonic() < deadline:
                    observer.bring_to_front()
                    switches += 1
                    observer.wait_for_timeout(100)
                assert done.is_set(), 'Batch did not finish'
                worker.join(timeout=1)
                assert not errors, str(errors)
                assert sorted(completed) == [f'P{i}' for i in range(6)]
                assert starts['P2'] < responses['P0'], 'Free tab waited for the slow tab'
                assert starts['P2'] >= responses['P1'], 'Next job fired before Save response body'
                print(f'PASS: 6 jobs, 2 worker tabs, {switches} foreground switches; '
                      'next SKU started while slow response was pending. Localhost only.')
            finally:
                observer.close()
                for context in browser.contexts:
                    for page in context.pages:
                        if page.url == url:
                            page.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()

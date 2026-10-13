# Phone barcode scanner

This is a standalone LAN website. It sends decoded barcode **text** to the
laptop, queries the existing warehouse database read-only, and returns the
product name, stored ID, and all saved locations to the phone. No Docker,
Node server, or additional Python packages are required. It uses the project's
existing `.venv` and Python's standard library.

## Start and stop

1. Connect laptop and phone to the same local network.
2. Double-click **`start_barcode_server.cmd`** at the repository root. If the
   repository `.venv` is missing, run the existing `setup_venv.cmd` first.
3. The laptop receiver opens at `http://localhost:8766/receiver`. It shows one
   phone link and its first-use certificate setup link. Windows prefers an
   active Private network with a gateway, prioritizing the interface selected
   with `configure_network.ps1`. Virtual adapters are not advertised when a
   suitable Private network is available. Other platforms/fallbacks use the
   default route. To override selection, pass `--lan-ip 192.168.1.13` with an
   address currently assigned to the laptop.
4. On each phone, open the HTTP certificate setup link once and follow the
   Android/Chrome or iPhone/Safari instructions. Then open the corresponding
   **HTTPS phone link**, press **Start camera**, and allow camera access.
5. Scanned content appears in the phone, the laptop receiver, the terminal,
   and `data/barcode_web/scans.jsonl`. The receiver displays the last 200 scans;
   the log keeps older scans. Barcode text is preserved, including leading
   zeros, spaces and separators. The phone also shows the product and its
   locations, or a clear unknown/unassigned/ambiguous result.

**Close the server's terminal window/tab, or press Ctrl+C, to stop both servers.**
Closing the receiver's browser tab does not stop the server. There are no
background services, containers, scheduled tasks, or automatic startup.
Only one server can own its ports: close the old launcher before starting again.

The first launch downloads the pinned mkcert 1.4.4 Windows x64 executable and
verifies its SHA-256 before running it to create a local CA and HTTPS certificate.
It does **not** install a trusted root in Windows. The laptop receiver works
over localhost HTTP and does not require certificate installation. If you want
to test the scanner on the laptop itself, open
`http://localhost:8766/scan#TOKEN`, replacing TOKEN with the fragment from a
current phone link. Localhost is allowed to use the camera without HTTPS.
Subsequent launches need no internet; JavaScript and the decoder's WASM are
served locally. Use Chrome or Safari directly, rather than a messaging app's
embedded browser.

## Phone certificates and network access

Camera access from `http://192.168...` is blocked by browsers. The setup page
downloads **only** the public `rootCA.cer`; no private keys are served. Merely
bypassing an HTTPS warning is not a substitute for trusting the CA.

- **Android:** Settings → install a certificate → **CA certificate**. Select
  the downloaded certificate. The exact Settings path varies by manufacturer.
- **iPhone:** use Safari to download; install the profile under Settings →
  General → VPN & Device Management. Then enable full trust under General →
  About → Certificate Trust Settings.

Only trust the certificate from your own laptop. Keep
`data/barcode_web/certs/rootCA-key.pem` and `server-key.pem` private. A trusted
CA can issue other certificates accepted by that device. Remove the phone's
CA/profile in Settings when it is no longer needed. Keys, executable, and logs
are under the repository's already ignored `data/` directory.

If Windows asks about Python network access, allow it on your **private**
network. If the phone cannot even open the HTTP setup link, check Windows
Firewall and whether the Wi-Fi isolates clients. The required TCP ports are
8765 (HTTPS scanning) and 8766 (certificate setup/receiver). No firewall rules
are changed automatically. Do not forward these ports onto the public internet.

If this trusted Wi-Fi is marked Public and Public inbound rules are disabled,
an administrator can run the opt-in helper (it enables existing Private-network
rules on the selected network and adds the scanner's local-subnet rule):

```powershell
powershell -NoProfile -File .\barcode_web\configure_network.ps1 -InterfaceAlias 'Wi-Fi 4'
```

Run that command from an **administrator** PowerShell window. Its result is
written to `data/barcode_web/network-setup.json`. It never installs certificates.

If the laptop's LAN IP changes, restart the launcher: it regenerates the server
certificate using the same local CA. The phone does not need to reinstall that
CA. Phone session links change on every server start, so use the new link.
Pending scans survive a page reload in the same phone tab; reopen the current
link in that tab if the server was restarted, then retry sending.

Optional command-line arguments:

```powershell
.\start_barcode_server.cmd --no-browser --port 8765 --setup-port 8766
# Select another existing database explicitly:
.\start_barcode_server.cmd --db "C:\path\warehouse_locations.db"
```

## Warehouse lookup

The default database follows the desktop app's `default_database_path()` rules,
normally `data/warehouse_locations.db`. The selected path is printed at startup.
SQLite opens it with `mode=ro`: no creation, migrations, inventory updates, or
assignment changes occur. Missing databases fail with a startup message.

The raw barcode remains unchanged in the scan log. Lookup trims surrounding
whitespace and accepts exact stored IDs or their dashless spellings, ignoring
ASCII case. It reuses `exact_product_search_id` to prefer a literal match and
reject ambiguous aliases instead of guessing. Matches include working products,
catalog-only products, and staged exception products. Product names and all
distinct regular/exception locations use the existing `find_product_locations`
query. Saved location labels are returned as stored, one per line on the phone.

Each scan/retry queries current SQLite data; assignments saved in the desktop
app become visible on the next lookup without restarting the web server.
Unknown products and known products without a saved location are separate
results. A database failure keeps the scan pending on the phone for retry.

## Frame processing

The phone requests a rear camera preview at 30 FPS, with a 15 FPS minimum.
Scanning targets **15 selected frames per second**, independently of preview.
Frames are cropped to the aiming box, scaled uniformly to at most 960 × 480,
and transferred to a phone-side Web Worker. It converts to grayscale, applies
a gentle sharpening convolution on alternate frames when enabled, and decodes
with ZXing-C++ WASM. Unsharpened frames remain in the cycle because sharpening
can damage some barcodes. Rotation/detection is handled by ZXing; there is no
custom perspective-rectification stage or claim to recover blurred detail.

There is at most **one frame in flight**. Slower phones skip processing frames
instead of building a queue. The measured scan rate and processing time are
visible; a 15 FPS target is not a hardware guarantee. The preview remains a
normal video element. The camera stops when the tab becomes hidden and needs
an explicit restart when you return.

Supported decoder selection: linear barcodes (including Code 128, Code 39,
EAN/UPC and ITF), QR and Data Matrix. Keep the whole code plus its blank margins
inside the box. Hold still and avoid glare. Move a barcode out for about 1.2
seconds before deliberately scanning the same value again.

Only `{id, text, format}` JSON is sent to the laptop. No frames, photos, video,
or processing results are uploaded. A failed delivery stays pending on the
phone and blocks accepting another barcode until retried. Retries reuse the
same ID; the server suppresses duplicate delivery IDs in its last 2,000 records.
Each request uses the current session token from the phone-link fragment.

## Source navigation and checks

- `server.py`: certificate generation, two foreground HTTP servers, bounded
  text-only API, local receiver session, JSONL recording and shutdown.
- `lookup.py`: read-only SQLite connection, exact/dashless matching, and reuse
  of the desktop persistence lookup for regular and exception locations.
- `static/scanner.js`: camera lifecycle, crop/scale, 15 FPS scheduling, one-frame
  backpressure, duplicate suppression and acknowledged/retryable delivery.
- `static/worker.js` and `processing.js`: phone-side decoder and convolution.
- `static/index.html`, `receiver.html`, `setup.html`, `style.css`: small scanner,
  laptop receiver and phone certificate instructions.
- `static/vendor/`: unmodified zxing-wasm 3.1.5 reader assets and licenses. npm
  archive integrity verified before extraction; no CDN requests at runtime.
- `../tests/test_barcode_web.py`: live HTTP validation, persistence, retries,
  unauthorized requests and private-key/path access checks.
- `../tests/test_barcode_lookup.py`: exact/dashless IDs, alias collisions,
  catalog/staged exceptions, multiple locations and enforced read-only access.
- `../tests/test_barcode_web.js`: bundled WASM/worker decoding of synthetic
  Code 128 and QR images, filter correctness, and 15-frame workload timing.

Run from the repository root:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_barcode_web tests.test_barcode_lookup
node tests/test_barcode_web.js
& '.\.venv\Scripts\python.exe' -m unittest tests.test_barcode_web_browser
```

Browser camera performance and focus must still be tested on real Android and
iPhone hardware. Synthetic/local checks cannot establish phone FPS or LAN
firewall reachability.

The optional browser check needs the already installed Playwright package,
Node, and Chrome. It uses fake video in an isolated headless Chrome process
at Android/iPhone viewport sizes; it is not a real Safari or phone camera test.

Upstream references: [ZXing WASM](https://github.com/Sec-ant/zxing-wasm),
[mkcert mobile trust instructions](https://github.com/FiloSottile/mkcert#mobile-devices).

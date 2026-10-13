# Phone barcode scanner

This is a standalone LAN website. The phone sends camera frames to the laptop
for image processing and decoding. The laptop queries the existing warehouse
database read-only and returns the product name, stored ID, and all saved
locations to the phone. It uses the project's existing `.venv`, OpenCV and
native ZXing. Run `setup_venv.cmd` after updating dependencies, then restart
the scanner launcher and reload the phone page.

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

Normal browser disconnects and abandoned connections are quiet. If a phone
rejects the HTTPS certificate, the terminal shows one short setup instruction
at most once per minute instead of repeated tracebacks. This message does not
mean the server stopped; the phone must still install and trust the local CA
if its scanner page cannot open. Unexpected application faults retain their
tracebacks for diagnosis.

The first launch downloads the pinned mkcert 1.4.4 Windows x64 executable and
verifies its SHA-256 before running it to create a local CA and HTTPS certificate.
It does **not** install a trusted root in Windows. The laptop receiver works
over localhost HTTP and does not require certificate installation. If you want
to test the scanner on the laptop itself, open
`http://localhost:8766/scan#TOKEN`, replacing TOKEN with the fragment from a
current phone link. Localhost is allowed to use the camera without HTTPS.
Subsequent launches need no internet; JavaScript is served locally and decoding
runs on the laptop. Use Chrome or Safari directly, rather than a messaging app's
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

Enable **Include cell contents** on the phone before scanning to request a table
for every saved location. Each table lists all barcodes in that cell, their
product names, and stock, including catalog-only and staged exceptions. Each
barcode appears once per cell; quantities across regular/exception placements
in the same cell are summed, with unknown stock shown as a dash. The checkbox
starts unchecked. When unchecked, the server skips cell-content queries and
returns only the normal product/location lookup. Changing the checkbox applies
to the next scan or retry; it clears any previous cell tables immediately.
Cell data and this request option are not saved in the scan log.

Each scan/retry queries current SQLite data; assignments saved in the desktop
app become visible on the next lookup without restarting the web server.
Unknown products and known products without a saved location are separate
results. A database failure keeps the scan pending on the phone for retry.

## Frame processing

The phone requests a rear camera preview at 30 FPS, with a 15 FPS minimum.
Scanning targets **15 selected frames per second**, independently of preview.
The whole camera view is scaled uniformly to at most 1280 × 720 and encoded
as JPEG at 92% quality. The phone sends it to authenticated `POST /api/frames`
over local HTTPS. Image processing and native ZXing decoding run on the laptop;
the current scanner page loads no Web Worker or WASM decoder.

The laptop tries the untouched view first. With **Enhance red labels** enabled,
it locates red ink in HSV and joins disconnected bars in a separate detection
mask. It tries up to three cropped regions, leaving margins for quiet zones,
then corrects a four-corner ink outline or deskews its enclosing rectangle.
It tries the green channel (red ink appears dark against white), a gentle
3 × 3 sharpening kernel, and Otsu thresholding as successive fallbacks. It also
processes the full view if red detection misses the label. Sharpening is only
a fallback because it can damage thin bars. Ink outlines approximate the label
plane; wrinkled plastic, glare and blurred detail still need a clearer image.

There is at most **one frame in flight per phone** and one concurrent decode
across phones. Slower capture, Wi-Fi or decoding skips frames rather than
building a queue. The measured scan rate and laptop processing time are
visible; a 15 FPS target is not a hardware guarantee. The preview remains a
normal video element. The camera stops when the tab becomes hidden and needs
an explicit restart when you return.

Supported decoder selection: linear barcodes (including Code 128, Code 39,
EAN/UPC and ITF), QR and Data Matrix. Keep the whole code plus its blank margins
inside the box. Hold still and avoid glare. Move a barcode out for about 1.2
seconds before deliberately scanning the same value again.

JPEG frames are processed in memory and discarded without logging. Frame byte
size and dimensions are bounded before native decoding. Only decoded
`{id, text, format}` JSON is saved through `/api/scans`. A failed delivery stays pending on the
phone and blocks accepting another barcode until retried. Retries reuse the
same ID; the server suppresses duplicate delivery IDs in its last 2,000 records.
Each request uses the current session token from the phone-link fragment.

## Source navigation and checks

- `server.py`: certificate generation, two foreground HTTP servers, bounded
  frame/text APIs, local receiver session, JSONL recording and shutdown.
- `processing.py`: JPEG validation, red-region cropping, perspective/angle
  correction, convolution/threshold fallbacks and native ZXing decoding.
- `lookup.py`: read-only SQLite connection, exact/dashless matching, and reuse
  of the desktop persistence lookup for regular and exception locations.
- `static/scanner.js`: camera lifecycle, JPEG upload, 15 FPS scheduling, one-frame
  backpressure, duplicate suppression and acknowledged/retryable delivery.
- `static/worker.js` and `processing.js`: legacy phone-side decoder and
  convolution, unused by the current scanner page.
- `static/index.html`, `receiver.html`, `setup.html`, `style.css`: small scanner,
  laptop receiver and phone certificate instructions.
- `static/vendor/`: unmodified zxing-wasm 3.1.5 reader assets and licenses. npm
  archive integrity verified before extraction; no CDN requests at runtime.
- `../tests/test_barcode_web.py`: live HTTP validation, persistence, retries,
  unauthorized requests and private-key/path access checks.
- `../tests/test_barcode_lookup.py`: exact/dashless IDs, alias collisions,
  catalog/staged exceptions, multiple locations and enforced read-only access.
- `../tests/test_barcode_processing.py`: generated red component labels on white
  packaging with black contents, rotation/perspective/low contrast, QR fallback,
  blank frames and rejection of invalid/oversized images.
- `../tests/test_barcode_web.js`: bundled WASM/worker decoding of synthetic
  Code 128 and QR images, filter correctness, and 15-frame workload timing.

Run from the repository root:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_barcode_processing tests.test_barcode_web tests.test_barcode_lookup
node tests/test_barcode_web.js
& '.\.venv\Scripts\python.exe' -m unittest tests.test_barcode_web_browser
```

Browser camera performance and focus must still be tested on real Android and
iPhone hardware. Synthetic/local checks cannot establish phone FPS or LAN
firewall reachability.

The optional browser check needs the already installed Playwright package,
Node, and Chrome. It uses fake video in an isolated headless Chrome process
at Android/iPhone viewport sizes; it is not a real Safari or phone camera test.

Upstream references: [ZXing Python](https://github.com/zxing-cpp/zxing-cpp/tree/master/wrappers/python),
[OpenCV filtering](https://docs.opencv.org/4.13.0/d4/d86/group__imgproc__filter.html),
[legacy ZXing WASM](https://github.com/Sec-ant/zxing-wasm),
[mkcert mobile trust instructions](https://github.com/FiloSottile/mkcert#mobile-devices).

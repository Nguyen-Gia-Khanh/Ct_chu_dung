# Phone barcode scanner

This is a standalone LAN website. **The phone decodes barcodes itself** and sends
only the decoded text to the laptop. The laptop queries the existing warehouse
database read-only and returns the product name, stored ID, and all saved
locations to the phone. The laptop's OpenCV/ZXing frame pipeline remains as a
fallback. It uses the project's existing `.venv`, OpenCV and native ZXing. Run
`setup_venv.cmd` after updating dependencies, then restart the scanner launcher
and reload the phone page.

## Start and stop

1. Connect laptop and phone to the same local network.
2. Double-click **`start_barcode_server.cmd`** at the repository root. If the
   repository `.venv` is missing, run the existing `setup_venv.cmd` first.
3. The laptop receiver opens at `http://localhost:8766/receiver`. It shows two
   QR codes: **1. Trust this laptop** (the phone setup page) and **2. Open the
   scanner** (the HTTPS phone link with its access key). Windows prefers an
   active Private network with a gateway, prioritizing the interface selected
   with `configure_network.ps1`. Virtual adapters are not advertised when a
   suitable Private network is available. Other platforms/fallbacks use the
   default route. To override selection, pass `--lan-ip 192.168.1.13` with an
   address currently assigned to the laptop.
4. On each phone, scan QR 1 once and follow its steps until its box turns green
   (see below). Then scan QR 2, press **Start camera**, and allow camera access.
   Add the scanner to the home screen to reopen it directly next time.
5. Scanned content appears in the phone, the laptop receiver, the terminal,
   and `data/barcode_web/scans.jsonl`. The receiver displays the last 200 scans;
   the log keeps older scans. Barcode text is preserved, including leading
   zeros, spaces and separators. The phone also shows the product and its
   locations, or a clear unknown/unassigned/ambiguous result.

**Close the server's terminal window/tab, or press Ctrl+C, to stop both servers.**
Closing the receiver's browser tab does not stop the server. There are no
background services, containers, scheduled tasks, or automatic startup.
Only one server can own its ports: close the old launcher before starting again.

To test the scanner on the laptop itself, use the receiver's **Open the scanner
here** link (`http://localhost:8766/scan#TOKEN`). Localhost may use the camera
without HTTPS, so it shows no certificate warning. Do not open the phone's
`https://192.168…` link on the laptop: Windows does not trust the local CA.

## Removing the browser certificate warning

Camera access from `http://192.168...` is blocked by browsers, so the scanner
uses HTTPS with a local certificate authority (CA) made by mkcert. A phone shows
"connection not private" **until that CA is installed and trusted**; clicking
through the warning is not the same as trusting it, which is why the warning
came back on every visit.

The setup page (`http://LAN-IP:8766/setup`) now checks trust live: it requests
`https://LAN-IP:8765/trust-check`, which only succeeds when the phone's browser
accepts the certificate. The box at the top turns green ("This phone trusts the
laptop") with an **Open scanner** button, or stays orange with the remaining
step. It rechecks every few seconds and when you return from Settings.

- **Android:** download the certificate (choose **Keep** if Chrome warns about
  an insecure download), then Settings → search **CA certificate** → Install
  anyway → pick the file. "VPN & app user certificate" and "Wi-Fi certificate"
  do **not** work for Chrome. Menu names vary by manufacturer.
- **iPhone:** use Safari to download; install the profile under Settings →
  General → VPN & Device Management. Then enable full trust under General →
  About → Certificate Trust Settings. Skipping full trust keeps the warning.

When a phone's browser rejects the certificate, the laptop receiver names that
phone ("Phone 192.168.1.40 does not trust this laptop yet") until it connects
successfully. The terminal still prints one short note at most once per minute.

The first launch downloads the pinned mkcert 1.4.4 Windows x64 executable and
verifies its SHA-256 before running it to create the CA and HTTPS certificate.
It does **not** install a trusted root in Windows. The setup page downloads
**only** the public `rootCA.cer`; no private keys are served. Only trust the
certificate from your own laptop. Keep `data/barcode_web/certs/rootCA-key.pem`
and `server-key.pem` private: a trusted CA can issue other certificates accepted
by that device. Remove the phone's CA/profile when it is no longer needed. Keys,
executable, and logs are under the repository's already ignored `data/` directory.

Normal browser disconnects and abandoned connections are quiet. Unexpected
application faults retain their tracebacks for diagnosis. Subsequent launches
need no internet: JavaScript, WASM and fonts are local (system fonts only).
Use Chrome or Safari directly, rather than a messaging app's embedded browser.

## Network access

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
CA. The phone link stays the same across server restarts while the laptop's LAN
IP and ports stay the same. The phone remembers its access key in this browser's
local storage, so restoring a tab, reopening its address, or the home-screen
icon does not require the full phone link again. If a tab has already lost that
key, scan the receiver's phone QR code once to save it. On later server restarts,
refresh the phone tab and press **Start camera**. Pending scans survive a reload
in the same tab; use **Retry sending**. Clearing this site's browser data or
using a new private browsing session requires opening the full phone link again.

The random access token is created once and saved in
`data/barcode_web/session-token.txt`, which is ignored by Git and is not served
by the website. To deliberately reset access, stop the server and delete only
that file, then restart and open the new phone link on each phone.

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
ASCII case. Matches include working products, catalog-only products, and staged
exception products. Product names and all distinct regular/exception locations
use the existing `find_product_locations` query. Saved location labels are
returned as stored and shown on the phone as yellow bin labels.

Enable **Cell contents** on the phone before scanning to request a table
for every saved location. Each table lists all barcodes in that cell, their
product names, and stock, including catalog-only and staged exceptions. Each
barcode appears once per cell; quantities across regular/exception placements
in the same cell are summed, with unknown stock shown as a dash. The toggle
starts off. When off, the server skips cell-content queries and returns only
the normal product/location lookup. Changing it applies to the next scan or
retry; it clears any previous cell tables immediately. Cell data and this
request option are not saved in the scan log.

Each scan/retry queries current SQLite data; assignments saved in the desktop
app become visible on the next lookup without restarting the web server.
Unknown products and known products without a saved location are separate
results. A database failure keeps the scan pending on the phone for retry.

**Catalog completion** (`POST /api/resolve`): when the phone has read a Code 39
label's full length but one or two characters stayed unreadable for half a
second, it sends a pattern such as `53205K?L640ZC`. The server answers with a
product only if **exactly one** catalog ID of that exact length matches every
read character; otherwise the phone keeps scanning. A completed read is shown
as "completed from catalog" and logged with format `Code 39 · catalog`.
At least four characters must be read; `%` and `_` are matched literally.

## Decoding

The scanner page shows a 4:3 camera preview with a **3:1 scan frame**; only the
frame's pixels are decoded. Each camera frame the decoder is free for is copied
at full resolution (up to 1920 px wide, no JPEG) to a Web Worker on the phone
(`static/decoder-worker.js`). One frame is in flight; others are skipped, so
slow phones drop frames instead of lagging. The worker tries, in order:

1. **Native `BarcodeDetector`** when the browser provides it (Android Chrome,
   backed by the platform's ML Kit engine). Not available in iPhone Safari.
   A native Code 39 read must repeat on two frames within 0.6 s.
2. **zxing-wasm 3.1.5** (already vendored) with `tryHarder` and two agreeing
   scanlines. The original frame is tried every other frame with all formats; in
   between, a light-flattened (horizontal closing + division, sharpened across
   bars) or local-threshold copy is tried for linear codes only. These mirror the
   laptop's "local contrast" and "local threshold" stages.
3. **Code 39 recovery** (`static/robust39.js`) for labels ZXing cannot read: see below.

The rectangle on the preview is an aiming hint from the decoder, not a
confirmation. A read flashes the frame green, vibrates, and beeps (speaker
button toggles the beep). Torch and zoom buttons appear when the phone's camera
exposes them; zoom gives the sensor's real detail when labels are small.

**Laptop fallback.** If the worker fails to load or keeps failing, or has not
become ready after 4 s, the page uploads JPEG frames to `POST /api/frames` at up
to 15 per second, exactly as before (`processing.py`, unchanged). While the
phone decodes, it also sends one frame every ~350 ms to the laptop as a second
opinion when it has seen a barcode-like pattern for 1.2 s without a read. The
**Mask** toggle still requests the laptop's thresholded diagnostic image. The
status pill says "Scanning on phone" or "Scanning on laptop".

### Code 39 recovery

The warehouse labels are Code 39, which has no check digit, so this module is
built to miss rather than misread:

- **Many scanlines.** Up to 48 lines across the frame, along the bars' estimated
  angle (handles tilt up to about 25°), read in both directions (upside-down labels).
- **Threshold-free edges.** Sub-pixel edges from intensity-gradient peaks relative
  to local contrast, so shadows, low contrast and glare edges do not need one
  global threshold.
- **Per-character normalisation.** Each 9-element character is classified by its
  own bar and space widths separately (robust to ink spread), then re-checked after
  correcting the stretch measured from its neighbours. Curved packaging and
  perspective compress characters smoothly, which this cancels; a character that
  changes under correction casts no vote.
- **Fragments and anchors.** A line interrupted by glare or missing ink still yields
  character runs. Runs touching the start or stop character with a quiet zone are
  anchors; the others are placed by measured pitch across the gap.
- **Voting across lines and frames.** Characters vote for slots counted from the
  start and from the stop, across a rolling ~1 s of frames, so the left half from
  one frame and the right half from another complete one code. The length comes
  from complete lines, or from aligning start- and stop-counted votes when no line
  sees both ends.
- **Acceptance.** Every character needs ≥2.5 weighted votes from **at least two
  frames** and a 2:1 margin, and start- and stop-counted votes must agree. In a
  600-trial random heavy-damage benchmark, accepting single-frame reads produced 2
  wrong codes; requiring two frames produced 0 with more correct reads.

Synthetic checks (in `tests/test_barcode_web.js`) cover blur and noise, tilt to 25°,
shadow, curved packaging with bowed bars, perspective, ink spread, low contrast,
2.5 px modules, upside-down labels, glare on some rows, and a missing chunk that
moves between frames. ZXing reads none of the moving-chunk frames; recovery
reads the code within a few frames. If three or more characters are hidden in
every frame, nothing is accepted. Code 128 labels and random bar texture produce
no Code 39 reads. These are generated images: real packaging, camera focus and
phone speed still need testing on actual phones.

Supported formats: Code 39, Code 128, QR and Data Matrix. Keep the whole code plus
its blank margins inside the frame. Move a barcode out for about 1.2 seconds
before deliberately scanning the same value again.

Frames never leave the phone during phone decoding. In fallback, JPEG frames are
processed in memory on the laptop and discarded without logging. Only decoded
`{id, text, format}` JSON is saved through `/api/scans`. A failed delivery stays
pending on the phone and blocks accepting another barcode until retried. Retries
reuse the same ID; the server suppresses duplicate delivery IDs in its last
2,000 records. Each request uses the session token from the phone link.

The camera stops when the tab becomes hidden and needs an explicit restart
when you return. The page fits the phone viewport without page scrolling;
cell tables scroll inside the result sheet. Decode rate and time are kept in
the hidden `#rate` element for browser diagnostics.

## Source navigation and checks

- `server.py`: certificate generation, two foreground HTTP servers, bounded
  frame/text APIs, `/trust-check`, receiver QR codes, untrusted-phone alerts,
  catalog completion endpoint, JSONL recording and shutdown.
- `processing.py`: laptop fallback: JPEG validation, native barcode localization,
  binary mask, illumination compensation, geometric/local-threshold retry.
- `lookup.py`: read-only SQLite connection, exact/dashless matching, location
  lookup, and unique-only completion of partly read barcodes.
- `static/scanner.js`: camera lifecycle, scan-frame crop, phone decoder worker,
  laptop fallback, catalog completion, torch/zoom/beep, duplicate suppression and
  acknowledged/retryable delivery.
- `static/decoder-worker.js`: native detector, zxing-wasm variants and recovery.
- `static/robust39.js`: damaged/curved/partial Code 39 recovery (no DOM; also
  runs in Node tests).
- `static/index.html`, `receiver.html`, `setup.html`, `style.css`, `icon.svg`,
  `manifest.webmanifest`: scanner, laptop receiver, phone setup with trust check.
- `static/vendor/`: unmodified zxing-wasm 3.1.5 reader assets and licenses. npm
  archive integrity verified before extraction; no CDN requests at runtime.
- `../tests/test_barcode_web.js` and `code39_scenes.js`: the real worker on Code
  128/QR/Code 39, ZXing agreement with the Code 39 generator, damage scenarios,
  catalog patterns, false-positive and random-damage (zero wrong reads) checks.
- `../tests/test_barcode_web.py`: live HTTP validation, persistence, retries,
  trust check, QR/session loopback limits, resolve validation, private files.
- `../tests/test_barcode_lookup.py`: exact/dashless IDs, catalog/staged
  exceptions, read-only access and unique-only pattern completion.
- `../tests/test_barcode_processing.py`: laptop fallback pipeline.
- `../tests/test_barcode_web_browser.py`: headless Chrome with a fake camera at
  phone sizes: phone-side decoding with no frame uploads, and laptop fallback
  when the worker is blocked.

Run from the repository root:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_barcode_processing tests.test_barcode_web tests.test_barcode_lookup
node tests/test_barcode_web.js
& '.\.venv\Scripts\python.exe' -m unittest tests.test_barcode_web_browser
```

The browser check needs the already installed Playwright package, Node, and
Chrome. It is not a real Safari or phone camera test: camera focus, real FPS,
native `BarcodeDetector` behaviour and LAN firewall reachability must be checked
on actual Android and iPhone hardware.

Upstream references: [ZXing-C++](https://github.com/zxing-cpp/zxing-cpp),
[zxing-wasm](https://github.com/Sec-ant/zxing-wasm),
[Barcode Detection API](https://developer.mozilla.org/docs/Web/API/Barcode_Detection_API),
[OpenCV filtering](https://docs.opencv.org/4.13.0/d4/d86/group__imgproc__filter.html),
[mkcert mobile trust instructions](https://github.com/FiloSottile/mkcert#mobile-devices).

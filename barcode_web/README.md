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
CA. The phone link stays the same across server restarts while the laptop's LAN
IP and ports stay the same. The phone remembers its access key in this browser's
local storage, so restoring a tab or reopening its address after a browser restart
does not require pasting the full phone link again. Existing tabs migrate their
old temporary key when refreshed. If a tab has already lost that key, open the
receiver's full phone link once to save it. On later server restarts, refresh the
phone tab and press **Start camera**. If the camera is still running, frame
uploads retry automatically. Pending scans survive a reload in the same tab;
use **Retry sending**. Clearing this site's browser data or using a new private
browsing session requires opening the full phone link again.

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
The top camera window is a **3.5:1 horizontal strip**, including when the phone
is held vertically. The video uses a centered cover crop, and capture uses the
same source coordinates: pixels outside that window are never uploaded. The
strip is scaled uniformly to at most 1280 pixels wide and encoded as JPEG at
92% quality. The phone sends it to authenticated `POST /api/frames` over local
HTTPS. Processing runs on the laptop, with no phone app to install.

The default preview is live color, with a faint white horizontal center line
and a red rectangle around the candidate barcode. The rectangle is an aiming
hint, not confirmation of a successful read; only valid decoder results are
accepted. It clears when the candidate disappears, capture fails or scanning
stops. The compact strip and page layout are unchanged.

**Mask** is optional and starts off: the window is white everywhere except
thresholded black ink inside a likely barcode region. This is a diagnostic
image returned as an in-memory PNG, not the image used for decoding.
OpenCV's built-in `barcode_BarcodeDetector`
replaces the hand-written Sobel/contour tag locator. It runs at reduced width
with white padding for the shallow strip. A successful ZXing position is a
fallback when OpenCV finds no candidate; a scanline-only position is shown as
a narrow band. Candidate masks can still be incomplete or mistaken.

The decoder tries the original strip first. It calls ZXing-C++'s **single-code
reader**, stopping at the first valid barcode instead of searching for more
symbols. Rotation and native downscale attempts remain enabled. On a miss,
an OpenCV horizontal grayscale closing estimates local illumination; division
by that background compensates for uneven light. A gentle horizontal
convolution `[-0.25, 1.5, -0.25]` then sharpens across the vertical bars before
one retry. If both full-strip attempts miss, a final retry uses the native
candidate's angle to rotate the **entire strip** on an expanded white canvas,
then applies adaptive local thresholding. It preserves both barcode ends and
the clear rows above/below a glare patch, even when glare splits the locator's
candidate into fragments. If no candidate exists, this retry thresholds the
unrotated full strip. Expanded rotations obey the camera pixel-allocation cap.
The more sensitive local threshold helps low-contrast ink that the native
scanline contrast threshold can reject. There are at most **three decoder calls
per frame**. No decoder attempt is cropped to an unconfirmed candidate. Retry
positions are mapped back into source coordinates. The old `red_regions` and
`straighten` helpers remain inactive.

A localized reflection does not have to prevent reading if a complete bar
sequence remains visible on other rows. A generated 3.5:1 scan-strip regression
reproduced a failure at 8/12 degrees of tilt with a small central glare patch:
the old final retry cropped to a partial candidate. Full-strip rotation recovers
all 12 tested angle/patch combinations, including six previously missed cases.
This verifies the reproduced failure, not every reflection on real packaging.

**Mask** only changes the preview; lighting/angle retries stay enabled in the
normal color view. `X-Mask: 1` requests the in-memory PNG; the normal API response
has `mask: null`, saving encoding and transfer work. Normalized `box` coordinates
are returned independently of the debug mask. `X-Enhance: 0` is still available
to API clients for an original-only decode.

The page fits the phone viewport without page scrolling: it keeps the scanned
barcode, product ID/name, locations and compact controls. Routine status and
FPS text are hidden; failures and retry controls remain visible when needed.
Optional cell tables scroll inside the remaining space. FPS remains available
in the hidden `#rate` element for browser diagnostics.

This is not a guarantee for folded or reflective packaging. Synthetic shadow,
partial-glare and mild-curve checks exercise the pipeline; actual tags still
need camera testing. The geometric retry corrects a candidate's angle; it does
not estimate or undo arbitrary nonlinear warping of crumpled packaging. Saturated glare
or a fold can remove required bar detail.

There is at most **one frame in flight per phone** and one concurrent decode
across phones. Slower capture, Wi-Fi or decoding skips frames rather than
building a queue. A 15 FPS target is not a hardware guarantee. The camera stops
when the tab becomes hidden and needs
an explicit restart when you return.

Supported decoder selection: linear barcodes (including Code 128, Code 39,
EAN/UPC and ITF), QR and Data Matrix. Keep the whole code plus its blank margins
inside the horizontal strip. Move a barcode out for about 1.2
seconds before deliberately scanning the same value again.

JPEG frames are processed in memory and discarded without logging. Frame byte
size and dimensions are bounded before native decoding. Only decoded
`{id, text, format}` JSON is saved through `/api/scans`. A failed delivery stays pending on the
phone and blocks accepting another barcode until retried. Retries reuse the
same ID; the server suppresses duplicate delivery IDs in its last 2,000 records.
Each request uses the current session token from the phone-link fragment.

## Scanner framework check (2026-10-16)

- [ZXing-C++](https://github.com/zxing-cpp/zxing-cpp) is the existing native
  decoder, with Python and WebAssembly bindings; it is already an established
  scanner engine, not a custom decoder. This change uses its single-code API.
- [OpenCV's barcode detector](https://docs.opencv.org/4.x/dc/df7/classcv_1_1barcode_1_1BarcodeDetector.html)
  is already installed and returns candidate quadrangles. Only localization
  is used; ZXing continues to decode Code 128 and the other supported formats.
- [Quagga2](https://github.com/ericblade/quagga2) is a browser alternative with
  localization and configurable sampling. Its documentation recommends a
  restricted scan area when users can aim through a rectangle. It has not
  been benchmarked against this pipeline on real packaging, so a speed or
  accuracy advantage is unproven.
- [Dynamsoft's browser samples](https://github.com/Dynamsoft/barcode-reader-javascript-samples)
  demonstrate a commercial browser SDK. Its vendor advertises curved/damaged
  barcode support, but that is not verified here. Integration requires a
  license; no trial, paid SDK, or external image-upload service was added.

## Source navigation and checks

- `server.py`: certificate generation, two foreground HTTP servers, bounded
  frame/text APIs, local receiver session, JSONL recording and shutdown.
- `processing.py`: JPEG validation, native barcode localization, binary mask,
  illumination compensation, final geometric/local-threshold retry and single-code decoding.
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

For the temporary mask/lighting path, this focused check uses generated images
and does not access the warehouse database:

```powershell
@'
import base64, cv2, numpy as np, zxingcpp
from unittest.mock import patch
from barcode_web import processing as p
from tests.test_barcode_processing import packaging, jpeg
bars = np.asarray(zxingcpp.write_barcode(zxingcpp.BarcodeFormat.Code128, '06410KFL850', 660, 240))
label = cv2.cvtColor(bars, cv2.COLOR_GRAY2BGR)
shadow = (label * np.linspace(.25, 1, label.shape[1])[None, :, None]).astype(np.uint8)
flare = (235 + bars.astype(np.float32) / 255 * 20).astype(np.uint8)
tilted = np.full((260, 800), 255, np.uint8)
tilted[95:165, 70:730] = cv2.resize(bars, (660, 70))
tilted = cv2.warpAffine(tilted, cv2.getRotationMatrix2D((400, 130), 15, 1), (800, 260), borderValue=255)
for scene in (label, shadow, packaging(label)[180:540], flare, tilted):
    with patch.object(p, 'read', wraps=p.read) as reader:
        answer = p.decode_frame(jpeg(scene), include_mask=True)
        assert reader.call_count <= 3
    assert answer['results'][0]['text'] == '06410KFL850'
    raw = base64.b64decode(answer['mask'].split(',')[1])
    mask = cv2.imdecode(np.frombuffer(raw, np.uint8), 0)
    y, x = np.where(mask == 0)
    assert set(np.unique(mask)) == {0, 255} and y.max() - y.min() > 10
assert p.decode_frame(jpeg(shadow))['stage'] == 'local contrast'
assert p.decode_frame(jpeg(flare))['stage'] == 'local threshold'
assert p.decode_frame(jpeg(tilted))['stage'] == 'angle / local threshold'
assert p.decode_frame(jpeg(label))['mask'] is None
print('Decode budget, shadow/flare/angle recovery, mask and default color path passed.')
for angle in (0, 8, 12):
    for glare in (0, 12, 24, 36):
        scene = np.full((228, 800), 255, np.uint8)
        scene[69:159, 70:730] = cv2.resize(bars, (660, 90))
        if glare:
            cv2.ellipse(scene, (400, 114), (90, glare // 2), 0, 0, 360, 255, -1)
        scene = cv2.warpAffine(scene, cv2.getRotationMatrix2D((400, 114), angle, 1), (800, 228), borderValue=255)
        with patch.object(p, 'read', wraps=p.read) as reader:
            answer = p.decode_frame(jpeg(scene))
            assert reader.call_count <= 3
        assert answer['results'][0]['text'] == '06410KFL850', (angle, glare)
wide = np.full((16, p.MAX_FRAME_PIXELS // 16), 255, np.uint8)
assert p.deskew_strip(wide, np.float32([[0, 0], [10, 10], [9, 11], [-1, 1]])) == (None, None)
print('Partial central glare at 0/8/12 degrees and rotated-allocation guard passed.')
'@ | & '.\.venv\Scripts\python.exe' -
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

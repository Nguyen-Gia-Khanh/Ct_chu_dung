# Phone scanner: cheap looks, strong tries — design

Date: 2026-11-04. Branch: `feature/scanner-fast-strong`. Phone scanner (`barcode_web/`) only.

## Why

Reported on Android and iPhone: good labels beep slowly, damaged labels never
read, and the phone gets hot and laggy. "Fewer, stronger tries" is acceptable,
down to about 2 analysed frames per second.

Evidence (synthetic 11-character Code 39 labels, 950×317 scan window, this
laptop's i5-8250U, roughly a mid-range phone's single-core speed):

- Every analysed frame ran native → zxing (`tryHarder`) → a JS filter → Robust39,
  8 times per second, even with no barcode in view. Real scans are 10–90 s
  apart (`scans.jsonl`), so nearly all of that work found nothing.
- Only one zxing variant ran per frame (original / local contrast / original /
  local threshold). A label that only one variant reads waited up to 4 frames.
- Every tier failed when focus blur exceeded about 1.3–1.5 bar widths.
  Horizontal sharpening reads blur of about 1.7 bar widths in one frame.
- Linear codes are read row by row: decoding every 3rd row keeps the yield of
  each variant (16/17 of the local-contrast yield) at a third of the cost,
  provided zxing's own downscale pass stays on.
- 400 heavily damaged random labels and 60 bar textures: 0 wrong reads for
  each variant (plain, sharpened, local contrast, local threshold).
- The log shows a label carrying both a QR and a Code 39 alternating 15 times
  in 2 s: duplicate suppression only remembered the last text.

## Behaviour

### Worker, per frame

1. **Cheap look.** Grayscale; a few-scanline edge probe; native
   `BarcodeDetector` (only when the probe sees edges); zxing on the original,
   all formats, without `tryHarder`. A read ends the frame.
2. **Nothing barcode-like** (probe quiet): return `present: false`, stage `idle`.
3. **Strong try** on the same frame, in order, first read wins: every 3rd row
   (plain, sharpened, local contrast, local threshold; linear formats); QR and
   Data Matrix with `tryHarder` on the full frame; Robust39 multi-frame recovery.
   Each step is cheap; the whole try costs about what one rotated variant did.

Native Code 39 still needs a second agreeing native read, now within 1 s
(strong tries can be slower than the old 600 ms window). When native returns
several codes, a linear code wins over a 2D one.

### Scheduling (scanner.js)

One frame in flight, as before. The next frame starts:

- immediately while a barcode-like pattern is in view and unread (strong tries
  back to back), easing to 250 ms after 3 s of unread aiming;
- 250 ms after a frame with nothing barcode-like (about 4 cheap looks/s);
- 300 ms after a repeat read of a barcode still in view.

Laptop fallback uploads keep their 8/s cap.

### Duplicates

Every text read in the last 1.2 s is suppressed, not only the last one.

### Field timing

Each camera scan sends optional `source` (which reader: `native`, `zxing:<stage>`,
`recovery`, `catalog`) and `aim_ms` (time a barcode-like pattern was in view
before the read). The server validates and stores both in `scans.jsonl`.
Typed searches send neither.

## Not changed

Recovery acceptance rules (two frames, votes, margins), catalog completion,
delivery/retry, camera settings, laptop pipeline, receiver.

## Checks

- `node tests/test_barcode_web.js`: matrix codes read on the first frame;
  blank frames return `idle`; focus-blurred Code 39 reads on the first frame;
  worker-level random heavy damage gives 0 wrong reads.
- `tests.test_barcode_web`: optional `source`/`aim_ms` accepted, stored, and
  validated.
- `tests.test_barcode_web_browser`: phone decoding still works; held-label
  decoding stays well under the old 8/s.
- Latency benchmark (scratch): time to read per scenario, before/after.

## Addendum: real labels (same day)

Six photos of real Honda labels on plastic bags (wrinkled, sheared, folded,
torn, curved; about 2.4 px per narrow bar) were read 1/12 times by both the old
and the first new decoder (two scales). Traces showed one end of each code read
well and the other end lost, so no scanline saw both start and stop; on sheared
labels the readable characters sat on different scanlines.

Decisions (confirmed with the user: products can be missing from the catalog;
completed reads are accepted automatically with the catalog badge; a save-frame
button for real samples):

- The phone fetches catalog IDs. Recovered Code 39 must be a catalog ID (in
  synthetic heavy damage, all 21 non-catalog recovered reads were wrong); zxing
  Code 39 outside the catalog needs a second frame.
- Recovery also scans at ±10°, only with the catalog checks (more lines
  produced a wrong full read, `40591K.6`, without them).
- Strict catalog completion: at most one unseen character, no frame reading a
  different character, at least six seen, unique. Two unseen characters gave
  15–19/300 wrong IDs when the true ID was removed; this rule gave 0/300.
- Result on the real photos: 4/12 through the worker (3/6 in the regression
  test), 0 wrong, 0 wrong with the true IDs removed. Smaller bars (1.9 px) read
  nothing: zoom matters more than any decoder change.
- Save-frame button: 6 PNG frames of the decode window plus details to
  `data/barcode_web/samples/`.

## Addendum: saved phone frames (same day)

144 frames (24 bursts) saved with the new button on an iPhone, all at zoom
0.5 (the ultra-wide lens: the slider's left end, which looked like 1×). Replayed
6-frame bursts: main 14/23 labels, this branch 14/23 without and 16/23 with the
catalog, 0 wrong; the laptop pipeline read 2 more. The receiver log showed two
wrong scans, both laptop second opinions (`0` as Code 39, `059521` as ITF), so:
the laptop reads only Code 39/128, QR and Data Matrix; a second opinion's Code 39
must be a catalog ID; second opinions start after 0.6 s instead of 1.2 s. Votes
for `$ / + % . -` are ignored by catalog completion (no ID contains them).
`tests/check_barcode_samples.js` replays saved bursts.

/* Phone-side decoding. Each frame gets a cheap look; only frames with barcode-like edges get a
 * strong try, and that try runs every variant on the same frame. First accepted result wins.
 * 1. Cheap look: native BarcodeDetector (Android Chrome; ML Kit engine) when edges are in view,
 *    then zxing-wasm on the original frame without tryHarder.
 * 2. Strong try: zxing on every 3rd row (plain, sharpened, light-flattened, thresholded),
 *    Robust39 multi-frame Code 39 recovery and, with the laptop's catalog IDs, strict completion of
 *    damaged reads; then zxing QR/Data Matrix with tryHarder.
 * Only decoded text leaves the phone; frames never do (unless the laptop fallback asks). */
importScripts("/vendor/reader.js", "/robust39.js");

const ZXING_FORMATS = ["Code39", "Code128", "QRCode", "DataMatrix"];
const NATIVE_FORMATS = { code_39: "Code 39", code_128: "Code 128", qr_code: "QR Code", data_matrix: "DataMatrix" };
const COMMON = { tryRotate: false, tryInvert: false, maxNumberOfSymbols: 1, minLineCount: 2, returnErrors: false,
                 textMode: "Plain" };
const CHEAP = { ...COMMON, formats: ZXING_FORMATS, tryHarder: false, tryDownscale: true };
// zxing's own downscale pass averages noise; it carries much of the light-flattened variant's yield.
const LINEAR = { ...COMMON, formats: ["Code39", "Code128"], tryHarder: true, tryDownscale: true };
const MATRIX = { ...COMMON, formats: ["QRCode", "DataMatrix"], tryHarder: true, tryDownscale: true };
// Linear codes are read along rows: every 3rd row keeps their detail at a third of the cost.
const ROW_STEP = 3;
// Recovery also scans along the band of bars at ±10°: sheared/bent labels on plastic bags. Those extra
// lines repeat a label's own defects, so they run only with the catalog check below.
const SPREAD = [0, -10, 10];
const session = new Robust39.Session();
let native = null, nativeCandidate = null;
// Catalog IDs from the laptop (optional): recovered reads must be catalog IDs, damaged reads may be
// completed from it, and a zxing Code 39 that is not a catalog ID must repeat on a second frame.
let catalog = null, offCatalog = null;

async function prepareNative() {
  if (typeof BarcodeDetector === "undefined") return null;
  try {
    const supported = await BarcodeDetector.getSupportedFormats();
    const formats = Object.keys(NATIVE_FORMATS).filter(format => supported.includes(format));
    return formats.length ? new BarcodeDetector({ formats }) : null;
  } catch (_) {
    return null;   // The detector is optional; zxing-wasm and recovery always run.
  }
}

const ready = Promise.all([
  ZXingWASM.prepareZXingModule({
    overrides: { locateFile: path => path.endsWith(".wasm") ? "/vendor/zxing_reader.wasm" : path },
    fireImmediately: true,
  }),
  prepareNative().then(detector => { native = detector; }),
]);
ready.then(() => postMessage({ type: "ready", native: Boolean(native) }))
  .catch(error => postMessage({ type: "error", message: error.message }));

function formatName(format) {
  const compact = String(format).replace(/[\s_-]/g, "").toLowerCase();
  if (compact.startsWith("code39")) return "Code 39";
  if (compact.startsWith("code128")) return "Code 128";
  if (compact.startsWith("qr")) return "QR Code";
  if (compact.startsWith("datamatrix")) return "DataMatrix";
  return String(format);
}

function toGray(rgba, size) {
  const gray = new Uint8ClampedArray(size);
  for (let i = 0, p = 0; i < size; i++, p += 4) gray[i] = (77 * rgba[p] + 150 * rgba[p + 1] + 29 * rgba[p + 2]) >> 8;
  return gray;
}

function toImage(gray, width, height) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0, p = 0; i < gray.length; i++, p += 4) {
    data[p] = data[p + 1] = data[p + 2] = gray[i];
    data[p + 3] = 255;
  }
  return { data, width, height };
}

/** One row's running max (or min) over ±radius (van Herk / Gil-Werman), written for the JIT. */
function runningExtreme(row, out, width, radius, max, prefix, suffix) {
  const size = 2 * radius + 1;
  for (let x = 0, block = 0; x < width; x++, block++) {
    const v = row[x];
    if (block === size) block = 0;
    const p = prefix[x - 1];
    prefix[x] = block === 0 ? v : max ? (p > v ? p : v) : (p < v ? p : v);
  }
  for (let x = width - 1; x >= 0; x--) {
    const v = row[x];
    const s = suffix[x + 1];
    suffix[x] = x === width - 1 || (x + 1) % size === 0 ? v : max ? (s > v ? s : v) : (s < v ? s : v);
  }
  for (let x = 0; x < width; x++) {
    const a = suffix[x > radius ? x - radius : 0], b = prefix[x + radius < width ? x + radius : width - 1];
    out[x] = max ? (a > b ? a : b) : (a < b ? a : b);
  }
}

/** Same idea as the laptop's "local contrast" stage: divide out uneven light, sharpen across bars. */
function flatten(gray, width, height) {
  const radius = Math.max(8, Math.round(25 * width / 1280));
  const prefix = new Uint8Array(width), suffix = new Uint8Array(width + 1);
  const lighter = new Uint8Array(width), background = new Uint8Array(width), flat = new Float32Array(width);
  const sharp = new Uint8ClampedArray(gray.length);
  for (let y = 0, offset = 0; y < height; y++, offset += width) {
    // Horizontal closing removes the dark bars and leaves the paper's illumination.
    runningExtreme(gray.subarray(offset, offset + width), lighter, width, radius, true, prefix, suffix);
    runningExtreme(lighter, background, width, radius, false, prefix, suffix);
    for (let x = 0; x < width; x++) flat[x] = gray[offset + x] * 255 / (background[x] || 1);
    sharp[offset] = flat[0];
    sharp[offset + width - 1] = flat[width - 1];
    for (let x = 1; x < width - 1; x++) sharp[offset + x] = 1.5 * flat[x] - .25 * (flat[x - 1] + flat[x + 1]);
  }
  return sharp;
}

/** Local mean threshold (integral image); helps low-contrast ink the native scanlines reject. */
function threshold(gray, width, height) {
  const radius = Math.max(6, Math.round(15 * width / 1280));
  const stride = width + 1;
  const integral = new Int32Array(stride * (height + 1));
  for (let y = 0; y < height; y++) {
    let rowSum = 0;
    const above = y * stride, here = above + stride, offset = y * width;
    for (let x = 0; x < width; x++) {
      rowSum += gray[offset + x];
      integral[here + x + 1] = integral[above + x + 1] + rowSum;
    }
  }
  const out = new Uint8ClampedArray(gray.length);
  for (let y = 0; y < height; y++) {
    const y0 = y > radius ? y - radius : 0, y1 = y + radius + 1 < height ? y + radius + 1 : height;
    const top = y0 * stride, bottom = y1 * stride, rows = y1 - y0, offset = y * width;
    for (let x = 0; x < width; x++) {
      const x0 = x > radius ? x - radius : 0, x1 = x + radius + 1 < width ? x + radius + 1 : width;
      const sum = integral[bottom + x1] - integral[top + x1] - integral[bottom + x0] + integral[top + x0];
      out[offset + x] = gray[offset + x] * rows * (x1 - x0) > sum - 2 * rows * (x1 - x0) ? 255 : 0;
    }
  }
  return out;
}

/** Undo some focus blur across vertical bars: horizontal unsharp mask over ±radius. */
function sharpen(gray, width, height, radius = 3, amount = 2) {
  const out = new Uint8ClampedArray(gray.length), size = 2 * radius + 1, last = width - 1;
  for (let y = 0, offset = 0; y < height; y++, offset += width) {
    let sum = 0;
    for (let x = -radius - 1; x < radius; x++) sum += gray[offset + (x < 0 ? 0 : x > last ? last : x)];
    for (let x = 0; x < width; x++) {
      const add = x + radius, drop = x - radius - 1;
      sum += gray[offset + (add > last ? last : add)] - gray[offset + (drop < 0 ? 0 : drop)];
      const value = gray[offset + x];
      out[offset + x] = value + amount * (value - sum / size);
    }
  }
  return out;
}

/** Every ROW_STEP-th row, for the linear-only strong variants. */
function rowsOf(gray, width, height) {
  const rows = Math.ceil(height / ROW_STEP), out = new Uint8ClampedArray(width * rows);
  for (let y = 0; y < rows; y++) out.set(gray.subarray(y * ROW_STEP * width, (y * ROW_STEP + 1) * width), y * width);
  return { gray: out, width, height: rows };
}

/** Cheap look: does any of a few scanlines cross many alternating light/dark edges?
 *  Bars, QR modules and print pass; blank card, hands and camera noise do not. */
function edgesInView(gray, width, height) {
  // STEP: mean level difference between the 2 px either side; faint labels still give 25+.
  const LINES = 7, MIN_EDGES = 16, STEP = 16;
  if (width < 16 || height < 8) return false;
  for (let line = 1; line <= LINES; line++) {
    const y = Math.min(height - 2, Math.max(1, Math.round(height * (line + 1) / (LINES + 3))));
    const above = (y - 1) * width, row = y * width, below = (y + 1) * width;
    let edges = 0, sign = 0;
    for (let x = 2; x < width - 2; x++) {
      // Three rows by two pixels on each side: noise-tolerant, still sharp at 2 px modules.
      const right = gray[above + x + 1] + gray[row + x + 1] + gray[below + x + 1]
                  + gray[above + x + 2] + gray[row + x + 2] + gray[below + x + 2];
      const left = gray[above + x - 1] + gray[row + x - 1] + gray[below + x - 1]
                 + gray[above + x - 2] + gray[row + x - 2] + gray[below + x - 2];
      const difference = right - left;
      const now = difference > 6 * STEP ? 1 : difference < -6 * STEP ? -1 : 0;
      if (now && now !== sign) { sign = now; if (++edges >= MIN_EDGES) return true; }
    }
  }
  return false;
}

function boxOf(points, width, height) {
  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  const left = Math.max(0, Math.min(...xs)), top = Math.max(0, Math.min(...ys));
  const right = Math.min(width, Math.max(...xs)), bottom = Math.min(height, Math.max(...ys));
  if (!(right > left)) return null;
  // Linear readers can report a single scanline; give the outline some height.
  const minimum = height * .12;
  const middle = (top + bottom) / 2, half = Math.max(minimum, bottom - top) / 2;
  return [left / width, Math.max(0, middle - half) / height, (right - left) / width,
          (Math.min(height, middle + half) - Math.max(0, middle - half)) / height];
}

/** Native reads: Code 128/QR/Data Matrix at once; Code 39 (no check digit) after a second agreeing frame. */
async function readNative(rgba, width, height, time) {
  let codes;
  try {
    codes = await native.detect(new ImageData(rgba, width, height));
  } catch (_) {
    native = null;   // A broken platform detector must not stop the other tiers.
    return null;
  }
  // A label carrying both a QR and a Code 39 gives the linear product code.
  const found = codes.find(code => code.rawValue && (code.format === "code_39" || code.format === "code_128"))
    || codes.find(code => code.rawValue);
  if (!found) return null;
  const format = NATIVE_FORMATS[found.format] || found.format;
  const box = boxOf(found.cornerPoints || [], width, height);
  // Strong tries can take a few hundred ms on a slow phone, so "two frames" allows up to 1 s.
  if (format === "Code 39" && !(nativeCandidate?.text === found.rawValue && time - nativeCandidate.time < 1000)) {
    nativeCandidate = { text: found.rawValue, time };
    return { box };
  }
  nativeCandidate = null;
  return { box, read: { text: found.rawValue, format, source: "native" } };
}

/** Code 39 has no check digit: with the catalog loaded, a Code 39 that is no catalog ID (a misread such
 *  as "45440K//$1", or another company's label) is accepted only when a second frame reads it too. */
function trusted(read, time) {
  if (!catalog || read.format !== "Code 39" || catalog.has(read.text)) return true;
  if (offCatalog?.text === read.text && time - offCatalog.time < 1000) {
    offCatalog = null;
    return true;
  }
  offCatalog = { text: read.text, time };
  return false;
}

/** zxing on an RGBA image; `step` maps rows of a row-subsampled image back to the frame. */
async function readZxing(image, options, width, height, step = 1) {
  const [read] = await ZXingWASM.readBarcodes(image, options);
  if (!read?.text) return null;
  const p = read.position;
  const points = [p.topLeft, p.topRight, p.bottomRight, p.bottomLeft].map(({ x, y }) => ({ x, y: y * step }));
  return { text: read.text, format: formatName(read.format), source: "zxing", box: boxOf(points, width, height) };
}

async function decode({ buffer, width, height, time }) {
  const rgba = new Uint8ClampedArray(buffer);
  const original = { data: rgba, width, height };
  const gray = toGray(rgba, width * height);
  const busy = edgesInView(gray, width, height);
  const found = ({ box, ...read }, stage) => {
    session.reset();
    return { results: [read], box, present: true, stage };
  };
  // A first sighting of a Code 39 outside the catalog: nothing else may confirm it on this frame.
  const unconfirmed = read => ({ results: [], box: read.box, present: true, stage: "unconfirmed" });
  // ---- Cheap look: every frame ----
  let nativeBox = null;
  if (native && busy) {
    const answer = await readNative(rgba, width, height, time);
    if (answer?.read) return found({ ...answer.read, box: answer.box }, "native");
    nativeBox = answer?.box || null;
  }
  const quick = await readZxing(original, CHEAP, width, height);
  if (quick) return trusted(quick, time) ? found(quick, "fast") : unconfirmed(quick);
  if (!busy) return { results: [], box: null, present: false, stage: "idle" };
  // ---- Strong try: barcode-like edges are in view, so every variant gets this frame ----
  const rows = rowsOf(gray, width, height);
  const flat = () => flatten(rows.gray, rows.width, rows.height);
  let flattened = null;
  const variants = [
    ["rows", () => rows.gray],
    ["sharpened", () => sharpen(rows.gray, rows.width, rows.height)],
    ["local contrast", () => (flattened = flat())],
    ["local threshold", () => threshold(flattened || flat(), rows.width, rows.height)],
  ];
  for (const [stage, variant] of variants) {
    const read = await readZxing(toImage(variant(), rows.width, rows.height), LINEAR, width, height, ROW_STEP);
    if (read) return trusted(read, time) ? found(read, stage) : unconfirmed(read);
  }
  const observation = Robust39.scanFrame(gray, width, height, catalog ? SPREAD : [0]);
  // With the catalog, session.accept refuses recovered text that is no catalog ID (keeping its votes).
  const consensus = session.add(observation, time);
  if (consensus.text) {
    return { results: [{ text: consensus.text, format: "Code 39", source: "recovery" }],
             box: observation.box, present: true, stage: "recovery" };
  }
  const completed = catalog && observation.present ? catalog.complete(session.lattice()) : null;
  if (completed) {
    session.reset();
    return { results: [{ text: completed, format: "Code 39 · catalog", source: "catalog" }],
             box: observation.box, present: true, stage: "catalog" };
  }
  // Code 39 characters in view: a QR beside them is not the product code, skip the 2D search.
  const matrix = observation.present ? null : await readZxing(original, MATRIX, width, height);
  if (matrix) return found(matrix, "2D");
  return { results: [], box: observation.box || nativeBox, present: observation.present || Boolean(nativeBox),
           stage: "strong", partial: consensus.partial && consensus.stableMs >= 500 ? consensus.partial : null };
}

onmessage = async ({ data }) => {
  if (data.type === "reset") { session.reset(); nativeCandidate = offCatalog = null; return; }
  if (data.type === "catalog") {
    catalog = new Robust39.Catalog(data.ids);
    session.accept = text => catalog.has(text);
    return;
  }
  const started = performance.now();
  try {
    await ready;
    const answer = await decode(data);
    postMessage({ type: "result", id: data.id, ...answer, milliseconds: performance.now() - started });
  } catch (error) {
    postMessage({ type: "error", id: data.id, message: error.message });
  }
};

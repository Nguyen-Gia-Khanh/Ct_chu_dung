/* Phone-side decoding. Tiers, first accepted result wins:
 * 1. Native BarcodeDetector (Android Chrome; ML Kit engine), when it is available.
 * 2. zxing-wasm, rotating original / flattened-light / local-threshold variants across frames.
 * 3. Robust39: multi-scanline, multi-frame recovery of curved, glared or partly missing Code 39.
 * Only decoded text leaves the phone; frames never do (unless the laptop fallback asks). */
importScripts("/vendor/reader.js", "/robust39.js");

const ZXING_FORMATS = ["Code39", "Code128", "QRCode", "DataMatrix"];
const LINEAR_FORMATS = ["Code39", "Code128"];
const NATIVE_FORMATS = { code_39: "Code 39", code_128: "Code 128", qr_code: "QR Code", data_matrix: "DataMatrix" };
const session = new Robust39.Session();
let native = null, nativeCandidate = null, variant = 0;

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

async function decode({ buffer, width, height, time }) {
  const rgba = new Uint8ClampedArray(buffer);
  const gray = toGray(rgba, width * height);
  if (native) {
    try {
      const [found] = await native.detect(new ImageData(rgba, width, height));
      if (found?.rawValue) {
        const format = NATIVE_FORMATS[found.format] || found.format;
        const box = boxOf(found.cornerPoints || [], width, height);
        // Code 39 has no check digit: the native reader must agree with itself on two frames.
        if (format !== "Code 39" || (nativeCandidate?.text === found.rawValue && time - nativeCandidate.time < 600)) {
          nativeCandidate = null;
          session.reset();
          return { results: [{ text: found.rawValue, format, source: "native" }], box, present: true, stage: "native" };
        }
        nativeCandidate = { text: found.rawValue, time };
      }
    } catch (_) {
      native = null;   // A broken platform detector must not stop the other tiers.
    }
  }
  // Original every other frame (all formats). In between, light-flattened or thresholded copies for
  // linear codes only: both whiten large dark areas such as QR finder patterns.
  variant = (variant + 1) % 4;
  const enhanced = variant % 2 === 1;
  const source = !enhanced ? { data: rgba, width, height }
    : toImage(variant === 1 ? flatten(gray, width, height) : threshold(flatten(gray, width, height), width, height), width, height);
  const [read] = await ZXingWASM.readBarcodes(source, {
    formats: enhanced ? LINEAR_FORMATS : ZXING_FORMATS, tryHarder: true, tryRotate: false, tryInvert: false,
    tryDownscale: true, maxNumberOfSymbols: 1, minLineCount: 2, returnErrors: false, textMode: "Plain",
  });
  const stage = ["original", "local contrast", "original", "local threshold"][variant];
  if (read?.text) {
    session.reset();
    const p = read.position;
    return { results: [{ text: read.text, format: formatName(read.format), source: "zxing" }],
             box: boxOf([p.topLeft, p.topRight, p.bottomRight, p.bottomLeft], width, height), present: true, stage };
  }
  const observation = Robust39.scanFrame(gray, width, height);
  const consensus = session.add(observation, time);
  if (consensus.text) {
    return { results: [{ text: consensus.text, format: "Code 39", source: "recovery" }],
             box: observation.box, present: true, stage: "recovery" };
  }
  return { results: [], box: observation.box, present: observation.present, stage,
           partial: consensus.partial && consensus.stableMs >= 500 ? consensus.partial : null };
}

onmessage = async ({ data }) => {
  if (data.type === "reset") { session.reset(); nativeCandidate = null; return; }
  const started = performance.now();
  try {
    await ready;
    const answer = await decode(data);
    postMessage({ type: "result", id: data.id, ...answer, milliseconds: performance.now() - started });
  } catch (error) {
    postMessage({ type: "error", id: data.id, message: error.message });
  }
};

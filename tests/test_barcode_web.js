/* Phone decoder tests: the real worker (zxing-wasm + Code 39 recovery) and synthetic damaged labels. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const zlib = require("node:zlib");
const { performance } = require("node:perf_hooks");
const R39 = require("../barcode_web/static/robust39.js");
const { scene, toRGBA, rng } = require("./code39_scenes.js");
const staticRoot = path.resolve(__dirname, "../barcode_web/static");
const PART = "53205KTL640ZC";

function rgba(width, height) {
  return { width, height, data: new Uint8ClampedArray(width * height * 4).fill(255) };
}
function rectangle(image, x, y, width, height) {
  for (let row = y; row < y + height; row++) {
    for (let col = x; col < x + width; col++) {
      const index = (row * image.width + col) * 4;
      image.data[index] = image.data[index + 1] = image.data[index + 2] = 0;
    }
  }
}
function code128() {
  // Code 128 C: 001234567890, including start, checksum, stop and quiet margins.
  const pattern = "BaAbCbBaBbBbAaBbCbAcAaBcCcAaBaBdAaAbBaDaBaAaCcBaBcCaAaB";
  const image = rgba(660, 240);
  let x = 60;
  for (const symbol of pattern) {
    const width = (symbol.toLowerCase().charCodeAt(0) - 96) * 4;
    if (symbol === symbol.toUpperCase()) rectangle(image, x, 40, width, 160);
    x += width;
  }
  return image;
}
function qr() {
  const rows = [
    "1111111001000010001111111", "1000001011011001001000001", "1011101001110011001011101",
    "1011101011010001101011101", "1011101000101100001011101", "1000001010100111001000001",
    "1111111010101010101111111", "0000000000001101000000000", "1111101111101011110101010",
    "0000110111000000000001010", "1110101001011001110101111", "0011110011110011111100011",
    "0101101101010000011011101", "1100000110101110010100000", "1011011001000111011110011",
    "1010010110101101101000010", "1001011000101011111111111", "0000000011100000100011110",
    "1111111010011000101011011", "1000001001110010100010000", "1011101011010001111111101",
    "1011101010101110111110111", "1011101011100111000100101", "1000001011001100111100001",
    "1111111010101010011100111",
  ];
  const image = rgba(264, 264);
  rows.forEach((row, y) => [...row].forEach((bit, x) => {
    if (bit === "1") rectangle(image, (x + 4) * 8, (y + 4) * 8, 8, 8);
  }));
  return image;
}
function randomBars(seed) {
  const image = rgba(1280, 427), random = rng(seed);
  let value = 200;
  for (let x = 0; x < image.width; x++) {
    if (random() < .25) value = random() < .5 ? 40 : 230;
    for (let y = 0; y < image.height; y++) {
      const i = (y * image.width + x) * 4;
      image.data[i] = image.data[i + 1] = image.data[i + 2] = value + random() * 10;
    }
  }
  return image;
}

/** Stand-in for Android's BarcodeDetector: each detect() returns the next scripted list of codes. */
function scriptedDetector(script) {
  return class {
    static async getSupportedFormats() { return ["code_39", "code_128", "qr_code", "data_matrix"]; }
    async detect() {
      return (script.shift() || []).map(([format, rawValue]) => ({ format, rawValue,
        cornerPoints: [{ x: 10, y: 10 }, { x: 300, y: 10 }, { x: 300, y: 80 }, { x: 10, y: 80 }] }));
    }
  };
}

/** Evaluate the actual browser worker. Only transport/loading are adapted; BarcodeDetector is absent
 *  unless a scripted stand-in is given. */
async function loadWorker(detector = null) {
  let resolveMessage;
  const sandbox = vm.createContext({
    console, performance, WebAssembly, Uint8ClampedArray, Uint8Array, ArrayBuffer,
    URL, Blob, TextDecoder, TextEncoder,
    fetch: async url => {
      assert.equal(url, "/vendor/zxing_reader.wasm", "WASM must be local, never a CDN");
      return new Response(fs.readFileSync(path.join(staticRoot, "vendor/zxing_reader.wasm")),
                          { headers: { "Content-Type": "application/wasm" } });
    },
    postMessage: message => resolveMessage(message),
    ...(detector && { BarcodeDetector: detector, ImageData: class { constructor(data, width, height) {
      Object.assign(this, { data, width, height }); } } }),
  });
  sandbox.self = sandbox;
  sandbox.importScripts = (...urls) => urls.forEach(url =>
    vm.runInContext(fs.readFileSync(path.join(staticRoot, url), "utf8"), sandbox, { filename: url }));
  let message = new Promise(resolve => { resolveMessage = resolve; });
  vm.runInContext(fs.readFileSync(path.join(staticRoot, "decoder-worker.js"), "utf8"), sandbox);
  const ready = await message;
  assert.equal(ready.type, "ready", ready.message);
  assert.equal(ready.native, Boolean(detector));
  let id = 0;
  const decode = async (image, time = 0) => {
    message = new Promise(resolve => { resolveMessage = resolve; });
    sandbox.onmessage({ data: { type: "frame", id: ++id, buffer: image.data.slice().buffer,
                                width: image.width, height: image.height, time } });
    const response = await message;
    assert.equal(response.type, "result", response.message);
    return response;
  };
  decode.send = data => sandbox.onmessage({ data });   // "reset" or "catalog" messages from the page
  return decode;
}

/** Real label photos (tests/fixtures/real_labels): grayscale crops around the scan window. */
function realLabels() {
  const folder = path.join(__dirname, "fixtures/real_labels");
  const { labels, catalog } = JSON.parse(fs.readFileSync(path.join(folder, "labels.json"), "utf8"));
  const cases = Object.entries(labels).map(([tag, label]) => {
    const sub = zlib.gunzipSync(fs.readFileSync(path.join(folder, `${tag}.gray.gz`)));
    const gray = new Uint8ClampedArray(sub.length);
    // Undo the horizontal "Sub" filter applied before compression.
    for (let y = 0, i = 0; y < label.height; y++) {
      for (let x = 0, last = 0; x < label.width; x++, i++) gray[i] = last = (last + sub[i]) & 255;
    }
    return { tag, ...label, gray };
  });
  return { cases, catalog };
}

/** Successive video frames of a real label: small hand movement (shift, scale) around the window. */
function handheld({ gray, width, window: [x0, y0, w, h] }, frame) {
  const dx = ((frame * 7) % 9 - 4) * 1.5, dy = ((frame * 5) % 7 - 3) * 1.5, zoom = 1 + ((frame * 3) % 5 - 2) * .015;
  const data = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const sx = x0 + dx + w / 2 + (x + .5 - w / 2) / zoom - .5, sy = y0 + dy + h / 2 + (y + .5 - h / 2) / zoom - .5;
    const ix = Math.floor(sx), iy = Math.floor(sy), fx = sx - ix, fy = sy - iy, i = iy * width + ix;
    const v = (gray[i] * (1 - fx) + gray[i + 1] * fx) * (1 - fy) + (gray[i + width] * (1 - fx) + gray[i + width + 1] * fx) * fy;
    const p = (y * w + x) * 4;
    data[p] = data[p + 1] = data[p + 2] = v;
    data[p + 3] = 255;
  }
  return { data, width: w, height: h };
}

/** Feed frames to a fresh recovery session; returns the accepted text and the last partial pattern. */
function recover(frames, rounds = 3) {
  const session = new R39.Session();
  let partial = null, frame = 0;
  for (let round = 0; round < rounds; round++) {
    for (const options of frames) {
      const image = scene(PART, { ...options, seed: (options.seed || 1) + round * 17 });
      const answer = session.add(R39.scanFrame(image.gray, image.width, image.height), frame++ * 60);
      if (answer.text) return { text: answer.text, frames: frame, partial };
      partial = answer.partial || partial;
    }
  }
  return { text: null, frames: frame, partial };
}

async function main() {
  const decode = await loadWorker();
  // Linear and matrix codes read on every frame's first, cheap look.
  for (let index = 0; index < 4; index++) {
    const linear = await decode(code128());
    assert.deepEqual([linear.results[0]?.text, linear.stage], ["001234567890", "fast"]);
    assert.equal((await decode(qr())).results[0]?.text, "warehouse-test-001");
  }
  // Nothing barcode-like: only the cheap look runs, and the page is told nothing is in view.
  const blank = rgba(950, 317);
  for (let i = 0; i < blank.data.length; i += 4) blank.data[i] = blank.data[i + 1] = blank.data[i + 2] = 170 + (i * 7919) % 13;
  assert.deepEqual(await decode(blank).then(({ results, present, stage }) => [results.length, present, stage]), [0, false, "idle"]);
  // Focus blur wider than a narrow bar defeats plain zxing and recovery; the sharpened row strip reads it at once.
  const blurred = scene("53168KFM902", { width: 950, height: 317, module: 3, blur: 2, noise: 6 });
  const unblurred = await decode(toRGBA(blurred));
  assert.deepEqual([unblurred.results[0]?.text, unblurred.stage], ["53168KFM902", "sharpened"]);

  // Android's native reader (scripted over bar texture that holds no readable code): a linear code wins
  // over a QR on the same label; Code 39 needs a second agreeing native frame within 1 s; QR reads at once.
  const script = [];
  const nativeDecode = await loadWorker(scriptedDetector(script));
  const texture = randomBars(7);
  const nativeRead = async (codes, time) => { script.push(codes); return (await nativeDecode(texture, time)).results[0]; };
  assert.equal(await nativeRead([["qr_code", "259190000061701;APC;13101-KFL-505"], ["code_39", "13101-KFL-505"]], 0),
               undefined, "an unconfirmed Code 39 is not accepted");
  const confirmed = await nativeRead([["code_39", "13101-KFL-505"]], 800);
  assert.deepEqual([confirmed?.text, confirmed?.format, confirmed?.source], ["13101-KFL-505", "Code 39", "native"]);
  assert.equal((await nativeRead([["qr_code", "warehouse-test-001"]], 5000))?.text, "warehouse-test-001");
  assert.equal(await nativeRead([["code_39", "45440KZLE01"]], 6000), undefined);
  assert.equal(await nativeRead([["code_39", "45440KZLE01"]], 7100), undefined, "1.1 s later is not a confirmation");
  assert.equal(script.length, 0, "the native reader runs whenever edges are in view");
  // The JS Code 39 table/generator agrees with ZXing, so recovery tests are not self-consistent fiction.
  const clean = await decode(toRGBA(scene(PART, { width: 1280, height: 427, module: 4 })));
  assert.deepEqual([clean.results[0]?.text, clean.results[0]?.format], [PART, "Code 39"]);
  assert.equal((await decode(rgba(640, 360))).results.length, 0, "blank frame must not decode");

  // Damage ZXing cannot read in any single frame: a missing chunk that moves between frames.
  const moving = [.38, .62, .40, .60].map((cx, i) => ({ glare: [{ cx, cy: .5, rx: .08, ry: .9 }], seed: i + 2 }));
  let recovered = null;
  for (let frame = 0; frame < 8 && !recovered; frame++) {
    const answer = await decode(toRGBA(scene(PART, moving[frame % 4])), frame * 60);
    if (answer.results.length) {
      assert.notEqual(answer.results[0].source, "zxing", "this damage should need recovery");
      recovered = answer.results[0];
    }
  }
  assert.deepEqual([recovered?.text, recovered?.source], [PART, "recovery"]);

  // One character hidden in every frame: never guessed; offered as a catalog pattern once stable.
  let partial = null;
  for (let frame = 0; frame < 16 && !partial; frame++) {
    const glare = [{ cx: .5, cy: .5, rx: .025, ry: .9 }];
    const answer = await decode(toRGBA(scene(PART, { glare, seed: frame + 1 })), frame * 60);
    assert.equal(answer.results.length, 0);
    partial = answer.partial;
  }
  assert.equal(partial, "53205K?L640ZC");

  const scenarios = {
    "noise and blur": [{ blur: 2, noise: 12 }],
    "tilt 12 degrees": [{ angle: 12 }],
    "tilt 25 degrees (no line sees both ends)": [{ angle: 25, module: 4 }],
    "shadow and tilt": [{ angle: -8, shadow: .7 }],
    "curved packaging": [{ curve: .75, module: 4.5 }],
    "curved with bowed bars": [{ curve: .6, bend: 12 }],
    "perspective": [{ perspective: .2 }],
    "ink spread": [{ ink: .35, blur: 1 }],
    "low contrast": [{ contrast: .25, noise: 6 }],
    "2.5 px modules": [{ module: 2.5, noise: 4 }],
    "upside down": [{ angle: 180 }],
    "glare patch on some rows": [{ glare: [{ cx: .5, cy: .4, rx: .1, ry: .25 }], angle: 6 }],
    "curved, glare moves between frames": [.45, .57, .43, .55].map((cx, i) =>
      ({ curve: .6, glare: [{ cx, cy: .5, rx: .06, ry: .9 }], noise: 6, seed: i + 7 })),
  };
  for (const [name, frames] of Object.entries(scenarios)) {
    assert.equal(recover(frames).text, PART, name);
  }
  assert.equal(recover([{ glare: [{ cx: .5, cy: .5, rx: .07, ry: .8 }] }]).text, null,
               "three or more characters missing in every frame cannot be recovered and must not be guessed");

  // Specials, short and long codes.
  for (const text of ["AB-12.3 $/+%", "X1", "1234567890ABCDEFGHIJ"]) {
    const session = new R39.Session();
    let got = null;
    for (let frame = 0; frame < 4 && !got; frame++) {
      const image = scene(text, { module: text.length > 15 ? 3.2 : 5, noise: 5, seed: frame + 1 });
      got = session.add(R39.scanFrame(image.gray, image.width, image.height), frame * 60).text;
    }
    assert.equal(got, text);
  }

  // No Code 39 from a Code 128 label or random bar texture.
  for (const image of [code128(), randomBars(1)]) {
    const gray = new Uint8ClampedArray(image.width * image.height);
    for (let i = 0; i < gray.length; i++) gray[i] = image.data[i * 4];
    const session = new R39.Session();
    for (let frame = 0; frame < 20; frame++) {
      const answer = session.add(R39.scanFrame(gray, image.width, image.height), frame * 60);
      assert.equal(answer.text, undefined);
      assert.equal(answer.partial, undefined);
    }
  }

  // Random heavy damage: misses are allowed, wrong reads are not (Code 39 has no check digit).
  const random = rng(42), letters = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  let correct = 0, wrong = 0, time = 0, frames = 0;
  for (let trial = 0; trial < 40; trial++) {
    let text = "";
    for (let i = 6 + Math.floor(random() * 9); i > 0; i--) text += letters[Math.floor(random() * letters.length)];
    const base = { module: 2.6 + random() * 3, angle: (random() - .5) * 30, curve: random() < .5 ? random() * .7 : 0,
                   blur: Math.floor(random() * 3), noise: random() * 25, contrast: .25 + random() * .75,
                   shadow: random() * .7, width: 1280, height: 427 };
    const session = new R39.Session();
    let got = null;
    for (let frame = 0; frame < 6 && !got; frame++) {
      const glare = random() < .6
        ? [{ cx: .3 + random() * .4, cy: .2 + random() * .6, rx: .02 + random() * .08, ry: .1 + random() * .8 }] : [];
      const image = scene(text, { ...base, glare, seed: trial * 10 + frame, offsetX: (random() - .5) * 20 });
      const started = performance.now();
      const observation = R39.scanFrame(image.gray, image.width, image.height);
      time += performance.now() - started;
      frames++;
      got = session.add(observation, frame * 60).text;
    }
    if (got === text) correct++;
    else if (got) wrong++;
  }
  assert.equal(wrong, 0, "random damage produced a wrong Code 39 read");
  assert.ok(correct >= 28, `recovery rate dropped: ${correct}/40`);

  // Every strong-try variant, through the real worker, on single heavily damaged frames: never a wrong code.
  const harsh = rng(99);
  let strongReads = 0;
  for (let trial = 0; trial < 30; trial++) {
    let text = "";
    for (let i = 11; i > 0; i--) text += letters[Math.floor(harsh() * letters.length)];
    const image = scene(text, { width: 950, height: 317, module: 2 + harsh() * 2.5, angle: (harsh() - .5) * 30,
      curve: harsh() < .5 ? harsh() * .7 : 0, blur: Math.floor(harsh() * 4), noise: harsh() * 30,
      contrast: .2 + harsh() * .8, shadow: harsh() * .7, ink: harsh() < .3 ? harsh() * .35 : 0, seed: trial + 1,
      glare: harsh() < .6 ? [{ cx: .2 + harsh() * .6, cy: .2 + harsh() * .6, rx: .02 + harsh() * .1, ry: .1 + harsh() * .8 }] : [] });
    // Frames 5 s apart: no multi-frame recovery, only single-frame variants can answer.
    const got = (await decode(toRGBA(image), 1e7 + trial * 5000)).results[0]?.text;
    if (got) { assert.equal(got, text, "a strong-try variant misread a damaged label"); strongReads++; }
  }
  for (let seed = 2; seed < 6; seed++) {
    assert.equal((await decode(randomBars(seed), 2e7 + seed * 5000)).results.length, 0, "bar texture read as a code");
  }

  // ---- Catalog checks ----
  const neighbours = ["53205KTL640ZD", "53206KTL640ZC", "45440KZLE01"];
  assert.ok(new R39.Catalog([PART]).has(" 53205-ktl-640zc "), "catalog IDs use the stored SKU spelling");
  // One character hidden in every frame: completed only when exactly one catalog ID fits, never when
  // another ID differs at the unseen character, and never to a neighbour when the product is missing.
  const hidden = [];
  for (let frame = 0; frame < 8; frame++) {
    hidden.push(scene(PART, { glare: [{ cx: .5, cy: .5, rx: .025, ry: .9 }], seed: frame + 1 }));
  }
  const completion = ids => {
    const session = new R39.Session({ accept: () => false });
    let completed = null;
    hidden.forEach((image, frame) => {
      session.add(R39.scanFrame(image.gray, image.width, image.height), frame * 60);
      completed ||= new R39.Catalog(ids).complete(session.lattice());
    });
    return completed;
  };
  assert.equal(completion([PART, ...neighbours]), PART);
  assert.equal(completion([PART, "53205KXL640ZC", ...neighbours]), null, "two IDs fit the unseen character");
  assert.equal(completion(neighbours), null, "a product missing from the catalog is not replaced by a neighbour");
  // A refused complete read keeps its votes: nothing accepted, the lattice still holds the characters.
  const refusing = new R39.Session({ accept: () => false });
  const plain = scene(PART, { seed: 3 });
  for (let frame = 0; frame < 3; frame++) {
    assert.equal(refusing.add(R39.scanFrame(plain.gray, plain.width, plain.height), frame * 60).text, undefined);
  }
  assert.ok(refusing.lattice().start.get(0)?.get("5")?.weight >= 2.5);

  // The worker with a catalog from the laptop.
  const checked = await loadWorker();
  checked.send({ type: "catalog", ids: [PART, ...neighbours] });
  // A clean Code 39 outside the catalog needs a second frame; catalog IDs read at once.
  const foreign = toRGBA(scene("X1Y2Z3", { width: 950, height: 317, module: 4 }));
  assert.deepEqual(await checked(foreign, 3e7).then(a => [a.results.length, a.stage, a.present]), [0, "unconfirmed", true]);
  assert.equal((await checked(foreign, 3e7 + 150)).results[0]?.text, "X1Y2Z3");
  assert.equal((await checked(toRGBA(scene(PART, { width: 1280, height: 427, module: 4 })), 3.1e7)).results[0]?.text, PART);
  checked.send({ type: "reset" });
  let viaCatalog = null;
  for (let frame = 0; frame < hidden.length && !viaCatalog; frame++) {
    viaCatalog = (await checked(toRGBA(hidden[frame]), 3.2e7 + frame * 150)).results[0] || null;
  }
  assert.deepEqual([viaCatalog?.text, viaCatalog?.format, viaCatalog?.source], [PART, "Code 39 · catalog", "catalog"]);

  // Real labels on plastic bags (wrinkles, shear, glare, damage): never a wrong product.
  const { cases: photos, catalog: nearby } = realLabels();
  const real = [];
  for (const missing of [false, true]) {
    const worker = await loadWorker();
    for (const label of photos) {
      // With the product missing from the catalog, nothing may be read as one of its neighbours.
      worker.send({ type: "catalog", ids: missing ? nearby.filter(id => id !== label.expected) : nearby });
      worker.send({ type: "reset" });
      let got = null;
      for (let frame = 0; frame < 12 && !got; frame++) {
        got = (await worker(handheld(label, frame), 4e7 + frame * 150 + label.width * 1e4)).results[0]?.text || null;
      }
      if (got) assert.equal(got, missing ? undefined : label.expected, `${label.tag}: wrong product`);
      if (!missing) real.push(`${label.tag} ${got ? "read" : "-"}`);
    }
  }
  const realReads = real.filter(line => line.endsWith("read")).length;
  assert.ok(realReads >= 3, `real labels read: ${real.join(", ")}`);

  const started = performance.now();
  for (let index = 0; index < 15; index++) await decode(code128(), index * 66);
  console.log(`Decoder checks passed. Random damage: ${correct}/40 recovered, 0 wrong; strong try ${strongReads}/30 single frames, 0 wrong; real labels ${realReads}/${photos.length} (${real.join(", ")}), 0 wrong; `
    + `recovery ${(time / frames).toFixed(1)} ms per 1280x427 frame; 15 worker frames `
    + `${(performance.now() - started).toFixed(0)} ms (this laptop, not phone FPS).`);
}

if (require.main === module) main().catch(error => { console.error(error); process.exitCode = 1; });
module.exports = { code128, qr };

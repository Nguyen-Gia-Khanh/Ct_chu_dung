/* Phone decoder tests: the real worker (zxing-wasm + Code 39 recovery) and synthetic damaged labels. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
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

/** Evaluate the actual browser worker. Only transport/loading are adapted; there is no BarcodeDetector. */
async function loadWorker() {
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
  });
  sandbox.self = sandbox;
  sandbox.importScripts = (...urls) => urls.forEach(url =>
    vm.runInContext(fs.readFileSync(path.join(staticRoot, url), "utf8"), sandbox, { filename: url }));
  let message = new Promise(resolve => { resolveMessage = resolve; });
  vm.runInContext(fs.readFileSync(path.join(staticRoot, "decoder-worker.js"), "utf8"), sandbox);
  const ready = await message;
  assert.equal(ready.type, "ready", ready.message);
  assert.equal(ready.native, false);
  let id = 0;
  return async (image, time = 0) => {
    message = new Promise(resolve => { resolveMessage = resolve; });
    sandbox.onmessage({ data: { type: "frame", id: ++id, buffer: image.data.slice().buffer,
                                width: image.width, height: image.height, time } });
    const response = await message;
    assert.equal(response.type, "result", response.message);
    return response;
  };
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
  // Variants rotate per frame: linear codes read on every variant, matrix codes within two frames.
  for (let index = 0; index < 4; index++) {
    assert.equal((await decode(code128())).results[0]?.text, "001234567890");
  }
  for (let index = 0; index < 4; index++) {
    const first = await decode(qr());
    const text = first.results[0]?.text || (await decode(qr())).results[0]?.text;
    assert.equal(text, "warehouse-test-001");
  }
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

  const started = performance.now();
  for (let index = 0; index < 15; index++) await decode(code128(), index * 66);
  console.log(`Decoder checks passed. Random damage: ${correct}/40 recovered, 0 wrong; `
    + `recovery ${(time / frames).toFixed(1)} ms per 1280x427 frame; 15 worker frames `
    + `${(performance.now() - started).toFixed(0)} ms (this laptop, not phone FPS).`);
}

if (require.main === module) main().catch(error => { console.error(error); process.exitCode = 1; });
module.exports = { code128, qr };

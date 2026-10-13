/* Runnable worker smoke test; generated reference labels use ReportLab encoding. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { performance } = require("node:perf_hooks");
const { preparePixels } = require("../barcode_web/static/processing.js");
const staticRoot = path.resolve(__dirname, "../barcode_web/static");

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

async function main() {
  const flat = rgba(3, 3); flat.data.fill(100);
  assert.equal(preparePixels(flat.data, 3, 3, true).data[16], 100, "kernel preserves a flat region");
  const edge = rgba(3, 3); edge.data.fill(100);
  edge.data[16] = edge.data[17] = edge.data[18] = 150;
  assert.equal(preparePixels(edge.data, 3, 3, true).data[16], 200, "kernel sharpens center pixel");
  assert.equal(edge.data[19], 255, "alpha stays opaque");

  // Evaluate the actual browser worker and IIFE. Only transport/loading are adapted.
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
  sandbox.importScripts = (...urls) => urls.forEach(url =>
    vm.runInContext(fs.readFileSync(path.join(staticRoot, url), "utf8"), sandbox, { filename: url }));
  let message = new Promise(resolve => { resolveMessage = resolve; });
  vm.runInContext(fs.readFileSync(path.join(staticRoot, "worker.js"), "utf8"), sandbox);
  assert.equal((await message).type, "ready");

  async function decode(image, sharpen) {
    message = new Promise(resolve => { resolveMessage = resolve; });
    sandbox.onmessage({ data: { buffer: image.data.slice().buffer, width: image.width, height: image.height, sharpen } });
    const response = await message;
    assert.equal(response.type, "result", response.message);
    return response;
  }
  for (const sharpen of [false, true]) {
    assert.equal((await decode(code128(), sharpen)).results[0]?.text, "001234567890");
    assert.equal((await decode(qr(), sharpen)).results[0]?.text, "warehouse-test-001");
  }
  assert.equal((await decode(rgba(640, 360), true)).results.length, 0, "blank frame must not decode");
  const started = performance.now();
  for (let index = 0; index < 15; index++) await decode(code128(), index % 2 === 0);
  console.log(`Worker checks passed; 15 synthetic Code 128 frames: ${(performance.now() - started).toFixed(0)} ms on this laptop (not phone FPS).`);
}

if (require.main === module) main().catch(error => { console.error(error); process.exitCode = 1; });
module.exports = { code128, qr };

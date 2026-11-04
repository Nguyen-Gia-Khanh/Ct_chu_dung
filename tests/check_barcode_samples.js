/* Replay frames saved with the phone's save-frame button through the phone decoder worker.
 *
 *   node tests/check_barcode_samples.js [samples folder] [--no-catalog]
 *
 * Each burst (6 frames, 150 ms apart) is one decoding sequence. Optional `labels.json` in the samples
 * folder maps a burst ID to its true product ID (or null for no barcode) to count correct and wrong
 * reads. Catalog IDs come from data/warehouse_locations.db (read-only), like the phone gets them. */
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const zlib = require("node:zlib");
const root = path.resolve(__dirname, "..");
const staticRoot = path.join(root, "barcode_web/static");
const folder = path.resolve(process.argv.slice(2).find(arg => !arg.startsWith("--")) || path.join(root, "data/barcode_web/samples"));
const withCatalog = !process.argv.includes("--no-catalog");

/** 8-bit, non-interlaced PNG (what canvas.toBlob writes) to RGBA. */
function readPng(file) {
  const bytes = fs.readFileSync(file);
  let offset = 8, width = 0, height = 0, channels = 0;
  const chunks = [];
  while (offset < bytes.length) {
    const length = bytes.readUInt32BE(offset), kind = bytes.toString("ascii", offset + 4, offset + 8);
    const body = bytes.subarray(offset + 8, offset + 8 + length);
    if (kind === "IHDR") {
      width = body.readUInt32BE(0); height = body.readUInt32BE(4);
      channels = { 0: 1, 2: 3, 4: 2, 6: 4 }[body[9]];
      if (body[8] !== 8 || body[12] || !channels) throw new Error(`${file}: unsupported PNG`);
    }
    if (kind === "IDAT") chunks.push(body);
    offset += 12 + length;
  }
  const raw = zlib.inflateSync(Buffer.concat(chunks)), stride = width * channels;
  const rgba = new Uint8ClampedArray(width * height * 4);
  let previous = new Uint8Array(stride), line = new Uint8Array(stride);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)], source = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    for (let x = 0; x < stride; x++) {
      const a = x >= channels ? line[x - channels] : 0, b = previous[x], c = x >= channels ? previous[x - channels] : 0;
      const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
      const predicted = [0, a, b, (a + b) >> 1, pa <= pb && pa <= pc ? a : pb <= pc ? b : c][filter];
      line[x] = source[x] + predicted;
    }
    for (let x = 0; x < width; x++) {
      const o = (y * width + x) * 4, s = x * channels, color = channels >= 3;
      rgba[o] = line[s]; rgba[o + 1] = line[s + (color ? 1 : 0)]; rgba[o + 2] = line[s + (color ? 2 : 0)]; rgba[o + 3] = 255;
    }
    [previous, line] = [line, previous];
  }
  return { data: rgba, width, height };
}

function catalogIds() {
  const { DatabaseSync } = require("node:sqlite");
  const database = new DatabaseSync(path.join(root, "data/warehouse_locations.db"), { readOnly: true });
  try { return database.prepare("SELECT product_id FROM catalog_products").all().map(row => row.product_id); }
  finally { database.close(); }
}

async function main() {
  const details = fs.readdirSync(folder).filter(name => name.endsWith(".json") && name !== "labels.json")
    .map(name => ({ ...JSON.parse(fs.readFileSync(path.join(folder, name), "utf8")), png: path.join(folder, name.replace(/\.json$/, ".png")) }));
  const bursts = new Map();
  for (const frame of details.sort((a, b) => a.received_at.localeCompare(b.received_at))) {
    if (!bursts.has(frame.burst)) bursts.set(frame.burst, []);
    bursts.get(frame.burst).push(frame);
  }
  const labelsFile = path.join(folder, "labels.json");
  const labels = fs.existsSync(labelsFile) ? JSON.parse(fs.readFileSync(labelsFile, "utf8")) : {};
  // The real worker, in this process (as fast as a browser worker; no DOM or BarcodeDetector).
  let deliver;
  Object.assign(globalThis, {
    self: globalThis, postMessage: message => deliver?.(message),
    fetch: async () => new Response(fs.readFileSync(path.join(staticRoot, "vendor/zxing_reader.wasm")),
                                    { headers: { "Content-Type": "application/wasm" } }),
    importScripts: (...urls) => urls.forEach(url => vm.runInThisContext(fs.readFileSync(path.join(staticRoot, url), "utf8"))),
  });
  const ready = new Promise(resolve => { deliver = resolve; });
  vm.runInThisContext(fs.readFileSync(path.join(staticRoot, "decoder-worker.js"), "utf8"));
  await ready;
  if (withCatalog) globalThis.onmessage({ data: { type: "catalog", ids: catalogIds() } });
  const decode = (image, id, time) => new Promise(resolve => {
    deliver = resolve;
    globalThis.onmessage({ data: { type: "frame", id, buffer: image.data.buffer, width: image.width, height: image.height, time } });
  });
  let id = 0, correct = 0, wrong = 0, unread = 0, frames = 0, milliseconds = 0;
  for (const [index, [burst, sequence]] of [...bursts].entries()) {
    globalThis.onmessage({ data: { type: "reset" } });
    let read = null;
    const stages = [];
    for (const [frame, detail] of sequence.entries()) {
      const answer = await decode(readPng(detail.png), ++id, 1e7 * (index + 1) + frame * 150);
      frames++; milliseconds += answer.milliseconds; stages.push(answer.stage);
      if (answer.results.length) { read = { ...answer.results[0], frame: frame + 1, stage: answer.stage }; break; }
    }
    const truth = labels[burst];
    const verdict = truth === undefined ? (read ? "read" : "-") : !read ? (truth ? "UNREAD" : "ok") : read.text === truth ? "OK" : "WRONG";
    if (verdict === "OK") correct++;
    if (verdict === "WRONG") wrong++;
    if (verdict === "UNREAD") unread++;
    console.log(`${String(index).padStart(3)} ${burst} zoom ${sequence[0].zoom ?? "-"}  ${verdict.padEnd(6)} `
      + (read ? `${read.text} (${read.format}) frame ${read.frame} via ${read.stage}` : stages.join(",")));
  }
  console.log(`\n${bursts.size} bursts, ${frames} frames, ${(milliseconds / frames).toFixed(0)} ms per frame on this computer, `
    + `catalog ${withCatalog ? "on" : "off"}` + (Object.keys(labels).length ? `: ${correct} correct, ${wrong} WRONG, ${unread} unread` : ""));
  if (wrong) process.exitCode = 1;
}

main().catch(error => { console.error(error); process.exitCode = 1; });

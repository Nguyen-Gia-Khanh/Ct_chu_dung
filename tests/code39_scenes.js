/* Synthetic Code 39 strips with camera/packaging distortions for the phone decoder tests. */
const R39 = require("../barcode_web/static/robust39.js");

function modules39(text, ratio = 2.5) {
  // Returns [{x0, x1}] dark runs in module units, plus total width (with 10X quiet zones).
  const runs = [];
  let x = 10;
  for (const char of `*${text}*`) {
    const code = char === "*" ? R39.ASTERISK : R39.ENCODINGS[R39.ALPHABET.indexOf(char)];
    if (code === undefined) throw new Error(`Not Code 39: ${char}`);
    for (let i = 0; i < 9; i++) {
      const w = code & (1 << (8 - i)) ? ratio : 1;
      if (i % 2 === 0) runs.push([x, x + w]);
      x += w;
    }
    x += 1;
  }
  return { runs, width: x - 1 + 10 };
}

function rng(seed) {
  let s = seed >>> 0 || 1;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

/**
 * Render a barcode into a gray strip. opts: width, height, module (px), ratio, angle (deg),
 * curve (0..1 cylinder strength), bend (px of bar bowing), perspective, blur (px box radius),
 * shadow (0..1), glare [{cx, cy, rx, ry}] in 0..1 strip coords, noise (levels), contrast, offsetX/Y.
 */
function scene(text, opts = {}) {
  const o = { width: 1600, height: 533, module: 5, ratio: 2.5, angle: 0, curve: 0, bend: 0, perspective: 0,
              blur: 0, shadow: 0, glare: [], noise: 0, contrast: 1, offsetX: 0, offsetY: 0, barHeight: .45,
              seed: 1, ink: 0, ...opts };
  const { runs, width: total } = modules39(text, o.ratio);
  const random = rng(o.seed);
  const W = o.width, H = o.height;
  const cx = W / 2 + o.offsetX, cy = H / 2 + o.offsetY;
  const half = total * o.module / 2;
  const R = o.curve ? half / Math.sin(Math.min(1.45, o.curve * 1.45)) : 0;
  const cos = Math.cos(o.angle * Math.PI / 180), sin = Math.sin(o.angle * Math.PI / 180);
  const barHalf = H * o.barHeight / 2;
  const dark = 255 - 200 * o.contrast;
  const gray = new Uint8ClampedArray(W * H);
  const sub = 4;
  // Precompute a fast lookup from module coordinate to ink.
  function inkAt(u) {
    let lo = 0, hi = runs.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (u < runs[mid][0] - o.ink) hi = mid - 1;
      else if (u >= runs[mid][1] + o.ink) lo = mid + 1;
      else return true;
    }
    return false;
  }
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      let sum = 0;
      for (let s = 0; s < sub; s++) {
        const px = x + (s + .5) / sub - .5;
        // Screen -> label plane: undo tilt.
        let dx = (px - cx) * cos + (y - cy) * sin;
        const dy = -(px - cx) * sin + (y - cy) * cos;
        if (o.perspective) dx = dx / (1 - o.perspective * dx / half);
        let u;
        if (R) {
          if (Math.abs(dx) >= R) { sum += 255; continue; }
          u = R * Math.asin(dx / R);
        } else u = dx;
        u += o.bend * (dy / barHalf) ** 2;
        const m = (u + half) / o.module;
        const inside = Math.abs(dy) <= barHalf && m >= 0 && m <= total;
        sum += inside && inkAt(m) ? dark : 255;
      }
      gray[y * W + x] = sum / sub;
    }
  }
  let out = Float32Array.from(gray);
  if (o.blur) {
    const r = o.blur, tmp = new Float32Array(W * H);
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      let s = 0, c = 0;
      for (let k = -r; k <= r; k++) { const xx = x + k; if (xx >= 0 && xx < W) { s += out[y * W + xx]; c++; } }
      tmp[y * W + x] = s / c;
    }
    out = tmp;
  }
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const i = y * W + x;
    let v = out[i];
    if (o.shadow) v *= 1 - o.shadow + o.shadow * (x / W);
    for (const g of o.glare) {
      const ex = (x / W - g.cx) / g.rx, ey = (y / H - g.cy) / g.ry;
      const d = ex * ex + ey * ey;
      if (d < 1) v = v + (250 - v) * Math.min(1, 1.6 * (1 - d));
    }
    if (o.noise) v += (random() * 2 - 1) * o.noise;
    gray[i] = v;
  }
  return { gray, width: W, height: H };
}

function toRGBA({ gray, width, height }) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0, p = 0; i < gray.length; i++, p += 4) { data[p] = data[p + 1] = data[p + 2] = gray[i]; data[p + 3] = 255; }
  return { data, width, height };
}

module.exports = { scene, toRGBA, modules39, rng };

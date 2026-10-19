/* Damaged, curved and partial Code 39 recovery. Pure JS: runs in the decoder worker and Node tests.
 *
 * ZXing needs one clean scanline. Here every scanline contributes fragments instead:
 * sub-pixel edges (no global threshold), each character normalised by its own bar/space widths
 * (smooth stretch from curved packaging cancels out), and quiet-zone-checked start/stop anchors.
 * Characters vote for a slot counted from the start or the stop, across scanlines and frames,
 * so the left half from one frame and the right half from another can complete one code.
 * Code 39 has no check digit, so acceptance needs agreement from several lines and frames. */
(function (root) {
  "use strict";
  const ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-. $/+%";
  // ZXing's narrow/wide patterns: first element (a bar) is the most significant bit.
  const ENCODINGS = [
    0x034, 0x121, 0x061, 0x160, 0x031, 0x130, 0x070, 0x025, 0x124, 0x064,
    0x109, 0x049, 0x148, 0x019, 0x118, 0x058, 0x00D, 0x10C, 0x04C, 0x01C,
    0x103, 0x043, 0x142, 0x013, 0x112, 0x052, 0x007, 0x106, 0x046, 0x016,
    0x181, 0x0C1, 0x1C0, 0x091, 0x190, 0x0D0, 0x085, 0x184, 0x0C4, 0x0A8,
    0x0A2, 0x08A, 0x02A,
  ];
  const PATTERNS = new Map(ENCODINGS.map((pattern, index) => [pattern, ALPHABET[index]]));
  PATTERNS.set(0x094, "*");

  const MIN_WIDE_RATIO = 1.4;   // Spec is 2:1 to 3:1; blur and ink spread shrink it.
  const QUIET_ZONE = 3.5;       // Start/stop need this many narrow widths of blank space.
  const MIN_SLOT_VOTES = 2.5;   // Weighted scanline votes for one character slot.
  // Lines in one frame share its defects; a second frame is required for every character.
  // (600 heavy-distortion trials: single-frame acceptance gave 2 wrong reads, this gave 0.)
  const MIN_FRAMES = 2;

  function classify(widths, k) {
    const bars = [widths[k], widths[k + 2], widths[k + 4], widths[k + 6], widths[k + 8]];
    const spaces = [widths[k + 1], widths[k + 3], widths[k + 5], widths[k + 7]];
    const b = bars.slice().sort((x, y) => y - x);
    const s = spaces.slice().sort((x, y) => y - x);
    // Bars and spaces are classified separately so ink spread cannot swap them.
    const normal = Math.min(b[1] / b[2], s[0] / s[1]);
    const special = b[0] / b[4] < 1.6 ? s[2] / s[3] : 0;   // $ / + %: three wide spaces
    let barCut, spaceCut, quality;
    if (normal >= special) {
      if (b[2] / b[4] > 2 || b[0] / b[1] > 2 || s[1] / s[3] > 2.5) return null;
      barCut = (b[1] + b[2]) / 2; spaceCut = (s[0] + s[1]) / 2; quality = normal;
    } else {
      barCut = Infinity; spaceCut = (s[2] + s[3]) / 2; quality = special;
    }
    if (!(quality >= MIN_WIDE_RATIO)) return null;
    let pattern = 0, wide = 0;
    for (let i = 0; i < 9; i++) {
      if (widths[k + i] > (i % 2 ? spaceCut : barCut)) { pattern |= 1 << (8 - i); wide++; }
    }
    const char = wide === 3 ? PATTERNS.get(pattern) : undefined;
    if (!char) return null;
    const narrow = [];
    for (let i = 0; i < 9; i++) if (!(pattern & (1 << (8 - i)))) narrow.push(widths[k + i]);
    narrow.sort((x, y) => x - y);
    return { char, confidence: Math.min(1, (quality - 1) / 1.2), narrow: narrow[3] };
  }

  /** Alternating sub-pixel edges from intensity derivative extrema; relative to local contrast. */
  function findEdges(profile) {
    const n = profile.length;
    const smooth = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      smooth[i] = (profile[Math.max(0, i - 1)] + 2 * profile[i] + profile[Math.min(n - 1, i + 1)]) / 4;
    }
    const slope = new Float32Array(n), magnitude = new Float32Array(n);
    for (let i = 1; i < n - 1; i++) {
      slope[i] = (smooth[i + 1] - smooth[i - 1]) / 2;
      magnitude[i] = Math.abs(slope[i]);
    }
    const local = slidingMax(magnitude, Math.max(12, Math.round(n / 48)));
    const positions = [], signs = [], strengths = [];
    for (let i = 2; i < n - 2; i++) {
      const m = magnitude[i];
      if (m < 3 || m < .2 * local[i] || m < magnitude[i - 1] || m <= magnitude[i + 1]) continue;
      const sign = slope[i] < 0 ? -1 : 1;
      const denominator = magnitude[i - 1] - 2 * m + magnitude[i + 1];
      const offset = denominator < 0 ? (magnitude[i - 1] - magnitude[i + 1]) / (2 * denominator) : 0;
      const last = signs.length - 1;
      if (last >= 0 && signs[last] === sign) {
        // Same direction twice: keep the stronger edge of the pair.
        if (m > strengths[last]) { positions[last] = i + offset; strengths[last] = m; }
        continue;
      }
      positions.push(i + offset); signs.push(sign); strengths.push(m);
    }
    return { positions, signs };
  }

  function slidingMax(values, radius) {
    const n = values.length, size = 2 * radius + 1;
    const prefix = new Float32Array(n), suffix = new Float32Array(n), out = new Float32Array(n);
    for (let i = 0; i < n; i++) prefix[i] = i % size === 0 ? values[i] : Math.max(prefix[i - 1], values[i]);
    for (let i = n - 1; i >= 0; i--) {
      suffix[i] = (i === n - 1 || (i + 1) % size === 0) ? values[i] : Math.max(suffix[i + 1], values[i]);
    }
    for (let i = 0; i < n; i++) {
      out[i] = Math.max(suffix[Math.max(0, i - radius)], prefix[Math.min(n - 1, i + radius)]);
    }
    return out;
  }

  /** Undo stretch that changes across a character (cylinder edges, perspective), using neighbour
   *  pitches, then re-read it. A character that changes or fails under correction is doubtful. */
  function destretch(chain, widths, starts) {
    const scales = chain.map(c => c.width);
    for (let i = 0; i < chain.length; i++) {
      const c = chain[i];
      const left = i > 0 ? (scales[i - 1] + scales[i]) / 2 : scales[i] - (scales[i + 1] - scales[i]) / 2;
      const right = i < chain.length - 1 ? (scales[i] + scales[i + 1]) / 2 : scales[i] + (scales[i] - scales[i - 1]) / 2;
      if (!(left > 0 && right > 0)) continue;
      const corrected = new Float32Array(9);
      for (let e = 0; e < 9; e++) {
        const middle = starts[c.k + e] + widths[c.k + e] / 2;
        const f = Math.min(1, Math.max(0, (middle - c.start) / c.width));
        corrected[e] = widths[c.k + e] * scales[i] / (left + (right - left) * f);
      }
      const again = classify(corrected, 0);
      if (!again || again.char !== c.char) {
        c.confidence = 0;
        c.doubtful = true;
      } else c.confidence = Math.min(c.confidence, again.confidence);
    }
    return true;
  }

  function median(values) {
    const sorted = values.slice().sort((a, b) => a - b);
    return sorted[sorted.length >> 1];
  }

  /** Character chains in one reading direction; start/stop must touch a quiet zone. */
  function fragments(widths, isBar, starts, lead, trail) {
    const count = widths.length;
    const chars = new Array(count);
    for (let k = 0; k + 8 < count; k++) {
      if (!isBar[k]) continue;
      const found = classify(widths, k);
      if (found) chars[k] = { ...found, k, start: starts[k], width: starts[k + 9] - starts[k] };
    }
    const linked = (a, b) => {
      if (!a || !b) return false;
      const gap = widths[a.k + 9];
      const ratio = b.width / a.width;
      return gap < 3.5 * a.narrow && gap > .2 * a.narrow && ratio > .7 && ratio < 1.43;
    };
    const chains = [];
    for (let k = 0; k < count; k++) {
      if (!chars[k] || linked(chars[k - 10], chars[k])) continue;
      const chain = [chars[k]];
      while (linked(chain[chain.length - 1], chars[chain[chain.length - 1].k + 10])) {
        chain.push(chars[chain[chain.length - 1].k + 10]);
      }
      if (chain.length >= 3) destretch(chain, widths, starts);
      const first = chain[0].k, tail = chain[chain.length - 1];
      const before = first > 0 ? widths[first - 1] : lead;
      const after = tail.k + 9 < count ? widths[tail.k + 9] : trail;
      const text = chain.map(c => c.char).join("");
      const startAnchor = text[0] === "*" && before >= QUIET_ZONE * chain[0].narrow;
      const stopAnchor = text.length > (startAnchor ? 1 : 0) && text[text.length - 1] === "*"
        && after >= QUIET_ZONE * tail.narrow;
      // A '*' anywhere else means a reversed 'P' or a decode error; the direction is wrong.
      const inner = text.slice(startAnchor ? 1 : 0, stopAnchor ? -1 : undefined);
      if (inner.includes("*") || (text[0] === "*" && !startAnchor && chain.length > 1)) continue;
      const links = [];
      for (let i = 1; i < chain.length; i++) links.push(chain[i].start - chain[i - 1].start);
      chains.push({
        chars: chain, text, startAnchor, stopAnchor, first, last: tail.k + 8,
        rank: (startAnchor || stopAnchor ? 1000 : 0) + chain.length
          + chain.reduce((sum, c) => sum + c.confidence, 0) / chain.length,
        begin: chain[0].start, lastStart: tail.start, end: tail.start + tail.width,
        pitch: links.length ? median(links) : chain[0].width * 1.075,
      });
    }
    // Quiet-zone anchored, then longest chains first. A decode shifted by two elements can
    // still form valid characters; it loses to the chain it overlaps.
    chains.sort((a, b) => b.rank - a.rank);
    const taken = new Uint8Array(count), result = [];
    for (const chain of chains) {
      let overlap = false;
      for (let i = chain.first; i <= chain.last && !overlap; i++) overlap = taken[i] === 1;
      if (overlap) continue;
      taken.fill(1, chain.first, chain.last + 1);
      result.push(chain);
    }
    return result.sort((a, b) => a.begin - b.begin);
  }

  const weightOf = c => c.doubtful ? 0 : .5 + .5 * c.confidence;

  function vote(map, slot, char, weight) {
    if (slot < 0 || slot > 80 || !(weight > 0)) return;
    let slotVotes = map.get(slot);
    if (!slotVotes) map.set(slot, slotVotes = new Map());
    slotVotes.set(char, (slotVotes.get(char) || 0) + weight);
  }

  /** Turn one direction's fragments into slot votes (from the start, from the stop) and a length vote. */
  function collect(pieces, observation) {
    let used = false;
    for (let index = 0; index < pieces.length; index++) {
      const anchor = pieces[index];
      if (!anchor.startAnchor) continue;
      used = true;
      const data = anchor.chars.slice(1, anchor.stopAnchor ? -1 : undefined);
      data.forEach((c, slot) => vote(observation.start, slot, c.char, weightOf(c)));
      if (anchor.stopAnchor) {
        observation.lengths.set(data.length, (observation.lengths.get(data.length) || 0) + 1);
        continue;
      }
      // Fragments after a gap (glare, missing ink) on the same line, until the stop.
      let slot = data.length, previous = anchor;
      for (let next = index + 1; next < pieces.length && !pieces[next].startAnchor; next++) {
        const piece = pieces[next];
        const pitch = (previous.pitch + piece.pitch) / 2;
        const missing = Math.max(0, Math.round((piece.begin - previous.lastStart) / pitch) - 1);
        slot += missing;
        const weight = missing === 0 ? 1 : missing <= 3 ? .6 : .35;
        const chars = piece.chars.slice(0, piece.stopAnchor ? -1 : undefined);
        if (!piece.stopAnchor) {
          chars.forEach((c, i) => vote(observation.startNear, slot + i, c.char, weight * weightOf(c)));
        }
        slot += chars.length;
        if (piece.stopAnchor) {
          // Counted across a gap: an estimate, never as strong as one complete line.
          observation.estimates.set(slot, (observation.estimates.get(slot) || 0) + weight);
          break;
        }
        previous = piece;
      }
    }
    for (let index = pieces.length - 1; index >= 0; index--) {
      const anchor = pieces[index];
      if (!anchor.stopAnchor) continue;
      used = true;
      if (anchor.startAnchor) continue;   // Full read: already counted from the start.
      const data = anchor.chars.slice(0, -1);
      data.forEach((c, i) => vote(observation.end, data.length - 1 - i, c.char, weightOf(c)));
      // Unanchored fragments before the stop, when no start anchor precedes them.
      let slot = data.length, previous = anchor;
      for (let back = index - 1; back >= 0 && !pieces[back].stopAnchor && !pieces[back].startAnchor; back--) {
        const piece = pieces[back];
        if (pieces.slice(0, back).some(p => p.startAnchor)) break;
        const pitch = (previous.pitch + piece.pitch) / 2;
        const missing = Math.max(0, Math.round((previous.begin - piece.lastStart) / pitch) - 1);
        slot += missing;
        const weight = missing === 0 ? 1 : missing <= 3 ? .6 : .35;
        piece.chars.forEach((c, i) => vote(observation.endNear, slot + piece.chars.length - 1 - i, c.char,
                                           weight * weightOf(c)));
        slot += piece.chars.length;
        previous = piece;
      }
    }
    return used;
  }

  function estimateAngle(gray, width, height) {
    const bins = new Float64Array(91);
    for (let y = 2; y < height - 2; y += 3) {
      for (let x = 2; x < width - 2; x += 3) {
        const i = y * width + x;
        const gx = gray[i + 1] - gray[i - 1], gy = gray[i + width] - gray[i - width];
        const strength = gx * gx + gy * gy;
        if (strength < 400 || Math.abs(gy) > Math.abs(gx)) continue;
        bins[Math.round(Math.atan(gy / gx) * 180 / Math.PI) + 45] += Math.sqrt(strength);
      }
    }
    let best = 45, score = -1;
    for (let i = 1; i < 90; i++) {
      const total = bins[i - 1] + bins[i] + bins[i + 1];
      if (total > score) { score = total; best = i; }
    }
    return (best - 45) * Math.PI / 180;
  }

  /** One frame: scanlines across the whole strip, both directions. Returns slot votes and box. */
  function scanFrame(gray, width, height) {
    const observation = {
      // Exact chain positions from the start/stop; "near" positions were estimated across a gap.
      start: new Map(), end: new Map(), startNear: new Map(), endNear: new Map(), lengths: new Map(), estimates: new Map(), chars: 0, present: false, box: null };
    if (width < 64 || height < 8) return observation;
    let angle = estimateAngle(gray, width, height);
    if (Math.abs(angle) < 3 * Math.PI / 180) angle = 0;
    const cos = Math.cos(angle), sin = Math.sin(angle);
    const lines = Math.max(8, Math.min(48, Math.round(height / 6)));
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (let line = 0; line < lines; line++) {
      const y0 = height * (line + .5) / lines;
      let tMin = (3 - width / 2) / cos, tMax = (width - 4 - width / 2) / cos;
      if (sin > 0) { tMin = Math.max(tMin, (3 - y0) / sin); tMax = Math.min(tMax, (height - 4 - y0) / sin); }
      if (sin < 0) { tMin = Math.max(tMin, (height - 4 - y0) / sin); tMax = Math.min(tMax, (3 - y0) / sin); }
      const length = Math.floor(tMax - tMin);
      if (length < 64) continue;
      const profile = new Float32Array(length);
      if (angle === 0) {
        const row = Math.min(height - 2, Math.max(1, Math.round(y0)));
        const offset = Math.round(width / 2 + tMin);
        for (let t = 0; t < length; t++) {
          const i = row * width + offset + t;
          profile[t] = (gray[i - width] + gray[i] + gray[i + width]) / 3;
        }
      } else {
        // Average across the bar direction so the profile stays sharp along the scan.
        for (let t = 0; t < length; t++) {
          const cx = width / 2 + (tMin + t) * cos, cy = y0 + (tMin + t) * sin;
          let sum = 0;
          for (const n of [-1.5, 0, 1.5]) sum += bilinear(gray, width, cx - n * sin, cy + n * cos);
          profile[t] = sum / 3;
        }
      }
      const { positions, signs } = findEdges(profile);
      if (positions.length < 20) continue;
      const count = positions.length - 1;
      const widths = new Float32Array(count), isBar = new Uint8Array(count), starts = new Float32Array(count + 1);
      for (let i = 0; i < count; i++) {
        widths[i] = positions[i + 1] - positions[i];
        isBar[i] = signs[i] < 0 ? 1 : 0;
        starts[i] = positions[i];
      }
      starts[count] = positions[count];
      const lead = positions[0], trail = length - 1 - positions[count];
      const forward = fragments(widths, isBar, starts, lead, trail);
      // Reverse direction for upside-down labels: same elements read right to left.
      const rWidths = widths.slice().reverse(), rIsBar = isBar.slice().reverse();
      const rStarts = new Float32Array(count + 1);
      for (let i = 0; i <= count; i++) rStarts[i] = length - 1 - positions[count - i];
      const backward = fragments(rWidths, rIsBar, rStarts, trail, lead);
      for (const [pieces, reversed] of [[forward, false], [backward, true]]) {
        if (!collect(pieces, observation)) continue;
        for (const piece of pieces) {
          observation.chars += piece.chars.length;
          for (const u of [piece.begin, piece.end]) {
            const t = tMin + (reversed ? length - 1 - u : u);
            const x = width / 2 + t * cos, y = y0 + t * sin;
            minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y);
          }
        }
      }
      if (positions.length >= 30) observation.present = true;
    }
    if (minX < maxX) {
      const pad = height / lines;
      minY = Math.max(0, minY - pad); maxY = Math.min(height, maxY + pad);
      observation.box = [minX / width, minY / height, (maxX - minX) / width, (maxY - minY) / height];
    }
    observation.present = observation.present && observation.chars >= 3;
    return observation;
  }

  function bilinear(gray, width, x, y) {
    const x0 = x | 0, y0 = y | 0, fx = x - x0, fy = y - y0, i = y0 * width + x0;
    return (gray[i] * (1 - fx) + gray[i + 1] * fx) * (1 - fy) + (gray[i + width] * (1 - fx) + gray[i + width + 1] * fx) * fy;
  }

  /** Rolling multi-frame consensus. */
  class Session {
    constructor({ windowMs = 1000, maxFrames = 30 } = {}) {
      this.windowMs = windowMs; this.maxFrames = maxFrames;
      this.reset();
    }

    reset() {
      this.frames = [];
      this.partial = null;
      this.partialSince = 0;
    }

    add(observation, now) {
      this.frames.push({ observation, now });
      while (this.frames.length > this.maxFrames || now - this.frames[0].now > this.windowMs) this.frames.shift();
      if (!this.frames.some(frame => frame.observation.present)) { this.reset(); return {}; }
      return this.consensus(now);
    }

    consensus(now) {
      const length = this.length();
      if (!length) return {};
      const text = [];
      let unresolved = 0;
      for (let slot = 0; slot < length; slot++) {
        const totals = new Map(), frames = new Map(), sources = [new Map(), new Map()];
        this.frames.forEach(({ observation }, index) => {
          [observation.start.get(slot), observation.end.get(length - 1 - slot),
           observation.startNear.get(slot), observation.endNear.get(length - 1 - slot)].forEach((votes, source) => {
            if (!votes) return;
            for (const [char, weight] of votes) {
              totals.set(char, (totals.get(char) || 0) + weight);
              if (source < 2) sources[source].set(char, (sources[source].get(char) || 0) + weight);
              if (!frames.has(char)) frames.set(char, new Set());
              frames.get(char).add(index);
            }
          });
        });
        // Counted from the start and from the stop must agree; otherwise the length is wrong.
        const [fromStart, fromStop] = sources.map(votes => [...votes].sort((a, b) => b[1] - a[1])[0]);
        if (fromStart && fromStop && fromStart[1] >= 1 && fromStop[1] >= 1 && fromStart[0] !== fromStop[0]) {
          this.partial = null;
          return { length, conflict: true };
        }
        const order = [...totals].sort((a, b) => b[1] - a[1]);
        const [char, weight] = order[0] || [null, 0];
        const runnerUp = order[1]?.[1] || 0;
        const resolved = char && weight >= MIN_SLOT_VOTES && weight >= 2 * runnerUp
          && frames.get(char).size >= MIN_FRAMES;
        text.push(resolved ? char : "?");
        if (!resolved) unresolved++;
      }
      const joined = text.join("");
      if (!unresolved) { this.reset(); return { text: joined, length }; }
      // Mostly read, a few slots never readable: offer a pattern for catalog completion.
      if (unresolved <= 2 && length >= 5 && length - unresolved >= 4) {
        if (this.partial !== joined) { this.partial = joined; this.partialSince = now; }
        return { partial: joined, length, stableMs: now - this.partialSince };
      }
      this.partial = null;
      return { length };
    }

    length() {
      const ranked = key => {
        const totals = new Map();
        for (const { observation } of this.frames) {
          for (const [length, weight] of observation[key]) totals.set(length, (totals.get(length) || 0) + weight);
        }
        return [...totals].filter(([length]) => length > 0).sort((a, b) => b[1] - a[1]);
      };
      const exact = ranked("lengths");
      if (exact.length && exact[0][1] >= 1.5 && !(exact[1] && exact[0][1] < 2 * exact[1][1])) return exact[0][0];
      const aligned = this.alignedLength();
      const estimated = ranked("estimates");
      const estimate = estimated.length && estimated[0][1] >= 1.5 && !(estimated[1] && estimated[0][1] < 3 * estimated[1][1])
        ? estimated[0][0] : 0;
      if (aligned && estimate && aligned !== estimate) return 0;
      if (aligned) return aligned;
      return estimate && estimated[0][1] >= 2.5 ? estimate : 0;
    }

    /** No scanline saw both ends (steep tilt, central glare): align start- and stop-counted votes. */
    alignedLength() {
      const winners = key => {
        const totals = new Map();
        for (const { observation } of this.frames) {
          for (const [slot, votes] of observation[key]) {
            if (!totals.has(slot)) totals.set(slot, new Map());
            for (const [char, weight] of votes) totals.get(slot).set(char, (totals.get(slot).get(char) || 0) + weight);
          }
        }
        const best = new Map();
        for (const [slot, votes] of totals) {
          const order = [...votes].sort((a, b) => b[1] - a[1]);
          if (order[0][1] >= MIN_SLOT_VOTES && order[0][1] >= 2 * (order[1]?.[1] || 0)) best.set(slot, order[0][0]);
        }
        return best;
      };
      const start = winners("start"), end = winners("end");
      if (start.size < 3 || end.size < 3) return 0;
      const maxStart = Math.max(...start.keys()), maxEnd = Math.max(...end.keys());
      const scores = [];
      for (let length = Math.max(maxStart, maxEnd) + 1; length <= maxStart + maxEnd + 2; length++) {
        let agree = 0, disagree = 0;
        for (const [slot, char] of start) {
          const other = end.get(length - 1 - slot);
          if (other === undefined) continue;
          if (other === char) agree++; else disagree++;
        }
        scores.push([length, agree, disagree]);
      }
      scores.sort((a, b) => (b[1] - 2 * b[2]) - (a[1] - 2 * a[2]));
      const [best, second] = scores;
      if (!best || best[1] < 3 || best[2] > best[1] / 4) return 0;
      if (second && second[1] - 2 * second[2] > best[1] - 2 * best[2] - 2) return 0;
      return best[0];
    }
  }

  const api = { scanFrame, Session, classify, findEdges, ALPHABET, ENCODINGS, ASTERISK: 0x094 };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Robust39 = api;
})(typeof self !== "undefined" ? self : this);

import { describe, expect, it } from "vitest";
import { ScannerDetector, normalizeSku } from "./scanner";

function type(detector: ScannerDetector, text: string, gapMs: number, start = 0): string | null {
  let time = start;
  for (const key of text) detector.feed(key, (time += gapMs));
  return detector.feed("Enter", time + gapMs);
}

describe("ScannerDetector", () => {
  it("accepts a fast burst ending in Enter", () => {
    expect(type(new ScannerDetector(), "91201KVB901", 10)).toBe("91201KVB901");
  });

  it("ignores human typing and short bursts", () => {
    expect(type(new ScannerDetector(), "91201KVB901", 150)).toBeNull();
    expect(type(new ScannerDetector(), "ABC", 10)).toBeNull();
  });

  it("starts over after a pause inside the burst", () => {
    const detector = new ScannerDetector();
    detector.feed("X", 0);
    detector.feed("Y", 500);
    expect(type(detector, "12345", 10, 1000)).toBe("12345");
  });
});

describe("normalizeSku", () => {
  it("matches the Python spelling", () => {
    expect(normalizeSku(" 08e50-kvg-700c ")).toBe("08E50KVG700C");
  });
});

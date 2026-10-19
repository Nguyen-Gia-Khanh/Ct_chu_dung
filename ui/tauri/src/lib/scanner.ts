/**
 * Tells a barcode scanner (keyboard emulation) from a person typing: the scanner
 * sends at least `minLength` printable keys less than `maxGapMs` apart, then Enter.
 * Same rule as utils/barcode_scanner.py in the Tkinter app.
 */
export class ScannerDetector {
  private buffer = "";
  private lastKey = -Infinity;

  constructor(private maxGapMs = 70, private minLength = 5) {}

  /** Feed one key; returns the scanned code when Enter completes a scanner burst. */
  feed(key: string, timeMs: number): string | null {
    if (key === "Enter") {
      const code = this.buffer.length >= this.minLength && timeMs - this.lastKey <= this.maxGapMs * 2 ? this.buffer : null;
      this.buffer = "";
      return code;
    }
    if (timeMs - this.lastKey > this.maxGapMs) this.buffer = "";
    this.lastKey = timeMs;
    if (key.length === 1) this.buffer += key;
    return null;
  }
}

/** The one stored SKU spelling (mapper.core.common.normalize_sku). */
export function normalizeSku(value: string): string {
  return value.trim().toUpperCase().replace(/[- ]/g, "");
}

import time


def format_product_id(value):
    """Convert an 11-character scanner value to the stored 5-3-3 ID format."""
    compact = value.strip().replace("-", "")
    if len(compact) == 11 and compact.isascii() and compact.isalnum():
        return f"{compact[:5]}-{compact[5:8]}-{compact[8:]}"
    return value.strip()


class BarcodeScanner:
    def __init__(self, root, callback, max_gap=0.06, min_length=5):
        self.callback = callback
        self.max_gap = max_gap
        self.min_length = min_length

        self.buffer = ""
        self.last_key = 0

        root.bind_all("<KeyPress>", self._on_key, add="+")

    def _on_key(self, event):
        now = time.perf_counter()

        # New sequence if keys are too far apart
        if now - self.last_key > self.max_gap:
            self.buffer = ""

        self.last_key = now

        # Scanner finishes with Enter
        if event.keysym == "Return":
            if len(self.buffer) >= self.min_length:
                self.callback(format_product_id(self.buffer))

            self.buffer = ""
            return

        if event.char:
            self.buffer += event.char

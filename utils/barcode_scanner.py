import time


def format_product_id(value: str) -> str:
    """Convert a barcode scanner value to the stored 5-3-any ID format.

    Examples:
        "06410KFL850"   -> "06410-KFL-850"    (5-3-3)
        "04801K0G900ZC" -> "04801-K0G-900ZC"  (5-3-5)
        "08E50KVG700C"  -> "08E50-KVG-700C"   (5-3-4)
        "9280012000"    -> "92800-120-00"     (5-3-2)
    """
    if not value:
        return ""
    trimmed = value.strip()
    compact = trimmed.replace("-", "")
    if len(compact) > 8 and compact.isascii() and compact.isalnum():
        if "-" in trimmed:
            parts = trimmed.split("-")
            if len(parts[0]) != 5 or (len(parts) > 1 and len(parts[1]) != 3):
                return trimmed
        return f"{compact[:5]}-{compact[5:8]}-{compact[8:]}"
    return trimmed


def select_all_entry_text(entry) -> None:
    """Focus an entry and highlight (select) its entire contents."""
    if entry is None:
        return
    try:
        entry.focus_set()
        entry.selection_range(0, "end")
        entry.icursor("end")
    except Exception:
        pass


def bind_auto_highlight(entry) -> None:
    """Ensure an entry's text is automatically selected on focus and click."""
    if entry is None:
        return
    entry.bind(
        "<FocusIn>",
        lambda _e: entry.after_idle(lambda: select_all_entry_text(entry)),
        add="+",
    )
    entry.bind(
        "<Button-1>",
        lambda _e: entry.after_idle(lambda: select_all_entry_text(entry)),
        add="+",
    )


class BarcodeScanner:
    """Detects barcode scanner keyboard emulation and distinguishes it from human typing."""

    def __init__(self, root=None, callback=None, max_gap=0.07, min_length=5):
        self.root = root
        self.callback = callback
        self.max_gap = max_gap
        self.min_length = min_length

        self.buffer = ""
        self.last_key = 0.0
        self.last_scan_time = 0.0

        if root is not None:
            root.bind_all("<KeyPress>", self._on_key, add="+")

    def _on_key(self, event):
        now = time.perf_counter()

        # Scanner finishes with Enter
        if event.keysym == "Return":
            if self.is_scanner():
                code = self.pop_scanner_code()
                self.last_scan_time = now
                if self.callback and code:
                    self.callback(format_product_id(code))
                return
            self.buffer = ""
            return

        # New sequence if keys are too far apart (human typing)
        if now - self.last_key > self.max_gap:
            self.buffer = ""

        self.last_key = now

        # Only accumulate printable characters
        if event.char and event.char.isprintable():
            self.buffer += event.char

    def is_scanner(self) -> bool:
        """Return True if the current buffer represents rapid scanner keystrokes."""
        now = time.perf_counter()
        return len(self.buffer) >= self.min_length and (now - self.last_key) <= self.max_gap

    def pop_scanner_code(self) -> str | None:
        """Retrieve and clear the scanned code if currently detected as scanner input."""
        if self.is_scanner():
            code = self.buffer
            self.buffer = ""
            return code
        self.buffer = ""
        return None


def process_entry_return(
    entry,
    variable,
    on_search=None,
    scanner: BarcodeScanner | None = None,
) -> str:
    """Handle Return on an entry, cleanly differentiating scanner from human typer."""
    if scanner is not None and scanner.is_scanner():
        code = scanner.pop_scanner_code()
        formatted = format_product_id(code) if code else ""
        variable.set(formatted)
    else:
        formatted = format_product_id(variable.get())
        variable.set(formatted)

    entry.after_idle(lambda: select_all_entry_text(entry))
    if on_search is not None:
        on_search()
    return "break"

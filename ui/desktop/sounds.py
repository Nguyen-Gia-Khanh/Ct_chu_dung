"""Short audio cues for the desktop app."""

from __future__ import annotations

import tkinter as tk

try:
    import winsound
except ImportError:  # not Windows
    winsound = None


def play_error_sound(widget: tk.Misc | None = None) -> None:
    """Play Windows' "Critical Stop" sound without waiting for it, or ring Tk's bell
    elsewhere. A missing sound device never interrupts the action that called this."""
    if winsound is not None:
        try:
            winsound.MessageBeep(winsound.MB_ICONHAND)
            return
        except RuntimeError:
            pass
    if widget is not None:
        try:
            widget.bell()
        except tk.TclError:
            pass

"""Backward-compatible re-export for mapper.tkinter_ui.widgets."""

import sys
import mapper.tkinter_ui.widgets as _mod

sys.modules[__name__] = _mod

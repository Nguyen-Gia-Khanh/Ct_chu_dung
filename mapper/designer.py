"""Backward-compatible re-export for mapper.tkinter_ui.designer."""

import sys
import mapper.tkinter_ui.designer as _mod

sys.modules[__name__] = _mod

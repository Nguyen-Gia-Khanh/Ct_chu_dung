"""Backward-compatible re-export for mapper.tkinter_ui.app."""

import sys
import mapper.tkinter_ui.app as _ui_app

sys.modules[__name__] = _ui_app

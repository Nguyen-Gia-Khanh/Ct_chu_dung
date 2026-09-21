"""Backward-compatible re-export for mapper.ui.app."""

import sys
import mapper.ui.app as _ui_app

sys.modules[__name__] = _ui_app

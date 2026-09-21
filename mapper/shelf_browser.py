"""Backward-compatible re-export for mapper.ui.shelf_browser."""

import sys
import mapper.ui.shelf_browser as _mod

sys.modules[__name__] = _mod

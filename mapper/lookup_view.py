"""Backward-compatible re-export for mapper.ui.lookup_view."""

import sys
import mapper.ui.lookup_view as _mod

sys.modules[__name__] = _mod

"""Backward-compatible re-export for mapper.ui.widgets."""

import sys
import mapper.ui.widgets as _mod

sys.modules[__name__] = _mod

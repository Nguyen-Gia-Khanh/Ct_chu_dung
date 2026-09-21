"""Backward-compatible re-export for mapper.ui.designer."""

import sys
import mapper.ui.designer as _mod

sys.modules[__name__] = _mod

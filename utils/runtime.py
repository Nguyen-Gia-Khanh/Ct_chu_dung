"""Keep command-line entry points in the repository's own Python environment."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def ensure_repo_venv() -> None:
    """Restart with local Python, preserving script/module arguments and flags."""
    venv = REPO_ROOT / ".venv"
    if Path(sys.prefix).resolve() == venv.resolve():
        return
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        raise SystemExit(f"Repository .venv is missing. Run {REPO_ROOT / 'setup_venv.cmd'} first.")
    raise SystemExit(subprocess.call([str(python), *sys.orig_argv[1:]]))

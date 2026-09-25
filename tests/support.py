"""Writable test directories that also work in the Windows sandbox."""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from uuid import uuid4


class WorkspaceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        scratch = Path(__file__).resolve().parents[1] / "tmp"
        scratch.mkdir(exist_ok=True)
        self.folder = scratch / f"test_{uuid4().hex}"
        self.folder.mkdir()
        self.addCleanup(self._cleanup_folder)

    def _cleanup_folder(self) -> None:
        scratch = Path(__file__).resolve().parents[1] / "tmp"
        if self.folder.resolve().parent != scratch.resolve():
            raise RuntimeError("Refusing to remove a test directory outside tmp/")
        shutil.rmtree(self.folder)

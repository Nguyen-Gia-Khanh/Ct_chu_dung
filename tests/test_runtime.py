"""Check actual process handoff from global Python to the repo environment."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
import venv

from tests.support import WorkspaceTestCase
from utils.runtime import REPO_ROOT, ensure_repo_venv


class RuntimeTests(WorkspaceTestCase):
    def test_global_python_handoff_preserves_flags_arguments_and_working_directory(self):
        probe = self.folder / "runtime probe.py"
        probe.write_text(
            "import json, os, sys\n"
            f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
            "from utils.runtime import ensure_repo_venv\n"
            "ensure_repo_venv()\n"
            "import openpyxl\n"
            "print(json.dumps([sys.prefix, sys.argv[1:], sys.flags.no_user_site, os.getcwd()]))\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys._base_executable, "-s", str(probe), "argument with spaces", "Tiếng Việt"],
            cwd=self.folder,
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        prefix, arguments, no_user_site, cwd = json.loads(result.stdout)
        self.assertEqual(Path(prefix).resolve(), (REPO_ROOT / ".venv").resolve())
        self.assertEqual(arguments, ["argument with spaces", "Tiếng Việt"])
        self.assertEqual(no_user_site, 1)
        self.assertEqual(Path(cwd).resolve(), self.folder.resolve())

    def test_local_python_does_not_restart(self):
        with patch("utils.runtime.subprocess.call") as restart:
            ensure_repo_venv()
        restart.assert_not_called()

    def test_missing_local_venv_explains_setup_without_global_fallback(self):
        with patch("utils.runtime.REPO_ROOT", self.folder), patch("utils.runtime.subprocess.call") as restart:
            with self.assertRaisesRegex(SystemExit, "setup_venv.cmd"):
                ensure_repo_venv()
        restart.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "Native Windows launchers")
    def test_both_exes_use_only_the_venv_beside_them(self):
        venv.EnvBuilder(with_pip=False).create(self.folder / ".venv")
        for name in ("warehouse_mapper", "warehouse_label_printer"):
            with self.subTest(app=name):
                shutil.copy2(REPO_ROOT / f"{name}.exe", self.folder)
                (self.folder / f"{name}.py").write_text(
                    "import json, os, sys\n"
                    "from pathlib import Path\n"
                    "Path('result.json').write_text(json.dumps([sys.prefix, sys.argv[1:], os.getcwd()]))\n",
                    encoding="utf-8",
                )
                subprocess.run(
                    [str(self.folder / f"{name}.exe"), "--probe", "argument with spaces"],
                    cwd=REPO_ROOT,
                    check=True,
                    timeout=20,
                )
                prefix, arguments, cwd = json.loads((self.folder / "result.json").read_text())
                self.assertEqual(Path(prefix).resolve(), (self.folder / ".venv").resolve())
                self.assertEqual(arguments, ["--probe", "argument with spaces"])
                self.assertEqual(Path(cwd).resolve(), self.folder.resolve())

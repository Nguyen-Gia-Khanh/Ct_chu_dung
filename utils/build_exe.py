"""Build the clickable warehouse_mapper.exe beside the root Python launcher."""

from __future__ import annotations

import os
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Build the Windows executable on Windows.")

    root = Path(__file__).resolve().parents[1]
    local_build_packages = root / "tmp" / "pyinstaller"
    environment = os.environ.copy()
    if (local_build_packages / "PyInstaller").is_dir():
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (str(local_build_packages), environment.get("PYTHONPATH", "")))
        )
    elif find_spec("PyInstaller") is None:
        raise SystemExit("Install the build tool first: python -m pip install pyinstaller")

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--name",
        "warehouse_mapper",
        "--distpath",
        str(root),
        "--workpath",
        str(root / "tmp" / "pyinstaller-build"),
        "--specpath",
        str(root / "tmp" / "pyinstaller-spec"),
        str(root / "warehouse_mapper.py"),
    ]
    try:
        subprocess.run(command, cwd=root, env=environment, check=True)
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from error
    print(f"Ready: {root / 'warehouse_mapper.exe'}")


if __name__ == "__main__":
    main()

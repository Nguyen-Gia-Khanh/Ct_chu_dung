"""Build the root-level Windows executables for the desktop apps."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path


APPLICATIONS = {
    "mapper": "warehouse_mapper",
    "labels": "warehouse_label_printer",
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", choices=("all", *APPLICATIONS), default="all")
    args = parser.parse_args(argv)
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

    selected = APPLICATIONS if args.app == "all" else {args.app: APPLICATIONS[args.app]}
    if "labels" in selected and (find_spec("reportlab") is None or find_spec("pypdf") is None):
        raise SystemExit("Label printing needs reportlab and pypdf in the build environment.")

    for name in selected.values():
        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--windowed",
            "--noconfirm",
            "--name",
            name,
            "--distpath",
            str(root),
            "--workpath",
            str(root / "tmp" / "pyinstaller-build"),
            "--specpath",
            str(root / "tmp" / "pyinstaller-spec"),
            str(root / f"{name}.py"),
        ]
        try:
            subprocess.run(command, cwd=root, env=environment, check=True)
        except subprocess.CalledProcessError as error:
            raise SystemExit(error.returncode) from error
        print(f"Ready: {root / f'{name}.exe'}")


if __name__ == "__main__":
    main()

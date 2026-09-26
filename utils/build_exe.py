"""Build small Windows launchers for the Python scripts at the project root."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
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
        raise SystemExit("Build the Windows launchers on Windows.")

    compiler = shutil.which("gcc")
    if compiler is None:
        raise SystemExit("Install MinGW-w64 GCC to rebuild the Windows launchers.")

    root = Path(__file__).resolve().parents[1]
    selected = APPLICATIONS if args.app == "all" else {args.app: APPLICATIONS[args.app]}
    scratch = root / "tmp"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="warehouse-launcher-", dir=scratch) as temporary:
        if not Path(temporary).resolve().is_relative_to(root.resolve()):
            raise SystemExit("Build folder escaped the project workspace.")
        builds: list[tuple[Path, Path]] = []
        for name in selected.values():
            output = root / f"{name}.exe"
            compiled = Path(temporary) / output.name
            command = [
                compiler,
                "-std=c11",
                "-Os",
                "-s",
                "-municode",
                "-mwindows",
                "-static",
                str(root / "utils" / "launcher.c"),
                "-o",
                str(compiled),
            ]
            try:
                subprocess.run(command, cwd=root, check=True)
            except subprocess.CalledProcessError as error:
                raise SystemExit(error.returncode) from error
            builds.append((compiled, output))
        for compiled, output in builds:
            try:
                os.replace(compiled, output)
            except PermissionError as error:
                raise SystemExit(f"Close {output.name} before rebuilding it.") from error
            print(f"Ready: {output} (loads {output.stem}.py and project folders at runtime)")


if __name__ == "__main__":
    main()

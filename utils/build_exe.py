"""Build the root-level Windows executables for the desktop apps."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


APPLICATIONS = {
    "mapper": "warehouse_mapper",
    "labels": "warehouse_label_printer",
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", choices=("all", *APPLICATIONS), default="all")
    parser.add_argument(
        "--python",
        type=Path,
        help="Python environment to package (defaults to the shared Auto/.venv when present)",
    )
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        raise SystemExit("Build the Windows executable on Windows.")

    root = Path(__file__).resolve().parents[1]
    project_venv = root.parents[1] / ".venv" / "Scripts" / "python.exe"
    python = args.python or (project_venv if project_venv.is_file() else Path(sys.executable))
    python = python.resolve()
    if not python.is_file():
        raise SystemExit(f"Python interpreter not found: {python}")

    local_build_packages = root / "tmp" / "pyinstaller"
    environment = os.environ.copy()
    if (local_build_packages / "PyInstaller").is_dir():
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (str(local_build_packages), environment.get("PYTHONPATH", "")))
        )
    selected = APPLICATIONS if args.app == "all" else {args.app: APPLICATIONS[args.app]}
    required = ["PyInstaller"]
    if "mapper" in selected:
        required.append("selenium.webdriver.chrome.options")
    if "labels" in selected:
        required.extend(("reportlab", "pypdf"))
    for module in required:
        probe = subprocess.run(
            [str(python), "-c", "import importlib.util, sys; sys.exit(importlib.util.find_spec(sys.argv[1]) is None)", module],
            env=environment,
            check=False,
        )
        if probe.returncode:
            raise SystemExit(f"{module} is missing from {python}. Install it in that environment first.")

    for app, name in selected.items():
        command = [
            str(python),
            "-m",
            "PyInstaller",
            "--onefile",
            "--windowed",
            "--noconfirm",
            "--clean",
            "--name",
            name,
            "--distpath",
            str(root),
            "--workpath",
            str(root / "tmp" / "pyinstaller-build"),
            "--specpath",
            str(root / "tmp" / "pyinstaller-spec"),
        ]
        if app == "mapper":
            command.extend(("--collect-all", "selenium"))
        command.append(str(root / f"{name}.py"))
        print(f"Building {name} with {python}", flush=True)
        try:
            subprocess.run(command, cwd=root, env=environment, check=True)
        except subprocess.CalledProcessError as error:
            raise SystemExit(error.returncode) from error
        print(f"Ready: {root / f'{name}.exe'}")


if __name__ == "__main__":
    main()

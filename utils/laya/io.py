"""Command-line input and output paths shared by the three extraction stages."""

from __future__ import annotations

import argparse
from pathlib import Path

from mapper.core.common import data_directory


def parse_paths(stage: str, argv: list[str] | None) -> tuple[Path, Path]:
    parser = argparse.ArgumentParser(description=f"Extract Laya product {stage} data")
    parser.add_argument("--input", required=True, type=Path, help="Input XLSX workbook")
    parser.add_argument("--output", type=Path, help="Output XLSX workbook")
    args = parser.parse_args(argv)
    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        parser.error(f"Input workbook does not exist: {input_path}")
    output_path = args.output or data_directory() / "laya" / f"{input_path.stem}_{stage}.xlsx"
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return input_path, output_path

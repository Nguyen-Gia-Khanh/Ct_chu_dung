"""python -m mapper.rpc [--db PATH]: serve mapper/ to the desktop front end over stdio."""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from mapper.core.common import default_database_path
from .server import Server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Warehouse mapper service for the desktop app")
    parser.add_argument("--db", type=Path, help="SQLite database path (default: data/warehouse_locations.db)")
    args = parser.parse_args(argv)
    protocol_out = sys.stdout.buffer
    # stdout carries only protocol lines; stray prints from libraries go to stderr.
    sys.stdout = sys.stderr
    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
    server = Server(args.db or default_database_path(), protocol_out)
    server.emit("ready", server.api.info())
    server.serve(stdin)


if __name__ == "__main__":
    main()

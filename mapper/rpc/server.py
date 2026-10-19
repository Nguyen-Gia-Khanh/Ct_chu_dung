"""Line-delimited JSON transport: one request per stdin line, replies and events on stdout."""

from __future__ import annotations

import dataclasses
import json
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any, BinaryIO, TextIO

from .api import Api


def encode(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


class Server:
    """Requests run on a small pool so a slow call never holds up a search."""

    def __init__(self, db_path: Path | str, out: BinaryIO, *, workers: int = 4):
        self.out = out
        self.write_lock = Lock()
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rpc")
        self.api = Api(db_path, emit=self.emit)

    def send(self, message: dict[str, Any]) -> None:
        line = json.dumps(message, default=encode, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self.write_lock:
            self.out.write(line.encode("utf-8"))
            self.out.flush()

    def emit(self, event: str, data: Any) -> None:
        self.send({"event": event, "data": data})

    def handle(self, line: str) -> bool:
        """Dispatch one request line; False once the client asked to shut down."""
        try:
            request = json.loads(line)
            request_id, method = request["id"], request["method"]
            params = request.get("params") or {}
        except (ValueError, KeyError, TypeError) as error:
            self.send({"id": None, "error": {"type": "BadRequest", "message": str(error)}})
            return True
        if method == "shutdown":
            self.send({"id": request_id, "result": None})
            return False
        self.pool.submit(self._call, request_id, method, params)
        return True

    def _call(self, request_id: Any, method: str, params: dict[str, Any]) -> None:
        try:
            result = self.api.call(method, params)
        except Exception as error:  # every failure goes back to the caller as data
            if not isinstance(error, (ValueError, KeyError, LookupError)):
                traceback.print_exc(file=sys.stderr)
            message = error.args[0] if isinstance(error, KeyError) and error.args else str(error)
            self.send({"id": request_id, "error": {"type": type(error).__name__, "message": str(message)}})
        else:
            self.send({"id": request_id, "result": result})

    def serve(self, lines: TextIO) -> None:
        try:
            for line in lines:
                if line.strip() and not self.handle(line):
                    break
        finally:
            self.pool.shutdown(wait=True)
            self.api.browser.shutdown(wait=False, cancel_futures=True)

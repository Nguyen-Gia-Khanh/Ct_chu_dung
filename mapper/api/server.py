"""Lightweight HTTP server and REST API bridge for Warehouse Shelf Mapper UI."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


from .dependencies import configure_database, _get_database
from .read_routes import ReadRoutes
from .write_routes import WriteRoutes
from .static_files import StaticFiles


class WarehouseApiHandler(ReadRoutes, WriteRoutes, StaticFiles, BaseHTTPRequestHandler):
    server_version = "WarehouseMapperServer/1.0"

    def log_message(self, format: str, *args: object) -> None:
        """Keep routine local HTTP requests out of the launch terminal."""
        return

    def _send_cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send_json(self, data: object, status: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self._send_cors()
        self.end_headers()
        self.wfile.write(payload)

    def _send_error_json(self, message: str, status: int = 400) -> None:
        self._send_json({"success": False, "error": message}, status=status)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/"):
            self._handle_api_get(path, query)
        else:
            self._handle_static_file(path)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len > 0 else b"{}"

        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            self._send_error_json("Invalid JSON body", 400)
            return

        if path.startswith("/api/"):
            self._handle_api_post(path, payload)
        else:
            self._send_error_json("Not found", 404)

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            self._handle_api_delete(path)
        else:
            self._send_error_json("Not found", 404)


def _is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _launch_app_mode(url: str, title: str = "Warehouse Shelf Mapper") -> bool:
    import os
    import subprocess
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for exe in candidates:
        if exe.exists():
            proc = subprocess.Popen([
                str(exe),
                f"--app={url}",
                "--window-size=1400,860",
                f"--app-id=warehouse_mapper",
            ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            proc.wait()
            return True
    return False


def run_desktop_app(
    port: int = 8000,
    title: str = "Warehouse Shelf Mapper",
    database_path: Path | None = None,
) -> None:
    """Launch the TypeScript UI in a clean, standalone native desktop window (like IntelliJ/Tkinter)."""
    configure_database(database_path)
    _get_database()

    current_port = port
    server = None
    while current_port < port + 20:
        try:
            server = ThreadingHTTPServer(("127.0.0.1", current_port), WarehouseApiHandler)
            break
        except OSError:
            current_port += 1

    if not server:
        from tkinter import messagebox
        messagebox.showerror("Warehouse Shelf Mapper", f"Could not bind to any port between {port} and {port + 20}.")
        return

    # Start background API server
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    url = f"http://localhost:{current_port}"
    target_url = "http://localhost:3000" if _is_port_in_use(3000) else url

    # 1. Primary: Use pywebview for native Edge WebView2 desktop window
    launched = False
    try:
        import webview
        window = webview.create_window(
            title,
            target_url,
            width=1400,
            height=860,
            min_size=(1024, 680),
            resizable=True,
            text_select=True,
        )
        webview.start()
        launched = True
    except Exception:
        launched = False

    # 2. Fallback: Standalone App Window mode (--app)
    if not launched:
        launched = _launch_app_mode(target_url, title)

    # 3. Last fallback: Browser tab
    if not launched:
        webbrowser.open(target_url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    server.shutdown()


def run_server(port: int = 8000, open_browser: bool = True) -> None:
    """Compatibility alias to run desktop app."""
    run_desktop_app(port=port)


if __name__ == "__main__":
    run_desktop_app()

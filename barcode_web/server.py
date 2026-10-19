"""Foreground LAN scanner: process phone images in memory and save decoded text."""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import urllib.request
import webbrowser

from barcode_web.lookup import WarehouseLookup

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).with_name("static")
DATA = ROOT / "data" / "barcode_web"
MKCERT_URL = "https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-windows-amd64.exe"
MKCERT_SHA256 = "d2660b50a9ed59eada480750561c96abc2ed4c9a38c6a24d93e30e0977631398"
UNTRUSTED_CA = ("SSLV3_ALERT_CERTIFICATE_UNKNOWN", "TLSV1_ALERT_UNKNOWN_CA",
                "SSLV3_ALERT_BAD_CERTIFICATE", "CERTIFICATE_VERIFY_FAILED")
STATIC_FILES = {
    "/scan": ("index.html", "text/html"),
    "/receiver": ("receiver.html", "text/html"),
    "/setup": ("setup.html", "text/html"),
    "/scanner.js": ("scanner.js", "text/javascript"),
    "/decoder-worker.js": ("decoder-worker.js", "text/javascript"),
    "/robust39.js": ("robust39.js", "text/javascript"),
    "/style.css": ("style.css", "text/css"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/vendor/reader.js": ("vendor/reader.js", "text/javascript"),
    "/vendor/zxing_reader.wasm": ("vendor/zxing_reader.wasm", "application/wasm"),
}


def load_token(folder: Path) -> str:
    """Keep phone links valid across server restarts without removing authentication."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "session-token.txt"
    try:
        with path.open("x", encoding="ascii") as output:
            output.write(secrets.token_urlsafe(24))
    except FileExistsError:
        pass
    token = path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{32}", token):
        raise ValueError(f"Invalid scanner token in {path}. Remove that file to create a new phone link.")
    return token


def lan_addresses() -> list[str]:
    addresses = []
    try:
        # UDP connect chooses the default interface; it sends no packet.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect(("8.8.8.8", 80))
            addresses.append(route.getsockname()[0])
    except OSError:
        pass
    try:
        addresses.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return list(dict.fromkeys(address for address in addresses
                             if ipaddress.ip_address(address).is_private
                             and not ipaddress.ip_address(address).is_loopback))


def phone_address(addresses: list[str]) -> str | None:
    """Advertise one real LAN address, preferring the configured Private network."""
    if not addresses:
        return None
    if os.name == "nt":
        preferred = ""
        settings = DATA / "network-setup.json"
        try:
            preferred = json.loads(settings.read_text(encoding="utf-8-sig")).get("interface", "")
            if not isinstance(preferred, str):
                preferred = ""
        except (OSError, ValueError, AttributeError):
            pass
        try:
            result = subprocess.run([
                "powershell.exe", "-NoProfile", "-Command",
                "Get-NetIPConfiguration | Where-Object { "
                "$_.NetProfile.NetworkCategory -eq 'Private' -and $_.IPv4DefaultGateway } | "
                "Sort-Object { $_.InterfaceAlias -ne $env:WAREHOUSE_SCANNER_INTERFACE } | "
                "ForEach-Object { $_.IPv4Address.IPAddress }"],
                env={**os.environ, "WAREHOUSE_SCANNER_INTERFACE": preferred},
                capture_output=True, text=True, timeout=12,
                creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode == 0:
                for address in result.stdout.splitlines():
                    if address.strip() in addresses:
                        return address.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return addresses[0]


def prepare_tls(addresses: list[str]) -> None:
    """Create a local CA and server cert. Never install a trusted root silently."""
    certs = DATA / "certs"
    certs.mkdir(parents=True, exist_ok=True)
    names = ["localhost", "127.0.0.1", *addresses]
    saved = certs / "names.json"
    if (saved.exists() and json.loads(saved.read_text()) == names
            and all((certs / name).is_file()
                    for name in ("server.pem", "server-key.pem", "rootCA.cer"))):
        return
    tool = DATA / "mkcert.exe"
    if not tool.exists():
        print("First launch: downloading mkcert 1.4.4 for local HTTPS...", flush=True)
        with urllib.request.urlopen(MKCERT_URL, timeout=60) as response:
            binary = response.read()
        if hashlib.sha256(binary).hexdigest() != MKCERT_SHA256:
            raise RuntimeError("mkcert download checksum mismatch")
        tool.write_bytes(binary)
    if hashlib.sha256(tool.read_bytes()).hexdigest() != MKCERT_SHA256:
        raise RuntimeError("Local mkcert checksum mismatch; remove data/barcode_web/mkcert.exe")
    subprocess.run([str(tool), "-cert-file", str(certs / "server.pem"),
                    "-key-file", str(certs / "server-key.pem"), *names],
                   env={**os.environ, "CAROOT": str(certs)}, check=True)
    (certs / "rootCA.cer").write_bytes(
        ssl.PEM_cert_to_DER_cert((certs / "rootCA.pem").read_text()))
    saved.write_text(json.dumps(names))


class ScanStore:
    def __init__(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / "scans.jsonl"
        self.lock = threading.Lock()
        self.scans = deque(maxlen=100)  # Shown on the receiver; scans.jsonl keeps every scan.
        self.ids = deque(maxlen=2000)
        # Bound startup memory even when the log has been used for months.
        if self.path.exists():
            with self.path.open("rb") as source:
                size = source.seek(0, 2)
                source.seek(max(0, size - 2_000_000))
                if size > 2_000_000:
                    source.readline()
                for line in source:
                    try:
                        record = json.loads(line)
                        if not isinstance(record, dict) or not all(
                                isinstance(record.get(key), str)
                                for key in ("id", "text", "format", "received_at")):
                            continue
                        self.scans.append(record)
                        self.ids.append(record["id"])
                    except (ValueError, KeyError, TypeError):
                        continue

    def add(self, payload: dict) -> dict:
        with self.lock:
            if payload["id"] in self.ids:
                return {"ok": True, "duplicate": True}
            record = {**payload, "received_at": datetime.now(timezone.utc).isoformat()}
            with self.path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.scans.append(record)
            self.ids.append(record["id"])
            # repr prevents control characters in a barcode altering the terminal.
            print(f"{record['received_at']}  {record['text']!r}", flush=True)
        return {"ok": True, "duplicate": False}

    def recent(self) -> list[dict]:
        with self.lock:
            return list(reversed(self.scans))


class TrustAlerts:
    """Phones whose HTTPS handshake rejected the local CA, until they connect successfully."""

    def __init__(self):
        self.lock = threading.Lock()
        self.phones: dict[str, float] = {}

    def add(self, address: str) -> None:
        with self.lock:
            self.phones[address] = time.time()
            for stale in sorted(self.phones, key=self.phones.get)[:-20]:
                del self.phones[stale]

    def clear(self, address: str) -> None:
        with self.lock:
            self.phones.pop(address, None)

    def recent(self, seconds: float = 600) -> list[dict]:
        now = time.time()
        with self.lock:
            return [{"address": address, "seconds_ago": round(now - seen)}
                    for address, seen in sorted(self.phones.items(), key=lambda item: -item[1])
                    if now - seen < seconds]


def qr_svg(text: str) -> bytes:
    import zxingcpp
    svg = zxingcpp.write_barcode_to_svg(zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.QRCode))
    # Scale with its container: the writer emits a fixed pixel size without a viewBox.
    size = re.search(r'<svg width="(\d+)" height="(\d+)"', svg)
    if size:
        svg = svg.replace(size.group(0), f'<svg viewBox="0 0 {size.group(1)} {size.group(2)}" '
                          'shape-rendering="crispEdges"', 1)
    return svg.encode("utf-8")


class ScannerServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt":
            # Windows SO_REUSEADDR permits competing servers on the same port.
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, address, store, token, info, *, secure=False, lookup=None, alerts=None):
        self.store, self.token, self.info, self.secure = store, token, info, secure
        self.lookup = lookup
        self.alerts = alerts or TrustAlerts()
        self.frame_slot = threading.BoundedSemaphore(1)
        self.connection_note_lock = threading.Lock()
        self.last_connection_note = None
        super().__init__(address, Handler)

    def handle_error(self, request, client_address):
        error = sys.exception()
        if isinstance(error, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, TimeoutError,
                              ssl.SSLEOFError, ssl.SSLZeroReturnError)):
            # Closing a browser tab or abandoning a connection is normal.
            return
        if not isinstance(error, ssl.SSLError):
            return super().handle_error(request, client_address)
        reason = getattr(error, "reason", "")
        if reason in ("UNEXPECTED_EOF_WHILE_READING", "EOF_OCCURRED_IN_VIOLATION_OF_PROTOCOL"):
            return
        if reason in UNTRUSTED_CA:
            # Shown on the laptop receiver until this phone connects with a trusted CA.
            self.alerts.add(client_address[0])
        with self.connection_note_lock:
            now = time.monotonic()
            if self.last_connection_note is not None and now - self.last_connection_note < 60:
                return
            self.last_connection_note = now
            if reason in UNTRUSTED_CA:
                setup = self.info.get("setup_urls", [])
                instruction = (f"Open {setup[0]} on that phone." if setup else
                               "Open the phone certificate setup link in the laptop receiver.")
                print(f"Phone {client_address[0]} needs certificate trust setup. {instruction} "
                      "The server is still running.", flush=True)
            else:
                print("A phone could not establish HTTPS. Open the current phone link from the receiver. "
                      "The server is still running.", flush=True)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)
        if isinstance(self.connection, ssl.SSLSocket):
            self.connection.do_handshake()
            self.server.alerts.clear(self.client_address[0])

    def log_message(self, *_args):
        pass

    def reply(self, status, body, content_type="application/json; charset=utf-8", headers=()):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(self), microphone=()")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        provided = self.headers.get("Authorization", "")
        if not secrets.compare_digest(provided.encode("utf-8"), ("Bearer " + self.server.token).encode("utf-8")):
            try:
                # Closing with an unread body makes Windows reset the connection before the 403 arrives.
                length = int(self.headers.get("Content-Length", "0"))
                if 0 < length <= 1_000_000:
                    self.rfile.read(length)
            except (ValueError, OSError):
                pass
            self.reply(403, {"error": "Use the current phone link from the laptop receiver."})
            return False
        return True

    def do_GET(self):
        path = urlsplit(self.path).path
        local = ipaddress.ip_address(self.client_address[0]).is_loopback
        if path == "/api/session":
            if not local:
                return self.reply(403, {"error": "Open the receiver on the laptop."})
            return self.reply(200, {**self.server.info, "token": self.server.token,
                                    "untrusted_phones": self.server.alerts.recent()})
        if path == "/api/qr":
            if not local:
                return self.reply(403, {"error": "Open the receiver on the laptop."})
            target = parse_qs(urlsplit(self.path).query).get("target", [""])[0]
            urls = self.server.info.get({"phone": "phone_urls", "setup": "setup_urls"}.get(target, ""), [])
            if not urls:
                return self.reply(404, {"error": "No link for that QR code."})
            return self.reply(200, qr_svg(urls[0]), "image/svg+xml")
        if path == "/trust-check":
            # Reachable only once the phone trusts the CA; the HTTP setup page probes it.
            return self.reply(204, b"", "text/plain", headers=[("Access-Control-Allow-Origin", "*")])
        if path == "/api/trust-info":
            return self.reply(200, {"https_port": self.server.info.get("https_port")})
        if path == "/api/scans":
            if self.authorized():
                self.reply(200, self.server.store.recent())
            return
        if path == "/rootCA.cer":
            public_cert = DATA / "certs" / "rootCA.cer"
            if not public_cert.exists():
                return self.reply(404, {"error": "HTTPS certificate has not been created."})
            return self.reply(200, public_cert.read_bytes(), "application/x-x509-ca-cert")
        if path == "/receiver" and not local:
            return self.reply(403, {"error": "Open the receiver on the laptop."})
        files = {**STATIC_FILES, "/": ("index.html" if self.server.secure else "setup.html", "text/html")}
        if path not in files:
            return self.reply(404, {"error": "Not found"})
        name, mime = files[path]
        self.reply(200, (STATIC / name).read_bytes(), mime)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/api/scans", "/api/frames", "/api/resolve"):
            return self.reply(404, {"error": "Not found"})
        if not self.server.secure and not ipaddress.ip_address(self.client_address[0]).is_loopback:
            return self.reply(403, {"error": "Send scans over HTTPS."})
        if not self.authorized():
            return
        if path == "/api/frames":
            return self.process_frame()
        if self.headers.get_content_type() != "application/json":
            return self.reply(415, {"error": "Only barcode JSON is accepted."})
        if path == "/api/resolve":
            return self.resolve_partial()
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 32768:
                return self.reply(413, {"error": "Barcode request is too large or empty."})
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                return self.reply(400, {"error": "Invalid barcode data."})
            include_cell_contents = payload.pop("include_cell_contents", False)
            if (type(include_cell_contents) is not bool or set(payload) != {"id", "text", "format"}
                    or not all(isinstance(value, str) for value in payload.values())
                    or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", payload["id"])
                    or not 0 < len(payload["text"]) <= 4096
                    or not 0 < len(payload["format"]) <= 64):
                return self.reply(400, {"error": "Invalid barcode data."})
        except (ValueError, UnicodeError):
            return self.reply(400, {"error": "Invalid JSON."})
        try:
            lookup = (self.server.lookup.find(payload["text"], include_cell_contents=include_cell_contents) if self.server.lookup else
                      {"status": "unavailable", "product_id": None, "product_name": "", "locations": []})
        except sqlite3.Error:
            return self.reply(503, {"error": "Warehouse lookup failed. Check the database on the laptop, then retry."})
        try:
            self.reply(200, {**self.server.store.add(payload), "lookup": lookup})
        except OSError:
            self.reply(503, {"error": "Could not save the scan. Check the laptop's disk."})

    def resolve_partial(self):
        """Catalog completion for a Code 39 read with one or two unreadable characters."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                return self.reply(413, {"error": "Request is too large or empty."})
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict) or set(payload) != {"pattern"} or not isinstance(payload["pattern"], str):
                return self.reply(400, {"error": "Invalid pattern."})
            if self.server.lookup is None:
                return self.reply(200, {"ok": True, "status": "unavailable"})
            answer = self.server.lookup.resolve_pattern(payload["pattern"])
        except (ValueError, UnicodeError) as error:
            return self.reply(400, {"error": str(error) or "Invalid pattern."})
        except sqlite3.Error:
            return self.reply(503, {"error": "Warehouse lookup failed."})
        self.reply(200, {"ok": True, **answer})

    def process_frame(self):
        from barcode_web.processing import MAX_FRAME_BYTES, decode_frame
        if self.headers.get_content_type() != "image/jpeg":
            return self.reply(415, {"error": "Send a JPEG camera frame."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.reply(400, {"error": "Invalid frame length."})
        if not 0 < length <= MAX_FRAME_BYTES:
            return self.reply(413, {"error": "Camera frame is too large or empty."})
        # One native decode at a time across phones; reject excess work instead of queuing it.
        if not self.server.frame_slot.acquire(blocking=False):
            return self.reply(429, {"error": "Laptop is processing another frame. Retry shortly."})
        try:
            frame = self.rfile.read(length)
            if len(frame) != length:
                return self.reply(400, {"error": "Incomplete camera frame."})
            try:
                answer = decode_frame(frame, enhance=self.headers.get("X-Enhance", "1") != "0",
                                      include_mask=self.headers.get("X-Mask", "0") == "1")
            except ValueError as error:
                return self.reply(400, {"error": str(error)})
            self.reply(200, {"ok": True, **answer})
        finally:
            self.server.frame_slot.release()


def main():
    from utils.runtime import ensure_repo_venv
    ensure_repo_venv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--setup-port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--db", type=Path, help="Existing warehouse SQLite database (opened read-only)")
    parser.add_argument("--lan-ip", help="Choose one of this laptop's LAN IPv4 addresses explicitly")
    args = parser.parse_args()
    try:
        from barcode_web import processing  # Verify native dependencies before opening servers.
    except ImportError as error:
        raise SystemExit("Scanner image processing is missing. Run setup_venv.cmd, then restart.") from error
    addresses = lan_addresses()
    try:
        if args.lan_ip and args.lan_ip not in addresses:
            raise ValueError("--lan-ip must be an IPv4 address currently assigned to this laptop")
        address = args.lan_ip or phone_address(addresses)
        from mapper.core.common import default_database_path
        lookup = WarehouseLookup(args.db if args.db is not None else default_database_path())
        prepare_tls(addresses)
        token = load_token(DATA)
        info = {"phone_urls": [f"https://{address}:{args.port}/#{token}"] if address else [],
                "setup_urls": [f"http://{address}:{args.setup_port}/setup"] if address else [],
                "local_scanner_url": f"http://localhost:{args.setup_port}/scan#{token}",
                "https_port": args.port}
        store = ScanStore(DATA)
        alerts = TrustAlerts()
        secure = ScannerServer(("0.0.0.0", args.port), store, token, info, secure=True, lookup=lookup,
                               alerts=alerts)
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(DATA / "certs/server.pem", DATA / "certs/server-key.pem")
            secure.socket = context.wrap_socket(secure.socket, server_side=True, do_handshake_on_connect=False)
            setup = ScannerServer(("0.0.0.0", args.setup_port), store, token, info, lookup=lookup, alerts=alerts)
        except Exception:
            secure.server_close()
            raise
    except (OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Cannot start scanner: {error}") from error
    threading.Thread(target=secure.serve_forever, daemon=True).start()
    receiver = f"http://localhost:{args.setup_port}/receiver"
    print(f"\nLaptop receiver: {receiver}\nPhone link:", flush=True)
    for url in info["phone_urls"]:
        print("  " + url, flush=True)
    print(f"\nWarehouse database (read-only): {lookup.path}"
          "\nFirst use on each phone: open the HTTP setup link shown in the receiver."
          "\nClose this terminal/tab or press Ctrl+C to stop both servers."
          f"\nSaved scan text: {store.path}\n", flush=True)
    if not args.no_browser:
        webbrowser.open(receiver)
    try:
        setup.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        setup.server_close()
        secure.shutdown()
        secure.server_close()


if __name__ == "__main__":
    main()

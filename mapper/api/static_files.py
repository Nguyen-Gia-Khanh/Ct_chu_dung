"""Lightweight HTTP server and REST API bridge for Warehouse Shelf Mapper UI."""

from __future__ import annotations

import mimetypes
import re
import time

from mapper.core.common import application_directory


class StaticFiles:
    def _handle_static_file(self, path: str) -> None:
        root_dir = application_directory()
        # Serve the checked-in offline bundle when present.
        ui_dir = root_dir / "ui" / "web"
        dist_dir = ui_dir / "dist"

        clean_path = path.lstrip("/")
        if not clean_path or clean_path == "index.html":
            target_file = dist_dir / "index.html"
            if not target_file.exists():
                target_file = ui_dir / "index.html"
        else:
            target_file = dist_dir / clean_path
            if not target_file.exists():
                target_file = ui_dir / clean_path

        if not target_file.exists() or not target_file.is_file():
            # Fallback to index.html for SPA routing
            target_file = dist_dir / "index.html"
            if not target_file.exists():
                target_file = ui_dir / "index.html"

        if not target_file.exists():
            self.send_error(404, "File not found")
            return

        mime_type, _ = mimetypes.guess_type(str(target_file))
        if not mime_type:
            if target_file.suffix in (".jsx", ".tsx"):
                mime_type = "text/javascript"
            else:
                mime_type = "application/octet-stream"

        try:
            if target_file.name == "index.html":
                text = target_file.read_text(encoding="utf-8")
                ts = int(time.time())
                text = re.sub(r'(\?v=)[0-9]+', rf'\g<1>{ts}', text)
                content = text.encode("utf-8")
            else:
                content = target_file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self._send_cors()
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Error reading file: {e}")

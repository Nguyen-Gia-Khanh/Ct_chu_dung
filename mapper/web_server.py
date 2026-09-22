"""Lightweight HTTP server and REST API bridge for Warehouse Shelf Mapper UI."""

from __future__ import annotations

import json
import mimetypes
import re
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .common import application_directory, clean_location_segment, make_slot_name, normalize_search
from utils.barcode_scanner import format_product_id
from .database import WarehouseDatabase


def _get_database() -> WarehouseDatabase:
    for candidate in ("warehouse_locations.db", "warehouse.db"):
        p = application_directory() / candidate
        if p.exists():
            return WarehouseDatabase(p)
    return WarehouseDatabase(application_directory() / "warehouse_locations.db")


_uploader = None


def _get_uploader():
    global _uploader
    if _uploader is None:
        try:
            from .web_upload import WebsiteUploader
            _uploader = WebsiteUploader()
        except Exception:
            _uploader = None
    return _uploader



class WarehouseApiHandler(BaseHTTPRequestHandler):
    server_version = "WarehouseMapperServer/1.0"

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

    # --- API GET HANDLERS ---

    def _handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        db = _get_database()

        if path == "/api/shelves":
            shelves_raw = db.list_shelves()
            result = []
            for shelf_id, floor, side, shelf_code in shelves_raw:
                try:
                    _, _, _, slot_counts = db.get_shelf(shelf_id)
                except Exception:
                    slot_counts = []
                row_cols = {r: count for r, count in enumerate(slot_counts, start=1)}
                result.append({
                    "id": shelf_id,
                    "floor": int(floor) if floor.isdigit() else floor,
                    "side": int(side) if side.isdigit() else side,
                    "shelf": shelf_code,
                    "rows_count": len(slot_counts),
                    "default_cols": max(slot_counts) if slot_counts else 10,
                    "custom_row_cols": row_cols,
                })
            self._send_json(result)
            return

        match_shelf_cells = re.match(r"^/api/shelves/([^/]+)/cells$", path)
        if match_shelf_cells:
            shelf_code_raw = urllib.parse.unquote(match_shelf_cells.group(1))
            placements = db.get_placement_details()
            products_map = {p[0]: p[1] for p in db.get_products()}
            # Also catalog names
            for cid, cname, _ in db.get_catalog_products():
                if cid not in products_map:
                    products_map[cid] = cname

            cells: dict[str, dict] = {}
            prefix = shelf_code_raw.strip().upper()
            for prod_id, pl in placements.items():
                if pl.slot_name.upper().startswith(prefix):
                    loc_id = pl.slot_name
                    if loc_id not in cells:
                        match_slot = re.search(r"(\d+)-(\d+)$", loc_id)
                        row = int(match_slot.group(1)) if match_slot else 1
                        col = int(match_slot.group(2)) if match_slot else 1
                        cells[loc_id] = {
                            "row": row,
                            "col": col,
                            "loc_id": loc_id,
                            "items": [],
                            "total_quantity": 0,
                            "is_occupied": True,
                        }
                    pname = products_map.get(prod_id, prod_id)
                    qty = pl.stock_qty
                    cells[loc_id]["items"].append({
                        "product_id": prod_id,
                        "product_name": pname,
                        "barcode": prod_id.replace("-", ""),
                        "quantity": qty,
                        "placed_at": pl.assigned_at,
                    })
                    if qty is not None:
                        cells[loc_id]["total_quantity"] += qty

            self._send_json(cells)
            return

        if path == "/api/products/catalog":
            catalog_rows = db.get_catalog_products()
            placements = db.get_placements()
            placement_details = db.get_placement_details()
            result = []
            for pid, pname, _ in catalog_rows:
                loc = placements.get(pid)
                p_detail = placement_details.get(pid)
                qty = p_detail.stock_qty if p_detail else None
                result.append({
                    "product_id": pid,
                    "product_name": pname,
                    "barcode": pid.replace("-", ""),
                    "on_hand": qty,
                    "loc_id": loc or None,
                })
            self._send_json(result)
            return

        if path == "/api/products/pending-queue":
            products = db.get_products()
            placements = db.get_placements()
            on_hand = db.get_on_hand_products()
            result = []
            for pid, pname in products:
                loc = placements.get(pid)
                if not loc:
                    qty = on_hand[pid].stock_qty if pid in on_hand else None
                    result.append({
                        "code": pid,
                        "name": pname,
                        "on_hand": qty,
                        "loc_id": None,
                    })
            self._send_json(result)
            return

        if path == "/api/products/primal-queue":
            products = db.get_products()
            placements = db.get_placements()
            placement_details = db.get_placement_details()
            result = []
            for pid, pname in products:
                loc = placements.get(pid)
                p_detail = placement_details.get(pid)
                qty = p_detail.stock_qty if p_detail else None
                result.append({
                    "barcode": pid.replace("-", ""),
                    "product_name": pname,
                    "quantity": qty,
                    "status": "assigned" if loc else "pending",
                    "target_location": loc or None,
                })
            self._send_json(result)
            return

        if path == "/api/products/find":
            q = query.get("q", [""])[0].strip()
            if not q:
                self._send_json({"product": None, "location": None})
                return

            term = normalize_search(format_product_id(q))
            placements = db.get_placements()
            catalog = db.get_catalog_products()
            placement_details = db.get_placement_details()
            found = None
            for pid, pname, _ in catalog:
                if (
                    normalize_search(pid) == term
                    or normalize_search(pid.replace("-", "")) == term.replace("-", "")
                    or normalize_search(pname).find(term) != -1
                ):
                    p_detail = placement_details.get(pid)
                    found = {
                        "product_id": pid,
                        "product_name": pname,
                        "barcode": pid.replace("-", ""),
                        "on_hand": p_detail.stock_qty if p_detail else None,
                        "loc_id": placements.get(pid),
                    }
                    break
            self._send_json({"product": found, "location": found["loc_id"] if found else None})
            return

        if path == "/api/products/on-hand":
            on_hand = db.get_on_hand_products()
            catalog = {p[0]: p[1] for p in db.get_catalog_products()}
            products = {p[0]: p[1] for p in db.get_products()}
            result = []
            for pid, item in on_hand.items():
                name = products.get(pid) or catalog.get(pid) or pid
                result.append({
                    "product_id": pid,
                    "product_name": name,
                    "stock_qty": item.stock_qty,
                    "queued_at": item.queued_at,
                })
            self._send_json(result)
            return

        if path == "/api/slot-address":
            floor = clean_location_segment(query.get("floor", ["1"])[0])
            side = clean_location_segment(query.get("side", ["1"])[0])
            shelf_code = clean_location_segment(query.get("shelf", ["A"])[0])
            try:
                row = int(query.get("row", ["1"])[0])
                col = int(query.get("col", ["1"])[0])
            except (ValueError, TypeError):
                row, col = 1, 1

            slot = db.get_slot_address(floor, side, shelf_code, row, col)
            if not slot:
                slot_name = make_slot_name(floor, shelf_code, row, col, side=side)
                self._send_json({
                    "success": False,
                    "slot_name": slot_name,
                    "message": f"No saved cell at Floor {floor} / Side {side} / Shelf {shelf_code} / Row {row} / Cell {col}."
                })
                return

            contents_raw = db.get_slot_contents(slot.slot_id)
            contents = []
            for pid, pname, pl in contents_raw:
                contents.append({
                    "product_id": pid,
                    "product_name": pname,
                    "stock_qty": pl.stock_qty,
                    "assigned_at": pl.assigned_at.replace("T", " ") if pl.assigned_at else "Unknown",
                })
            self._send_json({
                "success": True,
                "slot": {
                    "slot_id": slot.slot_id,
                    "slot_name": slot.slot_name,
                    "floor": slot.floor,
                    "side": slot.side,
                    "shelf": slot.shelf_code,
                    "row": slot.row_number,
                    "col": slot.slot_number,
                },
                "contents": contents,
                "message": f"Loaded {slot.slot_name} · {len(contents)} product(s)"
            })
            return

        self._send_error_json(f"Unknown GET endpoint: {path}", 404)

    # --- API POST HANDLERS ---

    def _handle_api_post(self, path: str, payload: dict) -> None:
        db = _get_database()
        now_iso = datetime.now().astimezone().isoformat(timespec="seconds")

        if path == "/api/shelves":
            floor = str(payload.get("floor", 1))
            side = str(payload.get("side", 1))
            shelf = str(payload.get("shelf", "A")).upper().strip()
            rows_count = int(payload.get("rows_count", 8))
            default_cols = int(payload.get("default_cols", 10))
            custom_map = payload.get("custom_row_cols", {})

            row_counts = []
            for r in range(1, rows_count + 1):
                c = custom_map.get(str(r)) or custom_map.get(r) or default_cols
                row_counts.append(int(c))

            try:
                shelf_id = db.save_shelf(floor=floor, shelf_code=shelf, row_counts=row_counts, side=side)
                self._send_json({
                    "success": True,
                    "id": shelf_id,
                    "message": f"Saved shelf L{floor}-{side}{shelf}",
                })
            except Exception as e:
                self._send_error_json(str(e))
            return

        if path == "/api/assignments":
            prod_id = format_product_id(payload.get("product_id", ""))
            prod_name = payload.get("product_name", prod_id)
            slot_data = payload.get("slot", {})
            qty = int(payload.get("quantity", 1))
            upload_kiot = bool(payload.get("upload_to_kiotviet", False))

            floor = str(slot_data.get("floor", 1))
            side = str(slot_data.get("side", 1))
            shelf = str(slot_data.get("shelf", "A"))
            row = int(slot_data.get("row", 1))
            col = int(slot_data.get("col", 1))

            slot_obj = db.get_slot_address(floor, side, shelf, row, col)
            if not slot_obj:
                slot_name = make_slot_name(floor, shelf, row, col, side=side)
                slot_obj = db.get_slot_by_name(slot_name)

            if not slot_obj:
                self._send_error_json(f"Slot {make_slot_name(floor, shelf, row, col, side)} does not exist.", 404)
                return

            try:
                # Ensure product exists in working queue
                db.import_products({prod_id: prod_name})
                # Add to on_hand
                db.add_to_on_hand({prod_id: qty}, now_iso)
                # Assign to slot
                db.assign_on_hand_to_slot(slot_obj.slot_id, now_iso, [prod_id])

                # Background KiotViet upload if requested
                if upload_kiot:
                    def _do_upload():
                        try:
                            from .web_upload import upload_product_location
                            upload_product_location(prod_id, slot_obj.slot_name)
                        except Exception as ex:
                            print(f"[KiotViet Upload Error] {ex}", file=sys.stderr)

                    threading.Thread(target=_do_upload, daemon=True).start()

                self._send_json({
                    "success": True,
                    "message": f"Assigned {prod_id} to {slot_obj.slot_name} (Qty: {qty})",
                })
            except Exception as e:
                self._send_error_json(str(e))
            return

        if path == "/api/assignments/direct-move":
            prod_id = format_product_id(payload.get("product_id", ""))
            slot_data = payload.get("slot", {})
            floor = str(slot_data.get("floor", 1))
            side = str(slot_data.get("side", 1))
            shelf = str(slot_data.get("shelf", "A"))
            row = int(slot_data.get("row", 1))
            col = int(slot_data.get("col", 1))

            slot_obj = db.get_slot_address(floor, side, shelf, row, col)
            if not slot_obj:
                slot_name = make_slot_name(floor, shelf, row, col, side=side)
                slot_obj = db.get_slot_by_name(slot_name)

            if not slot_obj:
                self._send_error_json("Target slot not found", 404)
                return

            try:
                # Pull to queue then assign
                db.force_pull_to_queue([prod_id], now_iso)
                db.add_to_on_hand({prod_id: 1}, now_iso)
                db.assign_on_hand_to_slot(slot_obj.slot_id, now_iso, [prod_id])
                self._send_json({"success": True, "message": f"Moved {prod_id} to {slot_obj.slot_name}"})
            except Exception as e:
                self._send_error_json(str(e))
            return

        if path == "/api/assignments/transfer":
            src_slot_id = payload.get("source_slot_id")
            dst_slot_id = payload.get("target_slot_id")
            action = payload.get("action", "switch")

            if src_slot_id and dst_slot_id:
                slot_a = db.get_slot_by_id(int(src_slot_id))
                slot_b = db.get_slot_by_id(int(dst_slot_id))
            else:
                src_shelf = payload.get("source_shelf", "")
                src_row = int(payload.get("source_row", 1))
                src_col = int(payload.get("source_col", 1))
                dst_shelf = payload.get("target_shelf", "")
                dst_row = int(payload.get("target_row", 1))
                dst_col = int(payload.get("target_col", 1))
                slot_a_name = f"{src_shelf}{src_row}-{src_col}"
                slot_b_name = f"{dst_shelf}{dst_row}-{dst_col}"
                slot_a = db.get_slot_by_name(slot_a_name)
                slot_b = db.get_slot_by_name(slot_b_name)

            if not slot_a or not slot_b:
                self._send_error_json("One or both slots not found in database.", 404)
                return

            slot_a_name = slot_a.slot_name
            slot_b_name = slot_b.slot_name

            # Pre-fetch product lists to compute exact location changes
            contents_a = [pid for pid, _, _ in db.get_slot_contents(slot_a.slot_id)]
            contents_b = [pid for pid, _, _ in db.get_slot_contents(slot_b.slot_id)]

            try:
                if action == "switch":
                    db.swap_slot_contents(slot_a.slot_id, slot_b.slot_id)
                    changed_products = (
                        [{"product_id": pid, "slot_name": slot_b_name} for pid in contents_a] +
                        [{"product_id": pid, "slot_name": slot_a_name} for pid in contents_b]
                    )
                    self._send_json({
                        "success": True,
                        "message": f"Switched {slot_a_name} ({len(contents_a)}) with {slot_b_name} ({len(contents_b)}).",
                        "changed_products": changed_products,
                    })
                elif action == "combine":
                    count = db.combine_slot_contents(slot_a.slot_id, slot_b.slot_id)
                    changed_products = [{"product_id": pid, "slot_name": slot_b_name} for pid in contents_a]
                    self._send_json({
                        "success": True,
                        "message": f"Combined {count} product(s) from {slot_a_name} into {slot_b_name}.",
                        "changed_products": changed_products,
                    })
                else:
                    self._send_error_json(f"Unknown action: {action}")
            except Exception as e:
                self._send_error_json(str(e))
            return

        if path == "/api/assignments/remove":
            prod_id = format_product_id(payload.get("product_id", ""))
            try:
                db.force_pull_to_queue([prod_id], now_iso)
                self._send_json({"success": True, "message": f"Removed {prod_id}"})
            except Exception as e:
                self._send_error_json(str(e))
            return

        if path == "/api/import-csv":
            data = payload.get("data", {})
            mapping = payload.get("mapping", {})
            mode = payload.get("mode", "new")
            rows = data.get("rows", [])
            code_col = mapping.get("code_col")
            name_col = mapping.get("name_col")

            records: dict[str, tuple[str, str]] = {}
            for r in rows:
                code = format_product_id(r.get(code_col, ""))
                name = r.get(name_col, "")
                if code:
                    records[code] = (name, name)

            try:
                if mode == "new":
                    ins, upd = db.import_products(records)
                    db.import_catalog_products(records)
                else:
                    ins, upd = db.import_catalog_products(records)
                self._send_json({"success": True, "message": f"Imported {ins} new, {upd} updated items."})
            except Exception as e:
                self._send_error_json(str(e))
            return

        if path == "/api/on-hand/add":
            items = payload.get("items", [])
            if not items and "product_ids" in payload:
                items = [{"product_id": pid, "quantity": None} for pid in payload["product_ids"]]
            quantities = {}
            for it in items:
                pid = format_product_id(it.get("product_id", ""))
                if not pid:
                    continue
                q = it.get("quantity")
                if q is not None and str(q).strip() != "":
                    try:
                        quantities[pid] = int(q)
                    except (ValueError, TypeError):
                        quantities[pid] = None
                else:
                    quantities[pid] = None
            try:
                count = db.add_to_on_hand(quantities, now_iso)
                self._send_json({"success": True, "message": f"Moved {count} product(s) to on-hand. Saved immediately.", "count": count})
            except Exception as e:
                self._send_error_json(str(e))
            return

        if path == "/api/on-hand/dequeue":
            product_ids = [format_product_id(pid) for pid in payload.get("product_ids", [])]
            try:
                count = db.dequeue_on_hand(product_ids, now_iso)
                self._send_json({"success": True, "message": f"Returned {count} selected product(s) to the total queue with stock retained.", "count": count})
            except Exception as e:
                self._send_error_json(str(e))
            return

        if path == "/api/on-hand/update-stock":
            product_id = format_product_id(payload.get("product_id", ""))
            raw_q = payload.get("quantity")
            quantity = int(raw_q) if raw_q is not None and str(raw_q).strip() != "" else 0
            try:
                db.update_on_hand_stock(product_id, quantity)
                self._send_json({"success": True, "message": f"Updated on-hand stock for {product_id} to {quantity}."})
            except Exception as e:
                self._send_error_json(str(e))
            return

        if path == "/api/assignments/assign-on-hand":
            slot_id = int(payload.get("slot_id", 0))
            product_ids = [format_product_id(pid) for pid in payload.get("product_ids", [])]
            slot = db.get_slot_by_id(slot_id)
            if not slot:
                self._send_error_json("Slot not found", 404)
                return
            try:
                count = db.assign_on_hand_to_slot(slot_id, now_iso, product_ids)
                self._send_json({"success": True, "message": f"Assigned {count} product(s) to {slot.slot_name}. Saved immediately."})
            except Exception as e:
                self._send_error_json(str(e))
            return

        if path == "/api/slot-contents/move-to-hand":
            slot_id = int(payload.get("slot_id", 0))
            raw_pids = payload.get("product_ids")
            product_ids = [format_product_id(pid) for pid in raw_pids] if raw_pids is not None else None
            slot = db.get_slot_by_id(slot_id)
            slot_name = slot.slot_name if slot else "slot"
            try:
                count = db.move_slot_to_on_hand(slot_id, now_iso, product_ids)
                self._send_json({"success": True, "message": f"Moved {count} product(s) from {slot_name} to on-hand."})
            except Exception as e:
                self._send_error_json(str(e))
            return

        if path == "/api/slot-contents/update-stock":
            slot_id = int(payload.get("slot_id", 0))
            product_id = format_product_id(payload.get("product_id", ""))
            raw_q = payload.get("quantity")
            quantity = int(raw_q) if raw_q is not None and str(raw_q).strip() != "" else 0
            try:
                db.update_placement_stock(product_id, quantity, expected_slot_id=slot_id)
                self._send_json({"success": True, "message": f"Updated stock for {product_id} to {quantity}."})
            except Exception as e:
                self._send_error_json(str(e))
            return

        if path == "/api/catalog/transfer-to-queue":
            product_ids = [format_product_id(pid) for pid in payload.get("product_ids", [])]
            catalog_rows = db.get_catalog_products()
            catalog_map = {p[0]: (p[1], p[2]) for p in catalog_rows}
            records = {pid: catalog_map[pid] for pid in product_ids if pid in catalog_map}
            try:
                ins, upd = db.import_products(records)
                self._send_json({"success": True, "message": f"Transferred {ins + upd} product(s) to total queue."})
            except Exception as e:
                self._send_error_json(str(e))
            return

        if path == "/api/web/connect-chrome":
            uploader_msg = "Chrome connection initiated."
            try:
                uploader = _get_uploader()
                if uploader:
                    connected = uploader.connect()
                    uploader_msg = connected or "Connected to Chrome successfully."
            except Exception as e:
                uploader_msg = f"Chrome connection note: {e}"
            self._send_json({"success": True, "message": uploader_msg})
            return

        if path == "/api/web/modify-location":
            items = payload.get("items")
            product_ids = payload.get("product_ids", [])
            slot_name = payload.get("slot_name", "")

            updates = []
            if items:
                for it in items:
                    pid = format_product_id(it.get("product_id", ""))
                    loc = clean_location_segment(it.get("slot_name", ""))
                    if pid and loc:
                        updates.append((pid, loc))
            elif product_ids and slot_name:
                clean_loc = clean_location_segment(slot_name)
                for pid in product_ids:
                    clean_pid = format_product_id(pid)
                    if clean_pid and clean_loc:
                        updates.append((clean_pid, clean_loc))

            uploader_note = ""
            try:
                uploader = _get_uploader()
                if uploader and uploader.is_connected():
                    from .web_upload import LocationUpdate
                    for pid, loc in updates:
                        uploader.modify_location(LocationUpdate(pid, loc))
                    uploader_note = " and synced to website via Chrome"
            except Exception as ex:
                uploader_note = f" (Chrome note: {ex})"

            self._send_json({
                "success": True,
                "message": f"Updated web location for {len(updates)} product(s){uploader_note}.",
                "count": len(updates)
            })
            return

        self._send_error_json(f"Unknown POST endpoint: {path}", 404)

    # --- API DELETE HANDLERS ---

    def _handle_api_delete(self, path: str) -> None:
        db = _get_database()
        match_shelf = re.match(r"^/api/shelves/(\d+)$", path)
        if match_shelf:
            shelf_id = int(match_shelf.group(1))
            try:
                db.delete_shelf(shelf_id)
                self._send_json({"success": True, "message": f"Deleted shelf {shelf_id}"})
            except Exception as e:
                self._send_error_json(str(e))
            return

        self._send_error_json(f"Unknown DELETE endpoint: {path}", 404)

    # --- STATIC FILE HANDLER ---

    def _handle_static_file(self, path: str) -> None:
        root_dir = application_directory()
        # Prefer ui/dist if available, else ui
        dist_dir = root_dir / "ui" / "dist"
        ui_dir = root_dir / "ui"

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
            ])
            proc.wait()
            return True
    return False


def run_desktop_app(port: int = 8000, title: str = "Warehouse Shelf Mapper") -> None:
    """Launch the TypeScript UI in a clean, standalone native desktop window (like IntelliJ/Tkinter)."""
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
        print(f"Error: Could not bind to any port between {port} and {port + 20}.", file=sys.stderr)
        return

    # Start background API server
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    url = f"http://localhost:{current_port}"
    target_url = "http://localhost:3000" if _is_port_in_use(3000) else url
    print("=" * 60)
    print(f"  {title} - Native Desktop Window")
    print(f"  Backend server running at: {url}")
    print("=" * 60)

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
    except Exception as ex:
        print(f"pywebview notice: {ex}")
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


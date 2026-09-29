"""Lightweight HTTP server and REST API bridge for Warehouse Shelf Mapper UI."""

from __future__ import annotations

import re
import urllib.parse

from mapper.core.common import clean_location_segment, make_slot_name, normalize_search
from utils.barcode_scanner import format_product_id


from .dependencies import _get_database


class ReadRoutes:
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
            placement_items = db.get_all_placement_items()
            products_map = {p[0]: p[1] for p in db.get_products()}
            # Also catalog names
            for cid, cname, _ in db.get_display_catalog_products():
                if cid not in products_map:
                    products_map[cid] = cname

            cells: dict[str, dict] = {}
            prefix = shelf_code_raw.strip().upper()
            for prod_id, loc_id, qty, assigned_at in placement_items:
                if loc_id.upper().startswith(prefix):
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
                    cells[loc_id]["items"].append({
                        "product_id": prod_id,
                        "product_name": pname,
                        "barcode": prod_id.replace("-", ""),
                        "quantity": qty,
                        "placed_at": assigned_at,
                    })
                    if qty is not None:
                        cells[loc_id]["total_quantity"] += qty

            self._send_json(cells)
            return

        if path == "/api/products/catalog":
            catalog_rows = db.get_display_catalog_products()
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
            catalog = db.get_display_catalog_products()
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
            catalog = {p[0]: p[1] for p in db.get_display_catalog_products()}
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

        if path == "/api/exceptions/pending":
            pending = db.get_pending_csv_updates()
            self._send_json({
                "success": True,
                "count": len(pending),
                "items": pending,
            })
            return

        self._send_error_json(f"Unknown GET endpoint: {path}", 404)

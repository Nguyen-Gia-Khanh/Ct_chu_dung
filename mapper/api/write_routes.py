"""Lightweight HTTP server and REST API bridge for Warehouse Shelf Mapper UI."""

from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path

from mapper.core.common import clean_location_segment, make_slot_name
from utils.barcode_scanner import format_product_id


from .dependencies import _get_database, _get_uploader


class WriteRoutes:
    def _handle_api_post(self, path: str, payload: dict) -> None:
        db = _get_database()
        now_iso = datetime.now().astimezone().isoformat(timespec="seconds")

        if path == "/api/shelves":
            floor = clean_location_segment(str(payload.get("floor", "1")))
            side = clean_location_segment(str(payload.get("side", "1")))
            shelf = clean_location_segment(str(payload.get("shelf", "A")).upper())
            rows_count = int(payload.get("rows_count", 8))
            default_cols = int(payload.get("default_cols", 10))
            custom_map = payload.get("custom_row_cols", {}) or {}
            raw_id = payload.get("id")
            shelf_id = None
            if raw_id is not None:
                try:
                    shelf_id = int(raw_id)
                except (ValueError, TypeError):
                    shelf_id = None

            row_counts = []
            for r in range(1, rows_count + 1):
                c = custom_map.get(str(r)) or custom_map.get(r) or default_cols
                try:
                    row_counts.append(max(1, min(200, int(c))))
                except (ValueError, TypeError):
                    row_counts.append(default_cols)

            try:
                new_shelf_id = db.save_shelf(
                    floor=floor,
                    shelf_code=shelf,
                    row_counts=row_counts,
                    side=side,
                    shelf_id=shelf_id,
                )
                self._send_json({
                    "success": True,
                    "id": new_shelf_id,
                    "floor": int(floor) if floor.isdigit() else floor,
                    "side": int(side) if side.isdigit() else side,
                    "shelf": shelf,
                    "rows_count": len(row_counts),
                    "default_cols": max(row_counts) if row_counts else default_cols,
                    "custom_row_cols": {r: count for r, count in enumerate(row_counts, start=1)},
                    "message": f"Saved shelf L{floor}-{side}{shelf} ({len(row_counts)} rows)",
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
                            from mapper.features.web_upload import upload_product_location
                            upload_product_location(prod_id, slot_obj.slot_name)
                        except Exception:
                            # This optional upload runs after the local assignment succeeds.
                            return

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
                name = str(r.get(name_col, "") or "").strip()
                if code and name:
                    records[code] = (name, name)

            if not records:
                self._send_error_json("No valid product ID/name rows were found in the CSV.")
                return

            try:
                if mode == "new":
                    ins, upd = db.import_products(records)
                    detail = "Queue names updated; shelf assignments, stock, and stored catalog names kept."
                else:
                    ins, upd = db.import_catalog_products(records)
                    detail = "Catalog names updated; working queue and shelf assignments kept."
                self._send_json({"success": True, "message": f"Imported {ins} new, {upd} updated items. {detail}"})
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
            raw_pids = payload.get("product_ids")
            product_ids = [format_product_id(pid) for pid in raw_pids] if raw_pids is not None else None
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
            catalog_rows = db.get_display_catalog_products()
            catalog_map = {p[0]: (p[1], p[2]) for p in catalog_rows}
            records = {pid: catalog_map[pid] for pid in product_ids if pid in catalog_map}
            try:
                ins, upd = db.import_products(records)
                self._send_json({"success": True, "message": f"Transferred {ins + upd} product(s) to total queue."})
            except Exception as e:
                self._send_error_json(str(e))
            return

        if path == "/api/catalog/transfer-to-shelf":
            slot_id = int(payload.get("slot_id", 0))
            product_ids = [format_product_id(pid) for pid in payload.get("product_ids", [])]
            default_stock = int(payload.get("default_stock", 999))
            slot = db.get_slot_by_id(slot_id)
            if not slot:
                self._send_error_json("Slot not found", 404)
                return
            catalog_rows = db.get_display_catalog_products()
            catalog_map = {p[0]: (p[1], p[2]) for p in catalog_rows}
            records = {pid: catalog_map[pid] for pid in product_ids if pid in catalog_map}
            try:
                count = db.assign_catalog_direct_to_slot(slot_id, now_iso, records, default_stock)
                self._send_json({"success": True, "message": f"Assigned {count} catalog product(s) directly to {slot.slot_name} with stock {default_stock}."})
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
                    from mapper.features.web_upload import LocationUpdate
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

        if path == "/api/exceptions/assign":
            prod_id = payload.get("product_id", "").strip()
            if not prod_id:
                self._send_error_json("Product ID is required.", 400)
                return
            floor = clean_location_segment(str(payload.get("floor", "1")))
            side = clean_location_segment(str(payload.get("side", "1")))
            shelf = clean_location_segment(str(payload.get("shelf", "A")))
            try:
                row = int(payload.get("row", 1))
                col = int(payload.get("col", 1))
            except (ValueError, TypeError):
                self._send_error_json("Row and cell must be whole numbers.", 400)
                return

            slot_name = make_slot_name(floor, shelf, row, col, side=side)
            slot_obj = db.get_slot_by_name(slot_name)
            if not slot_obj:
                self._send_error_json(f"Slot {slot_name} does not exist.", 404)
                return

            raw_qty = payload.get("quantity")
            qty = int(raw_qty) if raw_qty is not None and str(raw_qty).strip() != "" else None

            try:
                res_slot = db.assign_exception(prod_id, slot_obj.slot_id, stock_qty=qty)
                self._send_json({
                    "success": True,
                    "slot_name": res_slot,
                    "message": f"Assigned exception {prod_id} to {res_slot} (Qty: {qty if qty is not None else 'null'}). Staged for CSV update."
                })
            except Exception as e:
                self._send_error_json(str(e))
            return

        if path == "/api/exceptions/append-csv":
            csv_path = payload.get("csv_path", "").strip()
            if not csv_path:
                for candidate in ("full_catalogue.csv", "product_id_n_name.csv"):
                    if Path(candidate).exists():
                        csv_path = candidate
                        break
                else:
                    csv_path = "full_catalogue.csv"

            try:
                count = db.append_pending_to_csv(csv_path)
                self._send_json({
                    "success": True,
                    "count": count,
                    "message": f"Successfully appended {count} exception(s) to {Path(csv_path).name}.",
                })
            except Exception as e:
                self._send_error_json(str(e))
            return

        self._send_error_json(f"Unknown POST endpoint: {path}", 404)

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

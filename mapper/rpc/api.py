"""Every method the desktop front end can call, grouped by tab.

Writes return ``{"changes": {...}}`` naming the products, cells and shelves they
touched, so the front end refetches only what it shows. Product search runs on an
in-memory index that is patched after each write and fully reloaded only when
another program changed SQLite.
"""

from __future__ import annotations

import dataclasses
import itertools
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from mapper.core.common import APP_TITLE, MAX_VISIBLE_PRODUCTS, data_directory, iso_timestamp, normalize_sku, split_locations, vietnam_time
from mapper.core.search import ProductIndex
from mapper.features import kiotviet_settings
from mapper.features.csv_import import prepare_import, read_csv, suggest_columns
from mapper.features.location_comparison import (
    ID_HEADERS, LOCATION_HEADERS, LocationDifference, _plain_header, compare_locations, export_comparison,
    location_parts, read_web_locations, suggested_columns, web_code,
)
from mapper.features.web_upload import LocationUpdate, UploadError, WebsiteUploader
from mapper.persistence.database import WarehouseDatabase
from mapper.services import assignment
from mapper.services.cell_lookup import find_cell
from mapper.services.shelf_grid import build_grid, load_grid
from mapper.services.uploads import location_updates, upload_products

METHODS: dict[str, Callable] = {}


def rpc(name: str):
    def register(function):
        METHODS[name] = function
        return function
    return register


def changes(products: Iterable[str] = (), slots: Iterable[str] = (), *, shelves: bool = False,
            catalog: bool = False) -> dict[str, Any]:
    return {"products": sorted(set(products)), "slots": sorted(set(slots)), "shelves": shelves, "catalog": catalog}


def shelf_label(floor: str, side: str, code: str) -> str:
    return f"Floor {floor} — Side {side} — Shelf {code}"


class ProductState:
    """Search indexes plus the location and on-hand facts the product lists show."""

    def __init__(self, db: WarehouseDatabase):
        self.db = db
        self.lock = Lock()
        self.version: tuple[int, int] | None = None
        self.hot = ProductIndex()
        self.catalog = ProductIndex()
        self.placements: dict = {}
        self.on_hand: dict = {}

    def current(self) -> ProductState:
        with self.lock:
            if self.version != self.db.data_version():
                self.hot = ProductIndex(self.db.get_product_records())
                self.catalog = ProductIndex(self.db.get_catalog_products())
                self.placements = self.db.get_placement_details()
                self.on_hand = self.db.get_on_hand_products()
                self.version = self.db.data_version()
        return self

    def patch(self, product_ids: Iterable[str]) -> None:
        """Re-read only these products after a write made by this process."""
        ids = list(dict.fromkeys(product_ids))
        with self.lock:
            if self.version is None or not ids:
                self.version = None
                return
            rows = self.db.get_catalog_rows(ids)
            self.catalog.remove(ids)
            self.catalog.update(rows)
            for pid, state in self.db.get_product_inventory_states(ids).items():
                if state["product"] is None:
                    self.hot.remove([pid])
                else:
                    self.hot.update([(pid, *state["product"])])
                for target, value in ((self.placements, state["placement"]), (self.on_hand, state["on_hand"])):
                    if value is None:
                        target.pop(pid, None)
                    else:
                        target[pid] = value
            self.version = self.db.data_version()

    def row(self, pid: str) -> dict[str, Any]:
        index = self.catalog if pid in self.catalog else self.hot
        name, brand = index.names.get(pid, ("", ""))
        placement, hand = self.placements.get(pid), self.on_hand.get(pid)
        return {
            "product_id": pid, "name": name, "brand": brand, "hot": pid in self.hot,
            "location": placement.slot_name if placement else "",
            "stock": placement.stock_qty if placement else hand.stock_qty if hand else None,
            "on_hand": hand is not None,
        }


def _is_header_row(row: list[object]) -> bool:
    """Tab 7's header rule: the suggested ID and location columns both carry known headers."""
    product, location = suggested_columns(row)
    return (product != location and bool(row[product]) and bool(row[location])
            and _plain_header(row[product]) in ID_HEADERS and _plain_header(row[location]) in LOCATION_HEADERS)


class Api:
    def __init__(self, db_path: Path | str, emit: Callable[[str, Any], None] = lambda _event, _data: None):
        self.db = WarehouseDatabase(db_path)
        self.emit = emit
        self.products = ProductState(self.db)
        self.last_shift: dict[str, Any] | None = None
        self.web_locations: dict[str, str] | None = None
        self.uploader = WebsiteUploader()
        self.browser = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser")
        self.job_ids = itertools.count(1)
        self.web_busy = False

    def call(self, method: str, params: dict[str, Any]) -> Any:
        function = METHODS.get(method)
        if function is None:
            raise LookupError(f"Unknown method {method!r}.")
        return function(self, **params)

    def _written(self, products: Iterable[str] = (), slots: Iterable[str] = (), **flags) -> dict[str, Any]:
        products = list(products)
        if flags.get("catalog"):
            self.products.version = None
        else:
            self.products.patch(products)
        return changes(products, slots, **flags)

    def _slot_products(self, slot_id: int) -> list[str]:
        return [pid for pid, _name, _placement in self.db.get_slot_contents(slot_id)]

    def _slot_name(self, slot_id: int) -> str:
        address = self.db.get_slot_by_id(slot_id)
        if address is None:
            raise KeyError("That shelf cell no longer exists.")
        return address.slot_name

    # --- app ---------------------------------------------------------------
    @rpc("app.info")
    def info(self) -> dict[str, Any]:
        return {"title": APP_TITLE, "database": str(self.db.path), "max_rows": MAX_VISIBLE_PRODUCTS}

    # --- product lists (tabs 2, 3, 6) ----------------------------------------
    @rpc("products.search")
    def search(self, query: str = "", scope: str = "catalog", order: str = "plain", limit: int = MAX_VISIBLE_PRODUCTS,
               match_locations: bool = False) -> dict[str, Any]:
        """scope: hot | catalog. order: plain (exact ID first), queue (unassigned first), primal (placed first)."""
        state = self.products.current()
        index = state.hot if scope == "hot" else state.catalog
        location_text = {pid: split_locations(p.slot_name) for pid, p in state.placements.items()}
        also = None
        if match_locations:
            def also(pid: str, key: str) -> bool:
                return any(key in normalize_sku(name).casefold() for name in location_text.get(pid, ()))
        matches = index.matches(query, also=also)
        ranks = {
            "queue": {"before": lambda pid: pid in state.placements},
            "primal": {"after": lambda pid: pid not in state.placements},
        }.get(order, {})
        rows = [state.row(pid) for pid in index.top(matches, query, limit=limit, **ranks)]
        ready = sum(pid not in state.placements and pid not in state.on_hand for pid in matches) if scope == "hot" else None
        return {"rows": rows, "total": len(matches), "size": len(index), "ready": ready}

    @rpc("products.lookup")
    def lookup(self, query: str) -> dict[str, Any] | None:
        """The exact product a typed or scanned ID names, with its location facts."""
        state = self.products.current()
        pid = state.catalog.exact_id(query) or state.hot.exact_id(query)
        return state.row(pid) if pid else None

    @rpc("products.locations")
    def product_locations(self, product_id: str) -> list[dict[str, Any]]:
        names = self.db.get_product_locations(product_id)
        return [address for address in (self.db.get_slot_by_name(name) for name in names) if address]

    # --- shelves and cells ----------------------------------------------------
    @rpc("shelves.list")
    def shelves(self) -> list[dict[str, Any]]:
        return [{"shelf_id": shelf_id, "floor": floor, "side": side, "code": code, "label": shelf_label(floor, side, code)}
                for shelf_id, floor, side, code in self.db.list_shelves()]

    @rpc("shelves.find")
    def find_shelf(self, floor: str, side: str, code: str) -> int | None:
        return self.db.get_shelf_id(floor, code, side=side)

    @rpc("shelves.grid")
    def grid(self, shelf_id: int) -> dict[str, Any]:
        grid, contents = load_grid(self.db, shelf_id)
        return {"shelf_id": shelf_id, "label": shelf_label(*grid.key), "floor": grid.floor, "side": grid.side,
                "code": grid.shelf_code, "layout": grid.layout, "rows": grid.rows,
                "contents": [self._content_row(pid, name, placement) for pid, name, placement in contents]}

    @staticmethod
    def _content_row(pid: str, name: str, placement, modified: str | None = None) -> dict[str, Any]:
        return {"product_id": pid, "name": name, "slot": placement.slot_name, "stock": placement.stock_qty,
                "assigned_at": vietnam_time(placement.assigned_at), "modified_at": vietnam_time(modified)}

    @rpc("cells.address")
    def address(self, floor: str, side: str, code: str, row: int, cell: int):
        return self.db.get_slot_address(floor, side, code, int(row), int(cell))

    @rpc("cells.get")
    def cell(self, slot_id: int):
        return self.db.get_slot_by_id(slot_id)

    @rpc("cells.contents")
    def contents(self, slot_id: int) -> list[dict[str, Any]]:
        modified = self.db.get_slot_stock_modifications(slot_id)
        return [self._content_row(pid, name, placement, modified.get(pid))
                for pid, name, placement in self.db.get_slot_contents(slot_id)]

    @rpc("cells.find")
    def find(self, query: str) -> dict[str, Any]:
        found = find_cell(self.db, query)
        return {"address": found.address,
                "shelves": [{"shelf_id": s[0], "label": shelf_label(*s[1:])} for s in found.shelves]}

    @rpc("cells.swap")
    def swap(self, first_slot_id: int, second_slot_id: int) -> dict[str, Any]:
        moved = self._slot_products(first_slot_id) + self._slot_products(second_slot_id)
        counts = self.db.swap_slot_contents(first_slot_id, second_slot_id)
        return {"counts": counts, "changes": self._written(
            moved, (self._slot_name(first_slot_id), self._slot_name(second_slot_id)))}

    @rpc("cells.combine")
    def combine(self, source_slot_id: int, target_slot_id: int, merge: bool = False) -> dict[str, Any]:
        """Without merge, products in both cells are reported and nothing changes."""
        source, target = self._slot_products(source_slot_id), self._slot_products(target_slot_id)
        overlaps = sorted(set(source) & set(target))
        if overlaps and not merge:
            return {"needs_merge": overlaps}
        count = self.db.combine_slot_contents(source_slot_id, target_slot_id, merge_duplicates=merge)
        return {"count": count, "changes": self._written(
            source + target, (self._slot_name(source_slot_id), self._slot_name(target_slot_id)))}

    @rpc("cells.to_on_hand")
    def cell_to_on_hand(self, slot_id: int, product_ids: list[str] | None = None) -> dict[str, Any]:
        moved = product_ids if product_ids is not None else self._slot_products(slot_id)
        count = self.db.move_slot_to_on_hand(slot_id, iso_timestamp(), product_ids)
        return {"count": count, "changes": self._written(moved, (self._slot_name(slot_id),))}

    # --- tab 2: assignment ---------------------------------------------------
    def _records(self, product_ids: Iterable[str]) -> dict[str, tuple[str, str]]:
        """Assignment records keep the stored name; an unknown SKU is named after itself."""
        state = self.products.current()
        records = {}
        for pid in map(normalize_sku, product_ids):
            name, _brand = state.catalog.names.get(pid) or state.hot.names.get(pid) or (pid, "")
            records[pid] = (name, "")
        return records

    def _old_slots(self, product_ids: Iterable[str]) -> list[str]:
        return [name for names in self.db.get_location_sets(product_ids).values() for name in names]

    @rpc("assign.products")
    def assign_products(self, slot_id: int, quantities: dict[str, int]) -> dict[str, Any]:
        old = self._old_slots(quantities)
        moved = assignment.assign_products(self.db, slot_id, self._records(quantities), quantities)
        return {"count": moved, "changes": self._written(quantities, [*old, self._slot_name(slot_id)])}

    @rpc("assign.shift_queue")
    def shift_queue(self, slot_id: int, product_ids: list[str]) -> dict[str, Any]:
        refusal = assignment.shift_prefix_error(product_ids)
        if refusal:
            raise ValueError(refusal)
        return self._shift(slot_id, product_ids)

    @rpc("assign.shift_catalog")
    def shift_catalog(self, slot_id: int, product_ids: list[str]) -> dict[str, Any]:
        refusal = assignment.catalog_shift_error(product_ids)
        if refusal:
            raise ValueError(refusal)
        return self._shift(slot_id, product_ids)

    def _shift(self, slot_id: int, product_ids: list[str]) -> dict[str, Any]:
        old = self._old_slots(product_ids)
        moved, self.last_shift = assignment.shift_transfer(self.db, slot_id, self._records(product_ids))
        return {"count": moved, "can_revert": True,
                "changes": self._written(product_ids, [*old, self._slot_name(slot_id)])}

    @rpc("assign.on_hand")
    def assign_on_hand(self, slot_id: int, product_ids: list[str] | None = None) -> dict[str, Any]:
        moved_ids = list(self.db.get_on_hand_products()) if product_ids is None else product_ids
        moved, revert = assignment.assign_on_hand(self.db, slot_id, product_ids)
        if revert is not None:
            self.last_shift = revert
        return {"count": moved, "can_revert": revert is not None,
                "changes": self._written(moved_ids, (self._slot_name(slot_id),))}

    @rpc("assign.revert")
    def revert(self) -> dict[str, Any]:
        if self.last_shift is None:
            raise ValueError("There is no Shift transfer to revert.")
        products = [record["product_id"] for record in self.last_shift["products"]]
        slots = [self._slot_name(self.last_shift["slot_id"]), *self._old_slots(products)]
        count = self.db.revert_shift_transfer(self.last_shift)
        self.last_shift = None
        slots += self._old_slots(products)
        return {"count": count, "changes": self._written(products, slots)}

    @rpc("assign.can_revert")
    def can_revert(self) -> bool:
        return self.last_shift is not None

    @rpc("onhand.list")
    def on_hand(self) -> list[dict[str, Any]]:
        state = self.products.current()
        return [{"product_id": item.product_id, "name": state.row(item.product_id)["name"], "stock": item.stock_qty,
                 "queued_at": vietnam_time(item.queued_at)}
                for item in sorted(state.on_hand.values(), key=lambda item: (item.queued_at, item.product_id))]

    @rpc("onhand.set_stock")
    def set_on_hand_stock(self, product_id: str, quantity: int) -> dict[str, Any]:
        self.db.update_on_hand_stock(product_id, quantity, modified_at=iso_timestamp())
        return {"changes": self._written([normalize_sku(product_id)])}

    @rpc("placements.set_stock")
    def set_placement_stock(self, product_id: str, quantity: int, slot_id: int) -> dict[str, Any]:
        self.db.update_placement_stock(product_id, quantity, expected_slot_id=slot_id, modified_at=iso_timestamp())
        pid = normalize_sku(product_id)
        return {"changes": self._written([pid], self._old_slots([pid]))}

    # --- tab 1: shelf designer -------------------------------------------------
    @rpc("designer.preview")
    def preview(self, floor: str, side: str, code: str, layout: list[int], shelf_id: int | None = None) -> dict[str, Any]:
        """A layout's grid with saved counts; refused when it would drop occupied cells or clash."""
        existing = self.db.get_shelf_id(floor, code, side=side)
        if existing is not None and existing != shelf_id:
            raise ValueError(f"Floor {floor} / Side {side} / Shelf {code} already exists. Load it to edit.")
        contents = self.db.get_shelf_contents(shelf_id) if shelf_id is not None else []
        saved_grid = load_grid(self.db, shelf_id)[0] if shelf_id is not None else None
        grid = build_grid(floor, side, code, layout)
        if saved_grid is not None:
            kept = {(cell.row, cell.cell) for cell in grid.cells()}
            occupied = sorted(cell.slot_name for cell in saved_grid.cells()
                              if cell.count and (cell.row, cell.cell) not in kept)
            if occupied:
                raise ValueError(f"Return or move the products in {occupied[0]} before removing this row or cell.")
            by_position = {(cell.row, cell.cell): cell.count for cell in saved_grid.cells()}
            grid = build_grid(floor, side, code, layout, [
                cell.slot_name for cell in grid.cells() for _ in range(by_position.get((cell.row, cell.cell), 0))])
        return {"floor": grid.floor, "side": grid.side, "code": grid.shelf_code, "layout": grid.layout,
                "rows": grid.rows, "saved_products": len(contents)}

    @rpc("designer.commit")
    def commit(self, floor: str, side: str, code: str, layout: list[int], shelf_id: int | None = None) -> dict[str, Any]:
        shelf_id = self.db.commit_shelf(floor, code, layout, {}, set(), side=side, shelf_id=shelf_id)
        return {"shelf_id": shelf_id, "changes": self._written(shelves=True)}

    @rpc("designer.delete")
    def delete_shelf(self, shelf_id: int) -> dict[str, Any]:
        self.db.delete_shelf(shelf_id)
        return {"changes": self._written(shelves=True)}

    @rpc("csv.inspect")
    def inspect_csv(self, path: str, catalog: bool = False) -> dict[str, Any]:
        data = read_csv(Path(path))
        return {"headers": data.headers, "rows": len(data.rows), "suggested": suggest_columns(data.headers, catalog=catalog)}

    @rpc("csv.import")
    def import_csv(self, path: str, id_column: int, name_column: int, other_column: int = -1,
                   catalog: bool = False) -> dict[str, Any]:
        prepared = prepare_import(read_csv(Path(path)), id_column, name_column, other_column)
        importer = self.db.import_catalog_products if catalog else self.db.import_products
        inserted, updated = importer(prepared.records)
        return {"inserted": inserted, "updated": updated, "skipped": prepared.skipped,
                "duplicates": prepared.duplicates, "changes": self._written(catalog=True)}

    # --- tab 6: special exceptions -------------------------------------------
    @rpc("exceptions.find")
    def find_exception(self, product_id: str) -> dict[str, Any] | None:
        found = self.db.find_product_locations(product_id)
        return None if found is None else {"product_id": normalize_sku(product_id), "name": found[0],
                                           "locations": list(found[1])}

    @rpc("exceptions.assign")
    def assign_exception(self, product_id: str, slot_id: int, stock: int | None = None,
                         name: str | None = None) -> dict[str, Any]:
        pid = normalize_sku(product_id)
        slot = self.db.assign_exception(pid, slot_id, None, stock, name or None)
        return {"slot": slot, "changes": self._written([pid], [slot])}

    @rpc("exceptions.remove")
    def remove_exception(self, product_id: str, slot_id: int) -> dict[str, Any]:
        pid = normalize_sku(product_id)
        slot = self._slot_name(slot_id)
        self.db.remove_exception_from_slot(pid, slot_id)
        return {"changes": self._written([pid], [slot, *self._old_slots([pid])])}

    @rpc("exceptions.save_name")
    def save_name(self, product_id: str, name: str) -> dict[str, Any]:
        self.db.update_staged_exception_name(product_id, name)
        return {"changes": self._written([normalize_sku(product_id)])}

    @rpc("exceptions.staged")
    def staged(self) -> list[dict[str, Any]]:
        return [{**row, "created_at": vietnam_time(row["created_at"])} for row in self.db.get_staged_exception_summary()]

    @rpc("exceptions.multi")
    def multi(self) -> list[dict[str, Any]]:
        return [{"product_id": pid, "name": name, "locations": list(locations)}
                for pid, name, locations in self.db.get_multi_location_products()]

    @rpc("exceptions.append_csv")
    def append_csv(self, path: str, product_ids: list[str] | None = None) -> dict[str, Any]:
        return {"count": self.db.append_pending_to_csv(path, product_ids), "changes": changes()}

    @rpc("exceptions.add_catalog")
    def add_catalog(self, product_ids: list[str] | None = None) -> dict[str, Any]:
        return {"count": self.db.add_staged_to_catalog(product_ids), "changes": changes()}

    @rpc("exceptions.wipe")
    def wipe(self, product_id: str) -> dict[str, Any]:
        pid = normalize_sku(product_id)
        slots = self._old_slots([pid])
        self.db.wipe_staged_exception(pid)
        return {"changes": self._written([pid], slots)}

    # --- tab 7 and browser work -------------------------------------------------
    @rpc("settings.get")
    def settings(self) -> dict[str, Any]:
        url, tabs = kiotviet_settings.load_settings()
        return {"url": url, "tabs": tabs, "max_tabs": kiotviet_settings.MAX_UPLOAD_TABS}

    @rpc("settings.save")
    def save_settings(self, url: str, tabs: int) -> dict[str, Any]:
        url, tabs = kiotviet_settings.save_settings(url, tabs)
        self.uploader.store_url = url
        return {"url": url, "tabs": tabs}

    @rpc("workbook.inspect")
    def inspect_workbook(self, path: str) -> dict[str, Any]:
        """Each sheet's first rows plus a guessed header row for the column dialog."""
        from openpyxl import load_workbook
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheets = {name: [[("" if value is None else str(value)) for value in row]
                             for row in workbook[name].iter_rows(max_row=15, values_only=True)]
                      for name in workbook.sheetnames}
        finally:
            workbook.close()
        guess = next(((name, number) for name, rows in sheets.items()
                      for number, row in enumerate(rows, 1) if row and _is_header_row(row)),
                     (next(iter(sheets), ""), 1))
        return {"sheets": sheets, "sheet": guess[0], "header_row": guess[1]}

    @rpc("compare.run")
    def compare(self, path: str | None = None, sheet: str | None = None, header_row: int = 1,
                id_column: int = 0, location_column: int = 1) -> dict[str, Any]:
        """Import a KiotViet export (or reuse the last one) and compare it with saved locations."""
        if path is not None:
            self.web_locations = read_web_locations(path, sheet, header_row, id_column, location_column)
        if self.web_locations is None:
            raise ValueError("Import website data before comparing locations.")
        local = self.db.get_location_sets()
        differences, missing = compare_locations(local, self.web_locations)
        return {"web_products": len(self.web_locations),
                "differences": [{**dataclasses.asdict(row), "web_code": web_code(row.product_id)} for row in differences],
                "missing": [{"product_id": pid, "web_code": web_code(pid), "local": ", ".join(local[pid])}
                            for pid in missing]}

    @rpc("compare.export")
    def export(self, differences: list[dict[str, Any]]) -> str:
        result_dir = data_directory() / "exports" / "location_comparison"
        result_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = result_dir / f"kiotviet_location_comparison_{timestamp}.xlsx"
        counter = 2
        while destination.exists():
            destination = result_dir / f"kiotviet_location_comparison_{timestamp}_{counter}.xlsx"
            counter += 1
        export_comparison(destination, [
            LocationDifference(row["product_id"], row["wrong_location"], row["true_location"], row["can_resync"])
            for row in differences
        ])
        return str(destination)

    def _start_browser_job(self, work: Callable[[Callable, Callable], str]) -> int:
        if self.web_busy:
            raise UploadError("Wait for the current Chrome task to finish.")
        self.web_busy = True
        job = next(self.job_ids)

        def run():
            report = lambda kind, text: self.emit("job", {"job": job, "kind": kind, "text": text})
            try:
                report("done", work(lambda text: report("progress", text), lambda pid: report("item_done", pid)))
            except Exception as error:  # every failure reaches the UI as a job event
                report("error", str(error))
            finally:
                self.web_busy = False

        self.browser.submit(run)
        return job

    @rpc("web.connect")
    def connect(self) -> int:
        def work(progress, _done):
            self.uploader.store_url = kiotviet_settings.load_settings()[0]
            try:
                return self.uploader.connect(progress)
            finally:
                self.uploader.disconnect()
        return self._start_browser_job(work)

    def _run_batch(self, jobs, *, location_only: bool, save: bool | None, tab_count: int = 1) -> int:
        if not jobs:
            raise ValueError("No products to update.")

        def work(progress, done):
            self.uploader.store_url = kiotviet_settings.load_settings()[0]
            return self.uploader.run_batch(jobs, progress, done, location_only=location_only, save=save, tab_count=tab_count)
        return self._start_browser_job(work)

    @rpc("web.update_locations")
    def update_locations(self, product_ids: list[str], save_each: bool = False) -> int:
        return self._run_batch(location_updates(self.db, product_ids), location_only=True, save=True if save_each else None)

    @rpc("web.upload_cell")
    def upload_cell(self, slot_id: int, product_ids: list[str] | None = None, save_each: bool = False) -> int:
        placements = [(pid, placement) for pid, _name, placement in self.db.get_slot_contents(slot_id)
                      if product_ids is None or pid in product_ids]
        return self._run_batch(upload_products(self.db, placements), location_only=False, save=True if save_each else None)

    @rpc("web.resync")
    def resync(self, differences: list[dict[str, Any]]) -> int:
        updates = [LocationUpdate(row["product_id"], location_parts(row["true_location"]))
                   for row in differences if row["can_resync"]]
        return self._run_batch(updates, location_only=True, save=True, tab_count=kiotviet_settings.load_settings()[1])

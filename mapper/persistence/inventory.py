"""Placements, the on-hand queue, cell switch/combine, and Shift transfers."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import closing
from typing import Any

from mapper.core.common import iso_timestamp, normalize_sku
from .models import OnHandProduct, Placement, ProductLocation, validate_stock_quantity
from .shared import (
    IN_IDS, LOCATION_SQL, PRODUCT_NAME_SQL, check_slots, ids_param, location_names, merge_cell_duplicates,
    move_exception_cells, normalize_records, record_stock_modification, relocate_staging, remove_from_slot,
)

# Restore order for a Shift transfer revert; extra locations defer their placement foreign key.
TRANSFER_TABLES = ('exception_placements', 'placements', 'on_hand_queue', 'hot_sellers', 'wait_to_update_csv')
UNKNOWN_STOCK = (None, 999)


def _unique_skus(product_ids: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(normalize_sku(pid) for pid in product_ids))


def _require_time(value: str | None, label: str) -> str:
    if not value:
        raise ValueError(f'The {label} time must include a timezone.')
    return iso_timestamp(value)


class InventoryOperations:
    def get_product_inventory_states(self, product_ids):
        ids = _unique_skus(product_ids)
        states = {pid: {'product': None, 'placement': None, 'on_hand': None} for pid in ids}
        if not ids:
            return states
        batch = ids_param(ids)
        with closing(self.connect()) as c:
            for row in c.execute(f"""SELECT h.product_id, {PRODUCT_NAME_SQL} AS name, COALESCE(c.brand_name,'') AS brand
                                     FROM hot_sellers h JOIN catalog_products c USING(product_id)
                                     WHERE h.product_id {IN_IDS}""", (batch,)):
                states[row['product_id']]['product'] = (row['name'], row['brand'])
            rows = c.execute(f"""SELECT l.*, s.slot_name FROM ({LOCATION_SQL}) l JOIN slots s USING(slot_id)
                                 WHERE l.product_id {IN_IDS} ORDER BY l.extra, s.slot_name""", (batch,)).fetchall()
            for pid, placement in self._group_placements(rows).items():
                states[pid]['placement'] = placement
            for row in c.execute(f'SELECT * FROM on_hand_queue WHERE product_id {IN_IDS}', (batch,)):
                states[row['product_id']]['on_hand'] = OnHandProduct(row['product_id'], row['stock_qty'], row['queued_at'])
        return states

    @staticmethod
    def _group_placements(rows):
        """Rows ordered primary-first become one Placement per product listing all its locations."""
        grouped = {}
        for row in rows:
            grouped.setdefault(row['product_id'], [[], row['stock_qty'], row['assigned_at']])[0].append(row['slot_name'])
        return {pid: Placement(', '.join(names), qty, assigned) for pid, (names, qty, assigned) in grouped.items()}

    def get_placements(self):
        return {pid: value.slot_name for pid, value in self.get_placement_details().items()}

    def get_placement_details(self):
        with closing(self.connect()) as c:
            return self._group_placements(c.execute(
                f'SELECT l.*, s.slot_name FROM ({LOCATION_SQL}) l JOIN slots s USING(slot_id) ORDER BY l.extra, s.slot_name'))

    def get_all_placement_items(self):
        with closing(self.connect()) as c:
            return [(r['product_id'], r['slot_name'], r['stock_qty'], r['assigned_at']) for r in c.execute(
                f'SELECT l.*, s.slot_name FROM ({LOCATION_SQL}) l JOIN slots s USING(slot_id) ORDER BY l.extra, s.slot_name')]

    def get_location_sets(self, product_ids: Iterable[str] | None = None) -> dict[str, tuple[str, ...]]:
        """Every saved location of each product, sorted by name; all placed products when ids is None."""
        where, params = ('', ()) if product_ids is None else (f'WHERE l.product_id {IN_IDS}', (ids_param(_unique_skus(product_ids)),))
        with closing(self.connect()) as c:
            return {row[0]: tuple(dict.fromkeys(row[1].split('\x1f'))) for row in c.execute(
                f"""SELECT l.product_id, group_concat(s.slot_name, char(31) ORDER BY s.slot_name)
                    FROM ({LOCATION_SQL}) l JOIN slots s USING(slot_id) {where} GROUP BY l.product_id""", params)}

    def get_product_location(self, product_id):
        pid = normalize_sku(product_id)
        with closing(self.connect()) as c:
            row = c.execute("""SELECT p.*, s.slot_name, s.slot_number, s.row_number, s.shelf_id
                               FROM placements p JOIN slots s USING(slot_id) WHERE p.product_id=?""", (pid,)).fetchone()
            if row is None:
                return None
            names = location_names(c, pid)
        return ProductLocation(row['shelf_id'], row['row_number'], row['slot_number'],
                               Placement(', '.join(names), row['stock_qty'], row['assigned_at']))

    def get_product_locations(self, product_id):
        with closing(self.connect()) as c:
            return location_names(c, normalize_sku(product_id))

    def get_on_hand_products(self):
        with closing(self.connect()) as c:
            return {r['product_id']: OnHandProduct(r['product_id'], r['stock_qty'], r['queued_at'])
                    for r in c.execute('SELECT * FROM on_hand_queue ORDER BY queued_at, product_id')}

    def add_to_on_hand(self, quantities, queued_at):
        quantities = {normalize_sku(pid): qty for pid, qty in quantities.items()}
        queued_at = _require_time(queued_at, 'on-hand')
        for qty in quantities.values():
            if qty is not None:
                validate_stock_quantity(qty)
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            placed = c.execute(f"""SELECT j.value FROM json_each(?) j JOIN placements p ON p.product_id = j.value
                                   ORDER BY j.key LIMIT 1""", (ids_param(quantities),)).fetchone()
            if placed:
                raise ValueError(f'Product {placed[0]} is already assigned to a shelf.')
            c.executemany("""INSERT INTO on_hand_queue(product_id,stock_qty,queued_at) VALUES (?,?,?)
                             ON CONFLICT(product_id) DO UPDATE SET stock_qty=excluded.stock_qty, queued_at=excluded.queued_at""",
                          [(pid, qty, queued_at) for pid, qty in quantities.items()])
        return len(quantities)

    def get_slot_stock_modifications(self, slot_id):
        with closing(self.connect()) as c:
            return dict(c.execute(f"""SELECT m.product_id, m.modified_at FROM stock_modifications m
                                      WHERE product_id IN (SELECT product_id FROM ({LOCATION_SQL}) WHERE slot_id=?)""", (slot_id,)))

    def update_on_hand_stock(self, product_id, quantity, *, modified_at=None):
        validate_stock_quantity(quantity)
        pid = normalize_sku(product_id)
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('UPDATE on_hand_queue SET stock_qty=? WHERE product_id=?', (quantity, pid)).rowcount != 1:
                raise KeyError(f'Product {pid} is no longer in the on-hand queue.')
            record_stock_modification(c, pid, modified_at)

    def swap_slot_contents(self, first_slot_id, second_slot_id):
        if first_slot_id == second_slot_id:
            raise ValueError('Choose two different cells to switch.')
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            check_slots(c, first_slot_id, second_slot_id)
            counts = dict(c.execute(f'SELECT slot_id, COUNT(*) FROM ({LOCATION_SQL}) WHERE slot_id IN (?,?) GROUP BY slot_id',
                                    (first_slot_id, second_slot_id)))
            c.execute('UPDATE placements SET slot_id=CASE slot_id WHEN ? THEN ? ELSE ? END WHERE slot_id IN (?,?)',
                      (first_slot_id, second_slot_id, first_slot_id, first_slot_id, second_slot_id))
            move_exception_cells(c, {first_slot_id: second_slot_id, second_slot_id: first_slot_id})
        return counts.get(first_slot_id, 0), counts.get(second_slot_id, 0)

    def combine_slot_contents(self, source_slot_id, target_slot_id, *, merge_duplicates=False):
        if source_slot_id == target_slot_id:
            raise ValueError('Choose two different cells to combine.')
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            check_slots(c, source_slot_id, target_slot_id)
            overlaps = [row[0] for row in c.execute(f"""SELECT product_id FROM ({LOCATION_SQL}) WHERE slot_id IN (?,?)
                                                       GROUP BY product_id HAVING COUNT(*)>1""", (source_slot_id, target_slot_id))]
            if overlaps and not merge_duplicates:
                raise ValueError(f'Product {overlaps[0]} is already in both cells. Both cells are unchanged.')
            count = c.execute(f'SELECT COUNT(*) FROM ({LOCATION_SQL}) WHERE slot_id=?', (source_slot_id,)).fetchone()[0]
            if overlaps:
                merge_cell_duplicates(c, overlaps, source_slot_id, target_slot_id)
            c.execute('UPDATE placements SET slot_id=? WHERE slot_id=?', (target_slot_id, source_slot_id))
            move_exception_cells(c, {source_slot_id: target_slot_id})
        return count

    def assign_on_hand_to_slot(self, slot_id, assigned_at, product_ids=None):
        assigned_at = _require_time(assigned_at, 'assignment')
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            check_slots(c, slot_id)
            ids = (tuple(row[0] for row in c.execute('SELECT product_id FROM on_hand_queue')) if product_ids is None
                   else _unique_skus(product_ids))
            batch = ids_param(ids)
            missing = c.execute("""SELECT value FROM json_each(?)
                                   WHERE value NOT IN (SELECT product_id FROM on_hand_queue) ORDER BY key LIMIT 1""",
                                (batch,)).fetchone()
            if missing:
                raise KeyError(f'Product {missing[0]} is no longer in the on-hand queue.')
            placed = c.execute(f'SELECT product_id FROM placements WHERE product_id {IN_IDS} LIMIT 1', (batch,)).fetchone()
            if placed:
                raise ValueError(f'Product {placed[0]} is already assigned to a shelf.')
            c.execute(f"""INSERT INTO placements(product_id,slot_id,stock_qty,assigned_at)
                          SELECT product_id, ?, COALESCE(stock_qty, 999), ? FROM on_hand_queue WHERE product_id {IN_IDS}""",
                      (slot_id, assigned_at, batch))
            c.execute(f'DELETE FROM on_hand_queue WHERE product_id {IN_IDS}', (batch,))
        return len(ids)

    def assign_catalog_direct_to_slot(self, slot_id, assigned_at, products, default_stock=999, *, quantities=None):
        products = normalize_records(products)
        assigned_at = _require_time(assigned_at, 'assignment')
        validate_stock_quantity(default_stock)
        if quantities is not None:
            quantities = {normalize_sku(pid): qty for pid, qty in quantities.items()}
            if quantities.keys() != products.keys():
                raise ValueError('Enter stock for every selected product.')
            for qty in quantities.values():
                validate_stock_quantity(qty)
        batch = ids_param(products)
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            check_slots(c, slot_id)
            c.executemany('INSERT INTO catalog_products(product_id,full_name) VALUES (?,?) ON CONFLICT DO NOTHING',
                          [(pid, full_name) for pid, (full_name, _brand) in products.items()])
            # Read before deleting: 0 is a known count; 999 and NULL are unknown.
            queued = dict(c.execute(f'SELECT product_id, stock_qty FROM on_hand_queue WHERE product_id {IN_IDS}', (batch,)))
            placed = {row[0]: (row[1], row[2]) for row in c.execute(
                f'SELECT product_id, slot_id, stock_qty FROM placements WHERE product_id {IN_IDS}', (batch,))}

            def stock(pid):
                if quantities is not None:
                    return quantities[pid]
                known = [queued.get(pid), placed.get(pid, (None, None))[1]]
                return next((qty for qty in known if qty not in UNKNOWN_STOCK), default_stock)

            c.execute(f'DELETE FROM exception_placements WHERE slot_id=? AND product_id {IN_IDS}', (slot_id, batch))
            c.executemany("""INSERT INTO placements(product_id,slot_id,stock_qty,assigned_at) VALUES (?,?,?,?)
                             ON CONFLICT(product_id) DO UPDATE SET slot_id=excluded.slot_id,
                             stock_qty=excluded.stock_qty, assigned_at=excluded.assigned_at""",
                          [(pid, slot_id, stock(pid), assigned_at) for pid in products])
            c.execute(f'DELETE FROM on_hand_queue WHERE product_id {IN_IDS}', (batch,))
            moved_from: dict[int, list[str]] = {}
            for pid, (old_slot, _qty) in placed.items():
                if old_slot != slot_id:
                    moved_from.setdefault(old_slot, []).append(pid)
            for old_slot, pids in moved_from.items():
                relocate_staging(c, {old_slot: slot_id}, pids)
        return len(products)

    def capture_shift_transfer(self, product_ids, slot_id):
        ids = _unique_skus(product_ids)
        records = {pid: {'product_id': pid} | {table: [] for table in TRANSFER_TABLES} for pid in ids}
        with closing(self.connect()) as c:
            for table in TRANSFER_TABLES:
                for row in c.execute(f'SELECT * FROM {table} WHERE product_id {IN_IDS}', (ids_param(ids),)):
                    records[row['product_id']][table].append(dict(row))
        return {'slot_id': slot_id, 'products': list(records.values())}

    def revert_shift_transfer(self, transfer_data: dict[str, Any]):
        records = transfer_data.get('products', [])
        ids = [record['product_id'] for record in records]
        batch = ids_param(ids)
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            current = dict(c.execute(f'SELECT product_id, slot_id FROM placements WHERE product_id {IN_IDS}', (batch,)))
            moved = next((pid for pid in ids if current.get(pid) != transfer_data['slot_id']), None)
            if moved is not None:
                raise ValueError(f'{moved} has moved since the Shift transfer. Nothing was reverted.')
            for table in TRANSFER_TABLES:
                c.execute(f'DELETE FROM {table} WHERE product_id {IN_IDS}', (batch,))
                rows = [row for record in records for row in record[table]]
                if rows:
                    columns = list(rows[0])
                    c.executemany(f'INSERT INTO {table} ({", ".join(columns)}) VALUES ({", ".join("?" for _ in columns)})',
                                  [tuple(row[column] for column in columns) for row in rows])
        return len(records)

    def move_slot_to_on_hand(self, slot_id, queued_at, product_ids=None):
        queued_at = _require_time(queued_at, 'on-hand')
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            check_slots(c, slot_id)
            available = {row[0] for row in c.execute(f'SELECT product_id FROM ({LOCATION_SQL}) WHERE slot_id=?', (slot_id,))}
            ids = available if product_ids is None else {normalize_sku(pid) for pid in product_ids}
            if ids - available:
                raise KeyError(f'Product {sorted(ids - available)[0]} is no longer in that shelf address.')
            remove_from_slot(c, slot_id, ids, queued_at)
        return len(ids)

    def move_product_to_on_hand(self, product_id, queued_at):
        """Remove all locations of one SKU, retaining its one count atomically."""
        pid, queued_at = normalize_sku(product_id), iso_timestamp(queued_at)
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            slots = [row[0] for row in c.execute(f'SELECT slot_id FROM ({LOCATION_SQL}) WHERE product_id=?', (pid,))]
            if slots:
                c.execute(f'DELETE FROM wait_to_update_csv WHERE product_id=? AND slot_id {IN_IDS}', (pid, ids_param(slots)))
                c.execute('DELETE FROM exception_placements WHERE product_id=?', (pid,))
                c.execute('INSERT INTO on_hand_queue(product_id,stock_qty,queued_at) SELECT product_id, stock_qty, ? '
                          'FROM placements WHERE product_id=?', (queued_at, pid))
                c.execute('DELETE FROM placements WHERE product_id=?', (pid,))
        return len(slots)

    def update_placement_stock(self, product_id, quantity, *, expected_slot_id=None, modified_at=None):
        validate_stock_quantity(quantity)
        pid = normalize_sku(product_id)
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            if expected_slot_id is not None and not c.execute(
                    f'SELECT 1 FROM ({LOCATION_SQL}) WHERE product_id=? AND slot_id=?', (pid, expected_slot_id)).fetchone():
                raise KeyError(f'Product {pid} is no longer in that shelf address.')
            if c.execute('UPDATE placements SET stock_qty=? WHERE product_id=?', (quantity, pid)).rowcount != 1:
                raise KeyError(f'Product {pid} has no shelf placement.')
            record_stock_modification(c, pid, modified_at)

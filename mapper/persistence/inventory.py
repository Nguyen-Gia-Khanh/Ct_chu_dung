from __future__ import annotations

from contextlib import closing
from typing import Any
from mapper.core.common import iso_timestamp, normalise_sku, clean_product_name
from .models import OnHandProduct, Placement, ProductLocation, validate_stock_quantity

# Every location reads its quantity from the one primary placement.
LOCATION_SQL = """SELECT p.product_id, p.slot_id, p.stock_qty, p.assigned_at, 0 AS extra
                  FROM placements p
                  UNION ALL
                  SELECT e.product_id, e.slot_id, p.stock_qty, e.assigned_at, 1 AS extra
                  FROM exception_placements e JOIN placements p USING(product_id)"""


class InventoryOperations:
    def _import_transfer_products(self, connection, records):
        for pid, (name, _brand) in records.items():
            connection.execute('INSERT INTO catalog_products(product_id,full_name) VALUES (?,?) ON CONFLICT DO NOTHING',
                               (pid, clean_product_name(name)))

    def get_product_inventory_states(self, product_ids):
        ids = tuple(dict.fromkeys(normalise_sku(pid) for pid in product_ids))
        states = {pid: {'product': None, 'placement': None, 'on_hand': None} for pid in ids}
        if not ids:
            return states
        with closing(self.connect()) as c:
            for offset in range(0, len(ids), 400):
                batch = ids[offset:offset+400]
                marks = ','.join('?' for _ in batch)
                for row in c.execute(f"""SELECT h.product_id, COALESCE(c.full_name,c.brand_name,h.product_id) AS name,
                                      COALESCE(c.brand_name,'') AS brand FROM hot_sellers h JOIN catalog_products c USING(product_id)
                                      WHERE h.product_id IN ({marks})""", batch):
                    states[row['product_id']]['product'] = (row['name'], row['brand'])
                rows = c.execute(f"""SELECT l.*,s.slot_name FROM ({LOCATION_SQL}) l JOIN slots s USING(slot_id)
                                     WHERE l.product_id IN ({marks}) ORDER BY l.extra,s.slot_name""", batch).fetchall()
                for pid, placement in self._group_placements(rows).items():
                    states[pid]['placement'] = placement
                for row in c.execute(f'SELECT * FROM on_hand_queue WHERE product_id IN ({marks})', batch):
                    states[row['product_id']]['on_hand'] = OnHandProduct(row['product_id'],row['stock_qty'],row['queued_at'])
        return states

    @staticmethod
    def _group_placements(rows):
        grouped = {}
        for row in rows:
            info = grouped.setdefault(row['product_id'], [[], row['stock_qty'], row['assigned_at']])
            info[0].append(row['slot_name'])
        return {pid: Placement(', '.join(names), qty, assigned) for pid,(names,qty,assigned) in grouped.items()}

    def get_placements(self):
        return {pid: value.slot_name for pid,value in self.get_placement_details().items()}

    def get_placement_details(self):
        with closing(self.connect()) as c:
            return self._group_placements(c.execute(
                f'SELECT l.*,s.slot_name FROM ({LOCATION_SQL}) l JOIN slots s USING(slot_id) ORDER BY l.extra,s.slot_name').fetchall())

    def get_all_placement_items(self):
        with closing(self.connect()) as c:
            return [(r['product_id'],r['slot_name'],r['stock_qty'],r['assigned_at']) for r in c.execute(
                f'SELECT l.*,s.slot_name FROM ({LOCATION_SQL}) l JOIN slots s USING(slot_id) ORDER BY l.extra,s.slot_name')]

    def get_product_location(self, product_id):
        pid = normalise_sku(product_id)
        with closing(self.connect()) as c:
            row = c.execute("""SELECT p.*,s.slot_name,s.slot_number,s.row_number,s.shelf_id
                               FROM placements p JOIN slots s USING(slot_id)
                               WHERE p.product_id=?""", (pid,)).fetchone()
        if row is None:
            return None
        return ProductLocation(row['shelf_id'], row['row_number'],row['slot_number'],
                               Placement(', '.join(self.get_product_locations(pid)),row['stock_qty'],row['assigned_at']))

    def get_product_locations(self, product_id):
        with closing(self.connect()) as c:
            return [row[0] for row in c.execute(
                f'SELECT s.slot_name FROM ({LOCATION_SQL}) l JOIN slots s USING(slot_id) WHERE product_id=? ORDER BY extra,s.slot_name',
                (normalise_sku(product_id),))]

    def get_on_hand_products(self):
        with closing(self.connect()) as c:
            return {r['product_id']: OnHandProduct(r['product_id'],r['stock_qty'],r['queued_at'])
                    for r in c.execute('SELECT * FROM on_hand_queue ORDER BY queued_at,product_id')}

    def add_to_on_hand(self, quantities, queued_at):
        quantities = {normalise_sku(pid): qty for pid,qty in quantities.items()}
        if not queued_at:
            raise ValueError('The on-hand time must include a timezone.')
        queued_at = iso_timestamp(queued_at)
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            for pid, qty in quantities.items():
                if qty is not None:
                    validate_stock_quantity(qty)
                if c.execute('SELECT 1 FROM placements WHERE product_id=?', (pid,)).fetchone():
                    raise ValueError(f'Product {pid} is already assigned to a shelf.')
                c.execute("""INSERT INTO on_hand_queue(product_id,stock_qty,queued_at) VALUES (?,?,?)
                             ON CONFLICT(product_id) DO UPDATE SET stock_qty=excluded.stock_qty, queued_at=excluded.queued_at""",
                          (pid,qty,queued_at))
        return len(quantities)

    def get_slot_stock_modifications(self, slot_id):
        with closing(self.connect()) as c:
            return dict(c.execute(f"""SELECT m.product_id,m.modified_at FROM stock_modifications m
                                      WHERE product_id IN (SELECT product_id FROM ({LOCATION_SQL}) WHERE slot_id=?)""", (slot_id,)))

    @staticmethod
    def _record_stock_modification(connection, product_id, modified_at):
        if modified_at is not None:
            connection.execute("""INSERT INTO stock_modifications VALUES (?,?) ON CONFLICT(product_id)
                                  DO UPDATE SET modified_at=excluded.modified_at""", (product_id,iso_timestamp(modified_at)))

    def update_on_hand_stock(self, product_id, quantity, *, modified_at=None):
        validate_stock_quantity(quantity)
        pid = normalise_sku(product_id)
        with closing(self.connect()) as c,c:
            if c.execute('UPDATE on_hand_queue SET stock_qty=? WHERE product_id=?', (quantity,pid)).rowcount != 1:
                raise KeyError(f'Product {pid} is no longer in the on-hand queue.')
            self._record_stock_modification(c,pid,modified_at)

    def swap_slot_contents(self, first_slot_id, second_slot_id):
        if first_slot_id == second_slot_id:
            raise ValueError('Choose two different cells to switch.')
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            self._check_slots(c,first_slot_id,second_slot_id)
            counts = dict(c.execute(f'SELECT slot_id,COUNT(*) FROM ({LOCATION_SQL}) GROUP BY slot_id'))
            c.execute('UPDATE placements SET slot_id=CASE slot_id WHEN ? THEN ? ELSE ? END WHERE slot_id IN (?,?)',
                      (first_slot_id,second_slot_id,first_slot_id,first_slot_id,second_slot_id))
            self._move_exception_cells(c,{first_slot_id:second_slot_id,second_slot_id:first_slot_id})
        return counts.get(first_slot_id,0),counts.get(second_slot_id,0)

    @staticmethod
    def _check_slots(c, *slot_ids):
        if len(c.execute('SELECT slot_id FROM slots WHERE slot_id IN ('+','.join('?' for _ in slot_ids)+')',slot_ids).fetchall()) != len(set(slot_ids)):
            raise KeyError('One of the selected shelf cells no longer exists.')

    def combine_slot_contents(self, source_slot_id, target_slot_id, *, merge_duplicates=False):
        if source_slot_id == target_slot_id:
            raise ValueError('Choose two different cells to combine.')
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            self._check_slots(c,source_slot_id,target_slot_id)
            overlaps = [row[0] for row in c.execute(f"""SELECT product_id FROM ({LOCATION_SQL}) WHERE slot_id IN (?,?)
                                                       GROUP BY product_id HAVING COUNT(*)>1""",(source_slot_id,target_slot_id))]
            if overlaps and not merge_duplicates:
                raise ValueError(f'Product {overlaps[0]} is already in both cells. Both cells are unchanged.')
            count = c.execute(f'SELECT COUNT(*) FROM ({LOCATION_SQL}) WHERE slot_id=?',(source_slot_id,)).fetchone()[0]
            if overlaps:
                self._merge_cell_duplicates(c,overlaps,source_slot_id,target_slot_id)
            c.execute('UPDATE placements SET slot_id=? WHERE slot_id=?',(target_slot_id,source_slot_id))
            self._move_exception_cells(c,{source_slot_id:target_slot_id},merge_duplicates=merge_duplicates)
        return count

    def assign_on_hand_to_slot(self, slot_id, assigned_at, product_ids=None):
        if not assigned_at:
            raise ValueError('The assignment time must include a timezone.')
        assigned_at = iso_timestamp(assigned_at)
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            self._check_slots(c,slot_id)
            rows = {row['product_id']:row for row in c.execute('SELECT * FROM on_hand_queue')}
            ids = tuple(rows) if product_ids is None else tuple(dict.fromkeys(normalise_sku(pid) for pid in product_ids))
            for pid in ids:
                if pid not in rows:
                    raise KeyError(f'Product {pid} is no longer in the on-hand queue.')
                if c.execute('SELECT 1 FROM placements WHERE product_id=?',(pid,)).fetchone():
                    raise ValueError(f'Product {pid} is already assigned to a shelf.')
                qty = rows[pid]['stock_qty']
                c.execute('INSERT INTO placements(product_id,slot_id,stock_qty,assigned_at) VALUES (?,?,?,?)',
                          (pid,slot_id,qty if qty is not None else 999,assigned_at))
                c.execute('DELETE FROM on_hand_queue WHERE product_id=?',(pid,))
        return len(ids)

    def assign_catalog_direct_to_slot(self, slot_id, assigned_at, products, default_stock=999, *, quantities=None):
        products = self._normalise_records(products)
        if not assigned_at:
            raise ValueError('The assignment time must include a timezone.')
        assigned_at = iso_timestamp(assigned_at)
        validate_stock_quantity(default_stock)
        if quantities is not None:
            quantities = {normalise_sku(pid):qty for pid,qty in quantities.items()}
            if quantities.keys() != products.keys():
                raise ValueError('Enter stock for every selected product.')
            for qty in quantities.values():
                validate_stock_quantity(qty)
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            self._check_slots(c,slot_id)
            self._import_transfer_products(c,products)
            for pid in products:
                # Read before deleting: 0 is a known count; 999 and NULL are unknown.
                previous = [row[0] for row in c.execute('SELECT stock_qty FROM on_hand_queue WHERE product_id=? UNION ALL SELECT stock_qty FROM placements WHERE product_id=?',(pid,pid))]
                known = next((qty for qty in previous if qty not in (None,999)),default_stock)
                qty = quantities[pid] if quantities is not None else known
                old = c.execute('SELECT slot_id FROM placements WHERE product_id=?',(pid,)).fetchone()
                c.execute('DELETE FROM exception_placements WHERE product_id=? AND slot_id=?',(pid,slot_id))
                c.execute("""INSERT INTO placements(product_id,slot_id,stock_qty,assigned_at) VALUES (?,?,?,?)
                             ON CONFLICT(product_id) DO UPDATE SET slot_id=excluded.slot_id,
                             stock_qty=excluded.stock_qty,assigned_at=excluded.assigned_at""",(pid,slot_id,qty,assigned_at))
                c.execute('DELETE FROM on_hand_queue WHERE product_id=?',(pid,))
                if old and old['slot_id'] != slot_id:
                    self._move_product_staging(c,pid,old['slot_id'],slot_id)
        return len(products)

    def capture_shift_transfer(self, product_ids, slot_id):
        records = []
        with closing(self.connect()) as c:
            for pid in dict.fromkeys(normalise_sku(pid) for pid in product_ids):
                record = {'product_id':pid}
                for table in ('placements','exception_placements','on_hand_queue','hot_sellers','wait_to_update_csv'):
                    record[table] = [dict(row) for row in c.execute(f'SELECT * FROM {table} WHERE product_id=?',(pid,))]
                records.append(record)
        return {'slot_id':slot_id,'products':records}

    def revert_shift_transfer(self, transfer_data: dict[str,Any]):
        records = transfer_data.get('products',[])
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            for record in records:
                pid = record['product_id']
                current = c.execute('SELECT slot_id FROM placements WHERE product_id=?',(pid,)).fetchone()
                if current is None or current['slot_id'] != transfer_data['slot_id']:
                    raise ValueError(f'{pid} has moved since the Shift transfer. Nothing was reverted.')
                for table in ('exception_placements','placements','on_hand_queue','hot_sellers','wait_to_update_csv'):
                    c.execute(f'DELETE FROM {table} WHERE product_id=?',(pid,))
                    for row in record[table]:
                        c.execute(f'INSERT INTO {table} ('+', '.join(row)+') VALUES ('+', '.join('?' for _ in row)+')',tuple(row.values()))
        return len(records)

    def move_slot_to_on_hand(self, slot_id, queued_at, product_ids=None):
        if not queued_at:
            raise ValueError('The on-hand time must include a timezone.')
        queued_at = iso_timestamp(queued_at)
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            self._check_slots(c,slot_id)
            available = {row[0] for row in c.execute(f'SELECT product_id FROM ({LOCATION_SQL}) WHERE slot_id=?',(slot_id,))}
            ids = available if product_ids is None else {normalise_sku(pid) for pid in product_ids}
            if ids - available:
                raise KeyError(f'Product {sorted(ids-available)[0]} is no longer in that shelf address.')
            for pid in ids:
                self._remove_location(c,pid,slot_id,queued_at)
        return len(ids)

    def move_product_to_on_hand(self, product_id, queued_at):
        """Remove all locations of one SKU, retaining its one count atomically."""
        pid, queued_at = normalise_sku(product_id), iso_timestamp(queued_at)
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            rows = c.execute(f'SELECT slot_id FROM ({LOCATION_SQL}) WHERE product_id=? ORDER BY extra DESC', (pid,)).fetchall()
            for row in rows:
                self._remove_location(c,pid,row['slot_id'],queued_at)
        return len(rows)

    def _remove_location(self, c, pid, slot_id, queued_at):
        main = c.execute('SELECT * FROM placements WHERE product_id=?',(pid,)).fetchone()
        if main is None:
            raise KeyError(f'{pid} has no primary placement.')
        if main['slot_id'] == slot_id:
            replacement = c.execute('SELECT * FROM exception_placements WHERE product_id=? ORDER BY slot_id LIMIT 1',(pid,)).fetchone()
            if replacement:
                c.execute('UPDATE placements SET slot_id=?,assigned_at=? WHERE product_id=?',
                          (replacement['slot_id'],replacement['assigned_at'],pid))
                c.execute('DELETE FROM exception_placements WHERE product_id=? AND slot_id=?',(pid,replacement['slot_id']))
            else:
                c.execute('INSERT INTO on_hand_queue(product_id,stock_qty,queued_at) VALUES (?,?,?)',
                          (pid,main['stock_qty'],queued_at))
                c.execute('DELETE FROM placements WHERE product_id=?',(pid,))
        else:
            c.execute('DELETE FROM exception_placements WHERE product_id=? AND slot_id=?',(pid,slot_id))
        c.execute('DELETE FROM wait_to_update_csv WHERE product_id=? AND slot_id=?',(pid,slot_id))

    def update_placement_stock(self, product_id, quantity, *, expected_slot_id=None, modified_at=None):
        validate_stock_quantity(quantity)
        pid = normalise_sku(product_id)
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            if expected_slot_id is not None and not c.execute(
                    f'SELECT 1 FROM ({LOCATION_SQL}) WHERE product_id=? AND slot_id=?',(pid,expected_slot_id)).fetchone():
                raise KeyError(f'Product {pid} is no longer in that shelf address.')
            if c.execute('UPDATE placements SET stock_qty=? WHERE product_id=?',(quantity,pid)).rowcount != 1:
                raise KeyError(f'Product {pid} has no shelf placement.')
            self._record_stock_modification(c,pid,modified_at)

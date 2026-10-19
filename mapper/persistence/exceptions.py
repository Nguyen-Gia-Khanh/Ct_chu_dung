"""Extra product locations ("special exceptions") and their staged CSV/catalog follow-up."""

from __future__ import annotations

from contextlib import closing
from itertools import groupby
from pathlib import Path

from mapper.core.common import clean_product_name, iso_timestamp, normalize_sku
from mapper.features.csv_import import write_product_names
from .models import validate_stock_quantity
from .shared import IN_IDS, LOCATION_SQL, PRODUCT_NAME_SQL, find_product_locations, ids_param, remove_from_slot


class ExceptionOperations:
    def find_product_locations(self, product_id):
        with closing(self.connect()) as c:
            return find_product_locations(c, product_id)

    def get_multi_location_products(self):
        with closing(self.connect()) as c:
            rows = c.execute(f"""SELECT l.product_id, {PRODUCT_NAME_SQL} AS name, s.slot_name
                FROM ({LOCATION_SQL}) l JOIN catalog_products c USING(product_id) JOIN slots s USING(slot_id)
                WHERE l.product_id IN (SELECT product_id FROM ({LOCATION_SQL}) GROUP BY product_id HAVING COUNT(*) > 1)
                ORDER BY l.product_id, s.slot_name COLLATE NOCASE""").fetchall()
        return [(pid, group[0]['name'], tuple(row['slot_name'] for row in group))
                for pid, group in ((pid, list(group)) for pid, group in groupby(rows, key=lambda row: row['product_id']))]

    def assign_exception(self, product_id, slot_id, assigned_at=None, stock_qty=None, product_name=None):
        pid = normalize_sku(product_id)
        if not pid:
            raise ValueError('Product ID cannot be empty.')
        if stock_qty is not None:
            validate_stock_quantity(stock_qty)
        name = clean_product_name(product_name)
        if product_name and not name:
            raise ValueError('Use a real name, not an Excel error.')
        assigned_at = iso_timestamp(assigned_at)
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            slot = c.execute('SELECT slot_name FROM slots WHERE slot_id=?', (slot_id,)).fetchone()
            if slot is None:
                raise ValueError('The selected cell no longer exists.')
            catalog = c.execute('SELECT * FROM catalog_products WHERE product_id=?', (pid,)).fetchone()
            c.execute('INSERT INTO catalog_products(product_id,full_name) VALUES (?,?) ON CONFLICT DO NOTHING', (pid, name))
            changed = catalog and name and name != (catalog['full_name'] or catalog['brand_name'] or pid)
            if changed:
                c.execute('UPDATE catalog_products SET full_name=? WHERE product_id=?', (name, pid))
                c.execute('UPDATE wait_to_update_csv SET csv_updated=0,catalog_updated=0 WHERE product_id=?', (pid,))
            primary = c.execute('SELECT * FROM placements WHERE product_id=?', (pid,)).fetchone()
            if primary is None:
                hand = c.execute('SELECT stock_qty FROM on_hand_queue WHERE product_id=?', (pid,)).fetchone()
                qty = hand[0] if hand and hand[0] not in (None, 999) else stock_qty
                c.execute('INSERT INTO placements(product_id,slot_id,stock_qty,assigned_at) VALUES (?,?,?,?)',
                          (pid, slot_id, qty if qty is not None else 999, assigned_at))
                c.execute('DELETE FROM on_hand_queue WHERE product_id=?', (pid,))
            elif primary['slot_id'] != slot_id:
                c.execute('INSERT INTO exception_placements VALUES (?,?,?) ON CONFLICT DO NOTHING', (pid, slot_id, assigned_at))
            done = c.execute('SELECT MAX(csv_updated),MAX(catalog_updated) FROM wait_to_update_csv WHERE product_id=?', (pid,)).fetchone()
            c.execute("""INSERT INTO wait_to_update_csv(product_id,slot_id,slot_name,csv_updated,catalog_updated)
                         VALUES (?,?,?,?,?) ON CONFLICT(product_id,slot_name) DO UPDATE SET slot_id=excluded.slot_id""",
                      (pid, slot_id, slot[0], done[0] or 0, done[1] if done[1] is not None else int(catalog is not None and not changed)))
        return slot[0]

    def get_exception_staging(self, *, pending_csv_only=False):
        where = 'WHERE w.csv_updated = 0' if pending_csv_only else ''
        with closing(self.connect()) as c:
            return [dict(row) for row in c.execute(f"""SELECT w.*, {PRODUCT_NAME_SQL} AS product_name
                FROM wait_to_update_csv w JOIN catalog_products c USING(product_id) {where} ORDER BY w.id""")]

    def get_pending_csv_updates(self):
        return self.get_exception_staging(pending_csv_only=True)

    def get_staged_exception_summary(self):
        """One row per staged product: name, locations still staged, current saved locations, flags."""
        with closing(self.connect()) as c:
            rows = c.execute(f"""SELECT w.product_id, {PRODUCT_NAME_SQL} AS product_name,
                       group_concat(w.slot_name, ', ' ORDER BY w.id) AS staged_locations,
                       (SELECT group_concat(s.slot_name, ', ' ORDER BY l.extra, s.slot_name)
                        FROM ({LOCATION_SQL}) l JOIN slots s USING(slot_id) WHERE l.product_id = w.product_id) AS locations,
                       MIN(w.csv_updated) AS csv_updated, MIN(w.catalog_updated) AS catalog_updated,
                       MIN(w.created_at) AS created_at
                FROM wait_to_update_csv w JOIN catalog_products c USING(product_id)
                GROUP BY w.product_id ORDER BY MIN(w.id)""").fetchall()
        return [dict(row) for row in rows]

    def update_staged_exception_name(self, product_id, product_name):
        pid, name = normalize_sku(product_id), clean_product_name(product_name)
        if not name:
            raise ValueError('Enter a real full name, not an Excel error.')
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM wait_to_update_csv WHERE product_id=?', (pid,)).fetchone() is None:
                raise ValueError(f'{pid} is no longer in the staged exception list.')
            if c.execute('SELECT full_name FROM catalog_products WHERE product_id=?', (pid,)).fetchone()[0] == name:
                return
            c.execute('UPDATE catalog_products SET full_name=? WHERE product_id=?', (name, pid))
            c.execute('UPDATE wait_to_update_csv SET csv_updated=0,catalog_updated=0 WHERE product_id=?', (pid,))

    def add_staged_to_catalog(self, product_ids=None):
        where = 'catalog_updated = 0' + ('' if product_ids is None else f' AND product_id {IN_IDS}')
        params = () if product_ids is None else (ids_param({normalize_sku(pid) for pid in product_ids}),)
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            count = c.execute(f'SELECT COUNT(DISTINCT product_id) FROM wait_to_update_csv WHERE {where}', params).fetchone()[0]
            c.execute(f'UPDATE wait_to_update_csv SET catalog_updated = 1 WHERE {where}', params)
        return count

    def wipe_staged_exception(self, product_id):
        pid = normalize_sku(product_id)
        with closing(self.connect()) as c, c:
            if c.execute('SELECT 1 FROM wait_to_update_csv WHERE product_id=?', (pid,)).fetchone() is None:
                raise ValueError(f'{pid} is no longer in the staged exception list.')
            # Child tables reference catalog_products with ON DELETE CASCADE.
            c.execute('DELETE FROM catalog_products WHERE product_id=?', (pid,))

    def remove_exception_from_slot(self, product_id, slot_id):
        pid = normalize_sku(product_id)
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute(f'SELECT 1 FROM ({LOCATION_SQL}) WHERE product_id=? AND slot_id=?', (pid, slot_id)).fetchone() is None:
                raise ValueError(f'{pid} is no longer in this cell.')
            remove_from_slot(c, slot_id, [pid], iso_timestamp())

    def append_pending_to_csv(self, csv_path: str | Path, product_ids: list[str] | None = None) -> int:
        """Register each selected pending product in a CSV and keep its staged row."""
        selected = None if product_ids is None else {normalize_sku(pid) for pid in product_ids}
        names = {item['product_id']: item['product_name'] for item in self.get_pending_csv_updates()
                 if selected is None or item['product_id'] in selected}
        if not names:
            return 0
        write_product_names(csv_path, names)
        with closing(self.connect()) as c, c:
            c.execute(f'UPDATE wait_to_update_csv SET csv_updated = 1 WHERE product_id {IN_IDS}', (ids_param(names),))
        return len(names)

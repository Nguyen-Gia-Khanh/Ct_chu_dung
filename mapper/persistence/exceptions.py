from __future__ import annotations

import csv
import io
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import uuid4
from mapper.core.common import normalise_sku, normalize_search, clean_product_name, iso_timestamp
from .models import validate_stock_quantity


class ExceptionOperations:
    def _merge_cell_duplicates(self, connection, product_ids, source_slot_id, target_slot_id):
        # Duplicate locations collapse; the one product stock must never be summed.
        for pid in product_ids:
            primary = connection.execute('SELECT slot_id FROM placements WHERE product_id=?',(pid,)).fetchone()
            if primary['slot_id'] in (source_slot_id,target_slot_id):
                destination = connection.execute('SELECT assigned_at FROM exception_placements WHERE product_id=? AND slot_id=?',
                                                 (pid,target_slot_id)).fetchone()
                if primary['slot_id'] == source_slot_id and destination:
                    connection.execute('UPDATE placements SET slot_id=?,assigned_at=? WHERE product_id=?',
                                       (target_slot_id,destination[0],pid))
                else:
                    connection.execute('UPDATE placements SET slot_id=? WHERE product_id=?',(target_slot_id,pid))
                connection.execute('DELETE FROM exception_placements WHERE product_id=? AND slot_id IN (?,?)',
                                   (pid,source_slot_id,target_slot_id))
            else:
                connection.execute('DELETE FROM exception_placements WHERE product_id=? AND slot_id=?',(pid,source_slot_id))

    def _relocate_staging(self, c, destinations, product_id=None):
        marks = ','.join('?' for _ in destinations)
        where = f'slot_id IN ({marks})' + (' AND product_id=?' if product_id else '')
        params = tuple(destinations) + ((product_id,) if product_id else ())
        rows = c.execute(f'SELECT * FROM wait_to_update_csv WHERE {where}',params).fetchall()
        c.execute(f'DELETE FROM wait_to_update_csv WHERE {where}',params)
        for row in rows:
            target = destinations[row['slot_id']]
            name = c.execute('SELECT slot_name FROM slots WHERE slot_id=?',(target,)).fetchone()[0]
            c.execute("""INSERT INTO wait_to_update_csv(id,product_id,slot_id,slot_name,created_at,csv_updated,catalog_updated)
                         VALUES (?,?,?,?,?,?,?) ON CONFLICT(product_id,slot_name) DO UPDATE SET
                         csv_updated=MIN(wait_to_update_csv.csv_updated,excluded.csv_updated),
                         catalog_updated=MIN(wait_to_update_csv.catalog_updated,excluded.catalog_updated)""",
                      (row['id'],row['product_id'],target,name,row['created_at'],row['csv_updated'],row['catalog_updated']))

    def _move_product_staging(self,c,pid,source,target):
        self._relocate_staging(c,{source:target},pid)

    def _move_exception_cells(self, connection, destinations, *, merge_duplicates=False):
        marks = ','.join('?' for _ in destinations)
        rows = connection.execute(f'SELECT * FROM exception_placements WHERE slot_id IN ({marks})',tuple(destinations)).fetchall()
        connection.execute(f'DELETE FROM exception_placements WHERE slot_id IN ({marks})',tuple(destinations))
        for row in rows:
            connection.execute('INSERT INTO exception_placements VALUES (?,?,?) ON CONFLICT DO NOTHING',
                               (row['product_id'],destinations[row['slot_id']],row['assigned_at']))
        self._relocate_staging(connection,destinations)

    def find_product_locations(self, product_id):
        pid = normalise_sku(product_id)
        with closing(self.connect()) as c:
            row = c.execute('SELECT COALESCE(full_name,brand_name,product_id) FROM catalog_products WHERE product_id=?',(pid,)).fetchone()
            locations = c.execute("""SELECT s.slot_name FROM slots s JOIN (
                SELECT product_id,slot_id FROM placements UNION SELECT product_id,slot_id FROM exception_placements
                ) l USING(slot_id) WHERE l.product_id=? ORDER BY s.slot_name COLLATE NOCASE""",(pid,)).fetchall()
        return (row[0],tuple(r[0] for r in locations)) if row else None

    def get_multi_location_products(self):
        with closing(self.connect()) as c:
            rows = c.execute("""SELECT l.product_id, COALESCE(c.full_name,c.brand_name,l.product_id) AS name,s.slot_name
                FROM (SELECT product_id,slot_id FROM placements UNION SELECT product_id,slot_id FROM exception_placements) l
                JOIN catalog_products c USING(product_id) JOIN slots s USING(slot_id)
                ORDER BY l.product_id,s.slot_name COLLATE NOCASE""").fetchall()
        grouped = {}
        for row in rows:
            grouped.setdefault(row['product_id'],(row['name'],[]))[1].append(row['slot_name'])
        return [(pid,name,tuple(locations)) for pid,(name,locations) in grouped.items() if len(locations)>1]

    def assign_exception(self, product_id, slot_id, assigned_at=None, stock_qty=None, product_name=None):
        pid = normalise_sku(product_id)
        if not pid:
            raise ValueError('Product ID cannot be empty.')
        if stock_qty is not None:
            validate_stock_quantity(stock_qty)
        name = clean_product_name(product_name)
        if product_name and not name:
            raise ValueError('Use a real name, not an Excel error.')
        assigned_at = iso_timestamp(assigned_at)
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            slot = c.execute('SELECT slot_name FROM slots WHERE slot_id=?',(slot_id,)).fetchone()
            if slot is None:
                raise ValueError('The selected cell no longer exists.')
            catalog = c.execute('SELECT * FROM catalog_products WHERE product_id=?',(pid,)).fetchone()
            origin = self._remember_queue_origin(c,pid)
            c.execute('INSERT INTO catalog_products(product_id,full_name) VALUES (?,?) ON CONFLICT DO NOTHING',(pid,name))
            changed = catalog and name and name != (catalog['full_name'] or catalog['brand_name'] or pid)
            if changed:
                c.execute('UPDATE catalog_products SET full_name=? WHERE product_id=?',(name,pid))
                c.execute('UPDATE wait_to_update_csv SET csv_updated=0,catalog_updated=0 WHERE product_id=?',(pid,))
            self._save_queue_origin(c,pid,origin)
            primary = c.execute('SELECT * FROM placements WHERE product_id=?',(pid,)).fetchone()
            if primary is None:
                hand = c.execute('SELECT stock_qty FROM on_hand_queue WHERE product_id=?',(pid,)).fetchone()
                qty = hand[0] if hand and hand[0] not in (None,999) else stock_qty
                c.execute('INSERT INTO placements(product_id,slot_id,stock_qty,assigned_at) VALUES (?,?,?,?)',
                          (pid,slot_id,qty if qty is not None else 999,assigned_at))
                c.execute('DELETE FROM on_hand_queue WHERE product_id=?',(pid,))
            elif primary['slot_id'] != slot_id:
                c.execute('INSERT INTO exception_placements VALUES (?,?,?) ON CONFLICT DO NOTHING',(pid,slot_id,assigned_at))
            done = c.execute('SELECT MAX(csv_updated),MAX(catalog_updated) FROM wait_to_update_csv WHERE product_id=?',(pid,)).fetchone()
            c.execute("""INSERT INTO wait_to_update_csv(product_id,slot_id,slot_name,csv_updated,catalog_updated)
                         VALUES (?,?,?,?,?) ON CONFLICT(product_id,slot_name) DO UPDATE SET slot_id=excluded.slot_id""",
                      (pid,slot_id,slot[0],done[0] or 0,done[1] if done[1] is not None else int(catalog is not None and not changed)))
        return slot[0]

    def get_exception_staging(self):
        with closing(self.connect()) as c:
            return [dict(row) for row in c.execute("""SELECT w.*,COALESCE(c.full_name,c.brand_name,w.product_id) AS product_name
                FROM wait_to_update_csv w JOIN catalog_products c USING(product_id) ORDER BY w.id""")]

    def get_pending_csv_updates(self):
        return [item for item in self.get_exception_staging() if not item['csv_updated']]

    def update_staged_exception_name(self, product_id, product_name):
        pid, name = normalise_sku(product_id), clean_product_name(product_name)
        if not name:
            raise ValueError('Enter a real full name, not an Excel error.')
        with closing(self.connect()) as c,c:
            row = c.execute('SELECT 1 FROM wait_to_update_csv WHERE product_id=?',(pid,)).fetchone()
            if row is None:
                raise ValueError(f'{pid} is no longer in the staged exception list.')
            current = c.execute('SELECT full_name FROM catalog_products WHERE product_id=?',(pid,)).fetchone()[0]
            if current == name:
                return
            c.execute('UPDATE catalog_products SET full_name=? WHERE product_id=?',(name,pid))
            c.execute('UPDATE wait_to_update_csv SET csv_updated=0,catalog_updated=0 WHERE product_id=?',(pid,))

    def add_staged_to_catalog(self, product_ids=None):
        ids = None if product_ids is None else {normalise_sku(pid) for pid in product_ids}
        with closing(self.connect()) as c,c:
            selected = {row[0] for row in c.execute('SELECT product_id FROM wait_to_update_csv WHERE catalog_updated=0')}
            if ids is not None:
                selected &= ids
            c.executemany('UPDATE wait_to_update_csv SET catalog_updated=1 WHERE product_id=?',((pid,) for pid in selected))
        return len(selected)

    def wipe_staged_exception(self, product_id):
        pid = normalise_sku(product_id)
        with closing(self.connect()) as c,c:
            if c.execute('SELECT 1 FROM wait_to_update_csv WHERE product_id=?',(pid,)).fetchone() is None:
                raise ValueError(f'{pid} is no longer in the staged exception list.')
            # Child tables reference catalog_products with ON DELETE CASCADE.
            c.execute('DELETE FROM catalog_products WHERE product_id=?',(pid,))

    def remove_exception_from_slot(self, product_id, slot_id):
        pid = normalise_sku(product_id)
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            exists = c.execute("""SELECT 1 FROM placements WHERE product_id=? AND slot_id=? UNION ALL
                                 SELECT 1 FROM exception_placements WHERE product_id=? AND slot_id=?""",(pid,slot_id,pid,slot_id)).fetchone()
            if exists is None:
                raise ValueError(f'{pid} is no longer in this cell.')
            self._remove_location(c,pid,slot_id,iso_timestamp())

    def clear_pending_csv_updates(self, ids=None):
        with closing(self.connect()) as c,c:
            if ids is not None:
                if not ids:
                    return 0
                return c.execute('DELETE FROM wait_to_update_csv WHERE id IN ('+','.join('?' for _ in ids)+')',ids).rowcount
            return c.execute('DELETE FROM wait_to_update_csv').rowcount

    def append_pending_to_csv(
        self, csv_path: str | Path, product_ids: list[str] | None = None
    ) -> int:
        """Register each selected pending product in a CSV and keep its staged row."""
        selected = {normalise_sku(pid) for pid in product_ids} if product_ids is not None else None
        pending: dict[str, dict[str, Any]] = {}
        for item in self.get_pending_csv_updates():
            if selected is None or item["product_id"] in selected:
                pending[item["product_id"]] = item
        if not pending:
            return 0

        path = Path(csv_path)
        raw = path.read_bytes() if path.exists() else b""
        encoding = "utf-8"
        text_content = ""
        if raw:
            for candidate in ("utf-8-sig", "utf-8", "cp1258", "cp1252"):
                try:
                    text_content = raw.decode(candidate)
                    encoding = candidate
                    break
                except UnicodeDecodeError:
                    continue

        first_line = text_content.splitlines()[0] if text_content.splitlines() else ""
        delimiter = max((";", ",", "\t", "|"), key=first_line.count) if first_line else ";"
        existing_rows = list(csv.reader(io.StringIO(text_content), delimiter=delimiter))
        header_cols = existing_rows[0] if existing_rows else [
            "product_id", "full_name", "brand_name"
        ]
        if len(header_cols) < 2:
            raise ValueError("The CSV needs separate product ID and product name columns.")

        normalized = [
            "".join(character for character in normalize_search(column) if character.isalnum())
            for column in header_cols
        ]
        id_idx = next(
            (index for index, value in enumerate(normalized)
             if value in {"productid", "productcode", "mahang", "masanpham", "sku", "code"}),
            0,
        )
        name_idx = next(
            (index for index, value in enumerate(normalized)
             if value in {"fullname", "productname", "tenhang", "tensanpham", "name", "title"}),
            1,
        )
        if id_idx == name_idx:
            raise ValueError("Could not identify different product ID and name columns in the CSV.")
        rows_to_write = existing_rows if existing_rows else [header_cols]
        existing_ids: set[str] = set()
        for row in rows_to_write[1:]:
            if len(row) <= id_idx:
                continue
            product_id = normalise_sku(row[id_idx])
            row[id_idx] = product_id
            if product_id in pending:
                row.extend([""] * (name_idx + 1 - len(row)))
                row[name_idx] = pending[product_id]["product_name"]
                existing_ids.add(product_id)
        for product_id, item in pending.items():
            if product_id in existing_ids:
                continue
            row = [""] * len(header_cols)
            row[id_idx] = product_id
            row[name_idx] = item["product_name"]
            rows_to_write.append(row)

        output = io.StringIO(newline="")
        newline = "\r\n" if b"\r\n" in raw else "\n"
        writer = csv.writer(output, delimiter=delimiter, lineterminator=newline)
        writer.writerows(rows_to_write)
        payload = output.getvalue().encode(encoding)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(payload)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

        with closing(self.connect()) as connection, connection:
            connection.executemany(
                "UPDATE wait_to_update_csv SET csv_updated = 1 WHERE product_id = ?",
                [(product_id,) for product_id in pending],
            )
        return len(pending)

"""SQL fragments and connection-level steps shared by several operation groups.

Every helper takes an open connection inside the caller's transaction, so the
operation mixins never depend on each other's private methods.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from mapper.core.common import clean_product_name, iso_timestamp, normalize_sku

# Every location reads its quantity from the one primary placement.
LOCATION_SQL = """SELECT p.product_id, p.slot_id, p.stock_qty, p.assigned_at, 0 AS extra
                  FROM placements p
                  UNION ALL
                  SELECT e.product_id, e.slot_id, p.stock_qty, e.assigned_at, 1 AS extra
                  FROM exception_placements e JOIN placements p USING(product_id)"""

# Display name of a catalog row aliased as c.
PRODUCT_NAME_SQL = "COALESCE(c.full_name, c.brand_name, c.product_id)"

# `x IN_IDS` with ids_param(...) replaces hand-built placeholder lists of any length.
IN_IDS = "IN (SELECT value FROM json_each(?))"


def ids_param(ids: Iterable[object]) -> str:
    return json.dumps(list(ids))


def tuples(connection: sqlite3.Connection, sql: str, params: tuple = ()) -> list[tuple]:
    """Plain tuples for list-shaped reads; skips building a sqlite3.Row per row."""
    cursor = connection.cursor()
    cursor.row_factory = None
    return cursor.execute(sql, params).fetchall()


def normalize_records(records: dict) -> dict[str, tuple[str | None, str | None]]:
    """Import rows keyed by canonical SKU; a bare name becomes (name, '')."""
    normalized = {}
    for raw, value in records.items():
        pid = normalize_sku(raw)
        if not pid:
            raise ValueError('Product ID cannot be empty.')
        names = value if isinstance(value, tuple) else (value, '')
        cleaned = tuple(clean_product_name(name) for name in names)
        if pid in normalized and normalized[pid] != cleaned:
            raise ValueError(f'Conflicting imported rows for {pid}.')
        normalized[pid] = cleaned
    return normalized


def check_slots(connection: sqlite3.Connection, *slot_ids: int) -> None:
    unique = set(slot_ids)
    found = connection.execute(f'SELECT COUNT(*) FROM slots WHERE slot_id {IN_IDS}', (ids_param(unique),)).fetchone()[0]
    if found != len(unique):
        raise KeyError('One of the selected shelf cells no longer exists.')


def slot_names(connection: sqlite3.Connection, slot_ids: Iterable[int]) -> dict[int, str]:
    return dict(connection.execute(f'SELECT slot_id, slot_name FROM slots WHERE slot_id {IN_IDS}', (ids_param(slot_ids),)))


def location_names(connection: sqlite3.Connection, product_id: str) -> list[str]:
    """Primary location first, then extra locations by name."""
    return [row[0] for row in connection.execute(
        f'SELECT s.slot_name FROM ({LOCATION_SQL}) l JOIN slots s USING(slot_id) '
        'WHERE l.product_id=? ORDER BY l.extra, s.slot_name', (product_id,))]


def find_product_locations(connection: sqlite3.Connection, product_id: str) -> tuple[str, tuple[str, ...]] | None:
    """(display name, locations sorted by name) for a catalog SKU, or None when unknown."""
    pid = normalize_sku(product_id)
    row = connection.execute(f'SELECT {PRODUCT_NAME_SQL} FROM catalog_products c WHERE product_id=?', (pid,)).fetchone()
    if row is None:
        return None
    locations = connection.execute(
        f'SELECT s.slot_name FROM ({LOCATION_SQL}) l JOIN slots s USING(slot_id) '
        'WHERE l.product_id=? ORDER BY s.slot_name COLLATE NOCASE', (pid,)).fetchall()
    return row[0], tuple(dict.fromkeys(r[0] for r in locations))


def record_stock_modification(connection: sqlite3.Connection, product_id: str, modified_at: str | None) -> None:
    if modified_at is not None:
        connection.execute("""INSERT INTO stock_modifications VALUES (?,?) ON CONFLICT(product_id)
                              DO UPDATE SET modified_at=excluded.modified_at""", (product_id, iso_timestamp(modified_at)))


def relocate_staging(connection: sqlite3.Connection, destinations: dict[int, int],
                     product_ids: Iterable[str] | None = None) -> None:
    """Move staged CSV rows with their cells; flags merge so 'not done yet' wins."""
    where = f'slot_id {IN_IDS}' + (f' AND product_id {IN_IDS}' if product_ids is not None else '')
    params = (ids_param(destinations),) + ((ids_param(product_ids),) if product_ids is not None else ())
    rows = connection.execute(f'SELECT * FROM wait_to_update_csv WHERE {where}', params).fetchall()
    if not rows:
        return
    connection.execute(f'DELETE FROM wait_to_update_csv WHERE {where}', params)
    names = slot_names(connection, set(destinations.values()))
    connection.executemany(
        """INSERT INTO wait_to_update_csv(id,product_id,slot_id,slot_name,created_at,csv_updated,catalog_updated)
           VALUES (?,?,?,?,?,?,?) ON CONFLICT(product_id,slot_name) DO UPDATE SET
           csv_updated=MIN(wait_to_update_csv.csv_updated,excluded.csv_updated),
           catalog_updated=MIN(wait_to_update_csv.catalog_updated,excluded.catalog_updated)""",
        [(row['id'], row['product_id'], destinations[row['slot_id']], names[destinations[row['slot_id']]],
          row['created_at'], row['csv_updated'], row['catalog_updated']) for row in rows])


def move_exception_cells(connection: sqlite3.Connection, destinations: dict[int, int]) -> None:
    """Move extra locations (and their staged rows) from each source cell to its destination."""
    sources = ids_param(destinations)
    rows = connection.execute(f'SELECT * FROM exception_placements WHERE slot_id {IN_IDS}', (sources,)).fetchall()
    connection.execute(f'DELETE FROM exception_placements WHERE slot_id {IN_IDS}', (sources,))
    connection.executemany('INSERT INTO exception_placements VALUES (?,?,?) ON CONFLICT DO NOTHING',
                           [(row['product_id'], destinations[row['slot_id']], row['assigned_at']) for row in rows])
    relocate_staging(connection, destinations)


def merge_cell_duplicates(connection: sqlite3.Connection, product_ids: list[str], source_slot_id: int,
                          target_slot_id: int) -> None:
    """Collapse products found in both cells; the one product stock is never summed."""
    rows = connection.execute(
        f"""SELECT p.product_id, p.slot_id, e.assigned_at AS target_assigned_at
            FROM placements p LEFT JOIN exception_placements e
              ON e.product_id = p.product_id AND e.slot_id = ?
            WHERE p.product_id {IN_IDS}""", (target_slot_id, ids_param(product_ids))).fetchall()
    in_pair = [row for row in rows if row['slot_id'] in (source_slot_id, target_slot_id)]
    takes_time = {row['product_id'] for row in in_pair
                  if row['slot_id'] == source_slot_id and row['target_assigned_at'] is not None}
    # A primary in the source takes the target's extra-location time when it had one.
    connection.executemany('UPDATE placements SET slot_id=?, assigned_at=? WHERE product_id=?', [
        (target_slot_id, row['target_assigned_at'], row['product_id'])
        for row in in_pair if row['product_id'] in takes_time])
    connection.executemany('UPDATE placements SET slot_id=? WHERE product_id=?', [
        (target_slot_id, row['product_id']) for row in in_pair if row['product_id'] not in takes_time])
    connection.executemany('DELETE FROM exception_placements WHERE product_id=? AND slot_id IN (?,?)',
                           [(row['product_id'], source_slot_id, target_slot_id) for row in in_pair])
    # Primary elsewhere: the target keeps its extra location, the source copy goes.
    connection.executemany('DELETE FROM exception_placements WHERE product_id=? AND slot_id=?',
                           [(row['product_id'], source_slot_id) for row in rows
                            if row['slot_id'] not in (source_slot_id, target_slot_id)])


def remove_from_slot(connection: sqlite3.Connection, slot_id: int, product_ids: Iterable[str], queued_at: str) -> None:
    """Remove products from one cell. A primary location is replaced by the product's first
    extra location, or the product returns to the on-hand queue with its stock."""
    ids = ids_param(product_ids)
    connection.execute(f'DELETE FROM exception_placements WHERE slot_id=? AND product_id {IN_IDS}', (slot_id, ids))
    # Promote the lowest extra location of primaries leaving this cell.
    connection.execute(f"""
        UPDATE placements SET (slot_id, assigned_at) = (
            SELECT e.slot_id, e.assigned_at FROM exception_placements e
            WHERE e.product_id = placements.product_id ORDER BY e.slot_id LIMIT 1)
        WHERE slot_id=? AND product_id {IN_IDS}
          AND EXISTS (SELECT 1 FROM exception_placements e WHERE e.product_id = placements.product_id)""",
        (slot_id, ids))
    connection.execute(f"""
        DELETE FROM exception_placements WHERE product_id {IN_IDS}
          AND (product_id, slot_id) IN (SELECT product_id, slot_id FROM placements)""", (ids,))
    connection.execute(f"""INSERT INTO on_hand_queue(product_id, stock_qty, queued_at)
                           SELECT product_id, stock_qty, ? FROM placements WHERE slot_id=? AND product_id {IN_IDS}""",
                       (queued_at, slot_id, ids))
    connection.execute(f'DELETE FROM placements WHERE slot_id=? AND product_id {IN_IDS}', (slot_id, ids))
    connection.execute(f'DELETE FROM wait_to_update_csv WHERE slot_id=? AND product_id {IN_IDS}', (slot_id, ids))

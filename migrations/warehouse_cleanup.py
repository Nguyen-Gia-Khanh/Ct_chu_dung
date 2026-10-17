"""Review by default; --apply backs up and atomically upgrades the warehouse.

Run with the repository .venv: python -m migrations.warehouse_cleanup --help
Do not open the desktop app until this command finishes.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import closing
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from mapper.core.common import clean_product_name, iso_timestamp, normalise_sku
from mapper.persistence.schema import SCHEMA_VERSION, create_schema

VERSION = SCHEMA_VERSION
COLLISION = {'H06430-K56-N12', 'H0643-0K5-6N12'}


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + ('?mode=ro' if readonly else '?mode=rw'), uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    return connection


def snapshot(connection: sqlite3.Connection) -> dict:
    tables = {}
    for row in connection.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        name = row['name']
        tables[name] = {
            'count': connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0],
            'columns': [dict(item) for item in connection.execute(f'PRAGMA table_xinfo("{name}")')],
            'sql': row['sql'],
        }
    return {
        'tables': tables,
        'integrity_check': [row[0] for row in connection.execute('PRAGMA integrity_check')],
        'foreign_key_check': [list(row) for row in connection.execute('PRAGMA foreign_key_check')],
    }


def read_rows(connection: sqlite3.Connection) -> dict[str, list[dict]]:
    return {name: [dict(row) for row in connection.execute(f'SELECT * FROM "{name}"')]
            for name in snapshot(connection)['tables']}


def catalog_only_ids(origins) -> set[str]:
    """Legacy products also held temporary copies that were never hot sellers."""
    return {normalise_sku(row['product_id']) for row in origins
            if json.loads(row['snapshot'])['was_in_products'] is False}


def flatten_layout(data: dict) -> dict:
    """Keep cell IDs and empty rows while removing the row-identity table."""
    rows_by_shelf, cells_by_row = defaultdict(list), defaultdict(list)
    for row in data['shelf_rows']:
        rows_by_shelf[row['shelf_id']].append(row)
    for cell in data['slots']:
        cells_by_row[cell['row_id']].append(cell)
    shelves, slots, processed_rows = [], [], 0
    for shelf in data['shelves']:
        rows = sorted(rows_by_shelf[shelf['shelf_id']],key=lambda row:row['row_number'])
        processed_rows += len(rows)
        if [row['row_number'] for row in rows] != list(range(1,len(rows)+1)):
            raise ValueError(f"Shelf {shelf['shelf_id']} has nonconsecutive rows; review its layout first.")
        shelves.append({**shelf,'row_count':len(rows)})
        for row in rows:
            cells = sorted(cells_by_row[row['row_id']],key=lambda cell:cell['slot_number'])
            if [cell['slot_number'] for cell in cells] != list(range(1,row['slot_count']+1)):
                raise ValueError(f"Shelf row {row['row_id']} has inconsistent cells; review before migrating.")
            slots.extend({'slot_id':cell['slot_id'],'shelf_id':shelf['shelf_id'],
                          'row_number':row['row_number'],'slot_number':cell['slot_number'],
                          'slot_name':cell['slot_name']} for cell in cells)
    if len(slots) != len(data['slots']) or processed_rows != len(data['shelf_rows']):
        raise ValueError('Orphan shelf rows or cells must be reviewed before migrating.')
    return {'shelves':shelves,'slots':slots}


def review(connection: sqlite3.Connection, honda_csv: Path | None = None) -> dict:
    data = read_rows(connection)
    result = {'before': snapshot(connection)}
    if 'products' not in data:
        return result
    catalog = {normalise_sku(row['product_id']): row for row in data['catalog_products']}
    products = {normalise_sku(row['product_id']): row for row in data['products']}
    slots = {row['slot_id']: row['slot_name'] for row in data['slots']}
    locations = defaultdict(list)
    for table in ('placements', 'exception_placements'):
        for row in data[table]:
            locations[normalise_sku(row['product_id'])].append({
                'table': table, 'slot_id': row['slot_id'], 'slot_name': slots[row['slot_id']],
                'stock_qty': row['stock_qty'],
            })
    result['missing_catalog'] = {}
    for table in ('products', 'placements', 'exception_placements'):
        result['missing_catalog'][table] = [{
            'original_product_id': row['product_id'], 'product_id': normalise_sku(row['product_id']),
            'product_name': products.get(normalise_sku(row['product_id']), {}).get('product_name'),
            'shortened_name': products.get(normalise_sku(row['product_id']), {}).get('shortened_name'),
            'slots': locations[normalise_sku(row['product_id'])],
        } for row in data[table] if normalise_sku(row['product_id']) not in catalog]
    result['collisions'] = {}
    for table in ('catalog_products', 'products'):
        grouped = defaultdict(list)
        for row in data[table]:
            grouped[normalise_sku(row['product_id'])].append(row)
        result['collisions'][table] = {key: rows for key, rows in grouped.items() if len(rows) > 1}
    result['exception_products'] = [{
        'product_id': pid, 'locations': rows,
        'distinct_locations': len({row['slot_id'] for row in rows}),
        'real_counts': sorted({row['stock_qty'] for row in rows if row['stock_qty'] not in (None, 999)}),
    } for pid, rows in locations.items() if any(row['table'] == 'exception_placements' for row in rows)]
    hand = {normalise_sku(row['product_id']): row for row in data['on_hand_queue']}
    result['returned_queue_conflicts'] = [
        {'returned': row, 'on_hand': hand[normalise_sku(row['product_id'])]}
        for row in data['returned_queue_products'] if normalise_sku(row['product_id']) in hand
    ]
    result['staging_flags'] = [list(row) for row in connection.execute(
        'SELECT csv_updated, catalog_updated, COUNT(*) FROM wait_to_update_csv GROUP BY 1, 2')]
    result['test_rows_proposed_for_deletion_only'] = [row for row in data['products'] if row['product_id'] in ('1111', '111111')]
    if honda_csv:
        with honda_csv.open(encoding='utf-8-sig', newline='') as stream:
            source = list(csv.DictReader(stream, delimiter=';'))
        honda = defaultdict(set)
        for row in source:
            honda[normalise_sku(row['product_id'])].add(clean_product_name(row['product_name']))
        result['honda_csv'] = {'path': str(honda_csv.resolve()),
            'sha256': hashlib.sha256(honda_csv.read_bytes()).hexdigest(),
            'mismatches': [row for row in data['catalog_products']
                if normalise_sku(row['product_id']) in honda
                and clean_product_name(row['product_name']) not in honda[normalise_sku(row['product_id'])]],
            'not_in_csv': [row['product_id'] for row in data['catalog_products'] if normalise_sku(row['product_id']) not in honda]}
    return result


def backup(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = path.parent / 'backups' / f'{path.stem}-before-cleanup-{stamp}.db'
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path, readonly=True)) as source, closing(sqlite3.connect(target)) as destination:
        destination.execute('PRAGMA foreign_keys = ON')
        source.backup(destination)
        if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Backup integrity check failed.')
    return target


def migrate(connection: sqlite3.Connection, *, keep_sku: str | None = None,
            register_missing: bool = False) -> dict:
    """All SKU changes, table rebuilds, and checks share ONE transaction."""
    if connection.in_transaction:
        raise RuntimeError('Migration must own its transaction.')
    connection.execute('PRAGMA foreign_keys = OFF')
    if connection.execute('PRAGMA foreign_keys').fetchone()[0] != 0:
        raise RuntimeError('Cannot disable foreign keys before the transaction.')
    try:
        connection.execute('BEGIN IMMEDIATE')
        tables = snapshot(connection)['tables']
        if 'schema_migrations' in tables and connection.execute(
                'SELECT 1 FROM schema_migrations WHERE version=?', (VERSION,)).fetchone():
            state = snapshot(connection)
            if state['integrity_check'] != ['ok'] or state['foreign_key_check']:
                raise RuntimeError('Already migrated database fails SQLite checks.')
            connection.commit()
            return {'status': 'already_applied', 'after': state}
        if 'schema_migrations' in tables and connection.execute(
                'SELECT 1 FROM schema_migrations WHERE version=1').fetchone():
            # Versions 1-3 share the old layout and origin tables.
            before = snapshot(connection)
            custom = connection.execute("SELECT name FROM sqlite_master WHERE type IN ('view','trigger')").fetchall()
            if custom:
                raise RuntimeError(f'Custom views/triggers need review: {[row[0] for row in custom]}')
            layout = flatten_layout(read_rows(connection))
            slot_sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name='slots'").fetchone()
            removed = connection.execute("DELETE FROM sqlite_sequence WHERE name='exception_placements'").rowcount
            excluded = catalog_only_ids(connection.execute('SELECT * FROM queue_origins'))
            memberships = [dict(row) for row in connection.execute('SELECT * FROM hot_sellers ORDER BY product_id')
                           if row['product_id'] in excluded]
            connection.executemany('DELETE FROM hot_sellers WHERE product_id=?',
                                   [(row['product_id'],) for row in memberships])
            connection.execute('ALTER TABLE shelves ADD COLUMN row_count INTEGER NOT NULL DEFAULT 0 CHECK (row_count >= 0)')
            connection.executemany('UPDATE shelves SET row_count=? WHERE shelf_id=?',
                                   [(row['row_count'],row['shelf_id']) for row in layout['shelves']])
            connection.execute('DROP TABLE slots')
            connection.execute('DROP TABLE shelf_rows')
            connection.execute('DROP TABLE queue_origins')
            create_schema(connection)
            connection.executemany('INSERT INTO slots(slot_id,shelf_id,row_number,slot_number,slot_name) VALUES (?,?,?,?,?)',
                                   [tuple(row.values()) for row in layout['slots']])
            if slot_sequence:
                connection.execute("INSERT INTO sqlite_sequence(name,seq) SELECT 'slots',? WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name='slots')",(slot_sequence[0],))
                connection.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name='slots'",(slot_sequence[0],))
            connection.executemany('INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)', [(2,),(3,),(VERSION,)])
            after = snapshot(connection)
            if after['integrity_check'] != ['ok'] or after['foreign_key_check']:
                raise sqlite3.IntegrityError('Schema simplification failed SQLite checks.')
            connection.commit()
            return {'status': 'applied_simplification', 'before': before, 'after': after,
                    'excluded_catalog_only_hot_sellers': memberships,
                    'dropped_tables': ['shelf_rows','queue_origins'],
                    'retired_sequence_rows_removed': removed}
        data = read_rows(connection)
        expected = {'products', 'catalog_products', 'placements', 'exception_placements',
                    'on_hand_queue', 'returned_queue_products', 'queue_origins', 'stock_modifications',
                    'wait_to_update_csv', 'shelves', 'shelf_rows', 'slots'}
        if set(data) != expected:
            raise RuntimeError(f'Unexpected legacy tables: {set(data) ^ expected}. Review before migrating.')
        custom = connection.execute("SELECT name FROM sqlite_master WHERE type IN ('view','trigger')").fetchall()
        if custom:
            raise RuntimeError(f'Custom views/triggers need review: {[row[0] for row in custom]}')
        before = snapshot(connection)
        sequences = dict(connection.execute('SELECT name, seq FROM sqlite_sequence'))
        original_ids = {row['product_id'] for table in ('products', 'catalog_products') for row in data[table]}
        aliases = defaultdict(set)
        for pid in original_ids:
            aliases[normalise_sku(pid)].add(pid)
        for key, ids in aliases.items():
            if len(ids) > 1 and (ids != COLLISION or keep_sku not in ids):
                raise ValueError(f'Choose the surviving original SKU before merging {key}: {sorted(ids)}')
        def keyed(table):
            result = {}
            for row in sorted(data[table], key=lambda row: row['product_id'] == keep_sku):
                result[normalise_sku(row['product_id'])] = row
            return result
        old_catalog, old_products = keyed('catalog_products'), keyed('products')
        all_ids = {normalise_sku(row['product_id']) for rows in data.values() for row in rows if 'product_id' in row}
        missing = sorted(all_ids - old_catalog.keys())
        if missing and not register_missing:
            raise ValueError(f'{len(missing)} missing catalog SKUs require explicit --register-missing approval.')
        catalog = []
        for pid in sorted(all_ids):
            original, product = old_catalog.get(pid), old_products.get(pid)
            staged = next((row for row in data['wait_to_update_csv'] if normalise_sku(row['product_id']) == pid), {})
            full = clean_product_name(product['product_name']) if product else clean_product_name(staged.get('product_name'))
            catalog.append({'product_id': pid, 'full_name': full,
                'brand_name': clean_product_name(original['product_name']) if original else None,
                'imported_at': iso_timestamp((original or product or staged).get('imported_at') or staged.get('created_at'), legacy_utc=True)})
        excluded = catalog_only_ids(data['queue_origins'])
        migrated = {
            'catalog_products': catalog,
            'hot_sellers': [{'product_id': pid, 'imported_at': iso_timestamp(row['imported_at'], legacy_utc=True)}
                            for pid, row in old_products.items() if pid not in excluded],
        }
        promoted, main, extra = [], [], []
        locations = defaultdict(list)
        for table in ('placements', 'exception_placements'):
            for row in data[table]:
                locations[normalise_sku(row['product_id'])].append((table, row))
        for pid, rows in locations.items():
            real = {row['stock_qty'] for _, row in rows if row['stock_qty'] not in (None, 999)}
            if len(real) > 1:
                raise ValueError(f'Conflicting known counts for {pid}: {sorted(real)}. Review before merging.')
            stock = next(iter(real)) if real else 999
            primary = next((row for table, row in rows if table == 'placements' and row['product_id'] == keep_sku), None)
            primary = primary or next((row for table, row in rows if table == 'placements'), rows[0][1])
            if not any(table == 'placements' for table, _ in rows):
                promoted.append(pid)
            main.append({'product_id': pid, 'slot_id': primary['slot_id'], 'stock_qty': stock,
                'assigned_at': iso_timestamp(primary['assigned_at'], legacy_utc=True) if primary['assigned_at'] else None,
                'committed_at': iso_timestamp(primary['committed_at'], legacy_utc=True)})
            seen = {primary['slot_id']}
            for _, row in rows:
                if row['slot_id'] not in seen:
                    extra.append({'product_id': pid, 'slot_id': row['slot_id'],
                        'assigned_at': iso_timestamp(row['assigned_at'], legacy_utc=True) if row['assigned_at'] else None})
                    seen.add(row['slot_id'])
        migrated['placements'], migrated['exception_placements'] = main, extra
        hand = keyed('on_hand_queue')
        conflicts = [row for row in data['returned_queue_products'] if normalise_sku(row['product_id']) in hand]
        if conflicts:
            raise ValueError(f'Existing on-hand stock will not be overwritten: {conflicts}')
        for row in data['returned_queue_products']:
            hand[normalise_sku(row['product_id'])] = {'stock_qty': row['stock_qty'], 'queued_at': row['returned_at']}
        if hand.keys() & locations.keys():
            raise ValueError(f'Products are both on-hand and placed: {sorted(hand.keys() & locations.keys())}')
        migrated['on_hand_queue'] = [{'product_id': pid, 'stock_qty': row['stock_qty'],
            'queued_at': iso_timestamp(row['queued_at'], legacy_utc=True)} for pid, row in hand.items()]
        for table in ('stock_modifications', 'wait_to_update_csv', 'shelves', 'shelf_rows', 'slots'):
            rows = []
            for original in data[table]:
                row = {key: value for key, value in original.items() if key != 'product_name'}
                if 'product_id' in row:
                    row['product_id'] = normalise_sku(row['product_id'])
                for column in row:
                    if column.endswith('_at') and row[column]:
                        row[column] = iso_timestamp(row[column], legacy_utc=True)
                rows.append(row)
            migrated[table] = rows
        migrated.update(flatten_layout(migrated))
        del migrated['shelf_rows']
        # Do not rename referenced legacy tables: their FK targets must stay stable.
        for table in expected:
            connection.execute(f'DROP TABLE "{table}"')
        create_schema(connection)
        for table, rows in migrated.items():
            if rows:
                columns = ', '.join(rows[0])
                marks = ', '.join('?' for _ in rows[0])
                connection.executemany(f'INSERT INTO {table} ({columns}) VALUES ({marks})',
                                       [tuple(row.values()) for row in rows])
        for table, value in sequences.items():
            if table in ('shelves', 'slots', 'wait_to_update_csv'):
                cursor = connection.execute('UPDATE sqlite_sequence SET seq=MAX(seq, ?) WHERE name=?', (value, table))
                if cursor.rowcount == 0:
                    connection.execute('INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)', (table,value))
        connection.executemany('INSERT INTO schema_migrations(version) VALUES (?)', [(1,), (2,), (3,), (VERSION,)])
        after = snapshot(connection)
        if after['integrity_check'] != ['ok'] or after['foreign_key_check']:
            raise sqlite3.IntegrityError(f'Migration checks failed: {after}')
        connection.commit()
        return {'status': 'applied', 'before': before, 'after': after,
                'registered_missing_catalog': missing, 'promoted_to_primary': promoted,
                'excluded_catalog_only_hot_sellers': sorted(excluded & old_products.keys()),
                'dropped_tables': ['returned_queue_products','shelf_rows','queue_origins'],
                'returned_queue_moved': len(data['returned_queue_products']), 'returned_queue_conflicts': []}
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.execute('PRAGMA foreign_keys = ON')
        if connection.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
            raise RuntimeError('Failed to restore foreign key enforcement.')


def write_review(report: dict, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if 'missing_catalog' in report or not (directory / 'review.json').exists():
        (directory / 'review.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for table, rows in report.get('missing_catalog', {}).items():
        with (directory / f'missing_catalog_{table}.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(('original_product_id', 'product_id', 'name', 'previous_shortened_name', 'slots'))
            for row in rows:
                writer.writerow((row['original_product_id'], row['product_id'], row['product_name'], row['shortened_name'],
                                 ', '.join(item['slot_name'] for item in row['slots'])))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('data/warehouse_locations.db'))
    parser.add_argument('--honda-csv', type=Path, default=Path('full_catalogue.csv'))
    parser.add_argument('--output', type=Path, default=Path('data/schema-review'))
    parser.add_argument('--apply', action='store_true', help='Close the app first. Back up and apply the migration.')
    parser.add_argument('--keep-sku', choices=sorted(COLLISION))
    parser.add_argument('--register-missing', action='store_true', help='Approved registration using existing names; unknown brand names stay NULL.')
    args = parser.parse_args()
    with closing(connect(args.database, readonly=True)) as connection:
        report = review(connection, args.honda_csv if args.honda_csv.exists() else None)
    write_review(report, args.output)
    print('Review:', args.output.resolve())
    if args.apply:
        if 'missing_catalog' in report and (not report.get('honda_csv')
                or report['honda_csv']['mismatches'] or report['honda_csv']['not_in_csv']):
            raise ValueError('Provide a Honda CSV matching the existing brand names. Review the exported differences first.')
        target = backup(args.database)
        print('Backup:', target)
        with closing(connect(args.database)) as connection:
            result = migrate(connection, keep_sku=args.keep_sku, register_missing=args.register_missing)
        result['backup'] = str(target.resolve())
        result['backup_sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
        filename = {'already_applied': 'last-verification.json',
                    'applied_simplification': 'simplification.json'}.get(result['status'], 'migration.json')
        (args.output / filename).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(result['status'], 'integrity_check:', result['after']['integrity_check'],
              'foreign_key_check:', result['after']['foreign_key_check'])


if __name__ == '__main__':
    main()

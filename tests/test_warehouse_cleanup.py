"""Migration rollback and inventory behavior on isolated, real-schema fixtures."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tkinter as tk
from unittest.mock import patch

from barcode_web.lookup import WarehouseLookup
from mapper.core.common import iso_timestamp, normalize_sku, vietnam_time
from mapper.persistence.database import WarehouseDatabase, LayoutConflictError
from migrations.warehouse_cleanup import connect, migrate, read_rows, snapshot
from tests.support import WorkspaceTestCase
from ui.desktop.app import WarehouseMapperApp
from utils.labels.app import LabelDatabase

FIRST = '2026-09-24T14:32:28+07:00'
UTC = '2026-09-24T07:32:28+00:00'


class WarehouseCleanupTests(WorkspaceTestCase):
    def legacy(self):
        path = self.folder / 'legacy.db'
        with closing(sqlite3.connect(path)) as c, c:
            c.execute('PRAGMA foreign_keys=ON')
            c.executescript((Path(__file__).parent / 'fixtures/warehouse_before_cleanup.sql').read_text())
            ids = ['P-1', 'N-1', 'O-1', 'U-1', 'R-1', 'H06430-K56-N12', 'H0643-0K5-6N12']
            for pid in ids:
                c.execute('INSERT INTO products(product_id,product_name,shortened_name) VALUES (?,?,?)',
                          (pid, '#N/A' if pid == 'U-1' else f'Full {pid}', '#N/A'))
                if pid not in ('O-1','U-1'):
                    c.execute('INSERT INTO catalog_products(product_id,product_name) VALUES (?,?)',(pid,f'Honda {pid}'))
            c.execute("INSERT INTO shelves(shelf_id,floor,side,shelf_code) VALUES (1,'1','1','A')")
            c.execute('INSERT INTO shelf_rows(row_id,shelf_id,row_number,slot_count) VALUES (1,1,1,3)')
            for slot in (1,2,3):
                c.execute('INSERT INTO slots(slot_id,row_id,slot_number,slot_name) VALUES (?,1,?,?)',(slot,slot,f'L1-1A1-{slot}'))
            for pid,qty in [('P-1',3),('N-1',0)]:
                c.execute('INSERT INTO placements(product_id,slot_id,stock_qty,assigned_at) VALUES (?,1,?,?)',(pid,qty,FIRST))
            for pid,slot,qty in [('P-1',2,None),('N-1',2,999),('O-1',1,4),('U-1',3,None)]:
                c.execute('INSERT INTO exception_placements(product_id,slot_id,stock_qty,assigned_at) VALUES (?,?,?,?)',(pid,slot,qty,FIRST))
            c.execute('INSERT INTO returned_queue_products VALUES (?,?,?)',('R-1',7,FIRST))
            c.execute("INSERT INTO wait_to_update_csv(product_id,product_name,slot_id,slot_name) VALUES ('O-1','Full O-1',1,'L1-1A1-1')")
            c.execute("INSERT INTO queue_origins VALUES ('O-1', '{\"was_in_products\": false}')")
            c.execute("INSERT INTO queue_origins VALUES ('P-1', '{\"was_in_products\": true}')")
        return path

    def apply(self, path):
        with closing(connect(path)) as c:
            result = migrate(c, keep_sku='H06430-K56-N12', register_missing=True)
            self.assertEqual(c.execute('PRAGMA foreign_keys').fetchone()[0],1)
        return result

    def previous_schema(self, version=3):
        path=self.folder/'v3.db'
        with closing(sqlite3.connect(path)) as c,c:
            c.execute('PRAGMA foreign_keys=ON')
            c.executescript((Path(__file__).parent/'fixtures/warehouse_v3.sql').read_text())
            c.executemany('INSERT INTO schema_migrations(version) VALUES (?)',[(number,) for number in range(1,version+1)])
            c.execute("INSERT INTO catalog_products(product_id,full_name) VALUES ('P1','Hot seller'),('O1','Waiting for CSV'),('HAND','On hand')")
            c.execute("INSERT INTO hot_sellers(product_id) VALUES ('P1')")
            if version<3:
                c.execute("INSERT INTO hot_sellers(product_id) VALUES ('O1')")
            c.execute("INSERT INTO queue_origins VALUES ('O1','{\"was_in_products\":false}'),('P1','{\"was_in_products\":true}')")
            c.execute("INSERT INTO shelves(shelf_id,floor,side,shelf_code) VALUES (1,'1','1','A')")
            c.execute('INSERT INTO shelf_rows(row_id,shelf_id,row_number,slot_count) VALUES (1,1,1,2),(2,1,2,0),(3,1,3,1),(4,1,4,0)')
            c.execute("INSERT INTO slots(slot_id,row_id,slot_number,slot_name) VALUES (10,1,1,'L1-1A1-1'),(11,1,2,'L1-1A1-2'),(20,3,1,'L1-1A3-1')")
            c.execute("INSERT INTO placements(product_id,slot_id,stock_qty,assigned_at) VALUES ('P1',10,7,?),('O1',20,4,?)",(UTC,UTC))
            c.execute("INSERT INTO exception_placements VALUES ('P1',20,?)",(UTC,))
            c.execute("INSERT INTO on_hand_queue VALUES ('HAND',0,?)",(UTC,))
            c.execute("INSERT INTO wait_to_update_csv(product_id,slot_id,slot_name) VALUES ('O1',20,'L1-1A3-1')")
            c.execute("UPDATE sqlite_sequence SET seq=900 WHERE name='slots'")
        return path

    def test_migration_is_atomic_repeatable_and_preserves_names_counts_locations(self):
        path = self.legacy()
        result = self.apply(path)
        self.assertEqual(result['after']['integrity_check'],['ok'])
        self.assertEqual(result['after']['foreign_key_check'],[])
        self.assertEqual(result['registered_missing_catalog'],['O1','U1'])
        self.assertEqual(len(result['promoted_to_primary']),2)
        db = WarehouseDatabase(path)
        self.assertEqual(db.get_placement_details()['P1'].stock_qty,3)
        self.assertEqual(db.get_placement_details()['N1'].stock_qty,0)
        self.assertEqual(db.get_placement_details()['O1'].stock_qty,4)
        self.assertEqual(db.get_placement_details()['U1'].stock_qty,999)
        self.assertEqual(db.get_on_hand_products()['R1'].stock_qty,7)
        self.assertEqual(db.get_on_hand_products()['R1'].queued_at,UTC)
        self.assertNotIn('O1',dict(db.get_products()))
        self.assertIn('P1',dict(db.get_products()))
        with closing(db.connect()) as c:
            names = dict(c.execute('SELECT product_id,full_name FROM catalog_products'))
            self.assertIsNone(names['U1'])
            self.assertEqual(names['H06430K56N12'],'Full H06430-K56-N12')
            self.assertEqual([r[1] for r in c.execute('PRAGMA table_info(exception_placements)')],['product_id','slot_id','assigned_at'])
            first = snapshot(c)
        self.assertEqual(self.apply(path)['status'],'already_applied')
        with closing(db.connect()) as c:
            self.assertEqual(snapshot(c),first)

    def test_collision_and_missing_catalog_require_explicit_choices(self):
        path = self.legacy()
        with closing(connect(path)) as c:
            before = snapshot(c)
            for options in ({}, {'keep_sku':'H06430-K56-N12'}):
                with self.assertRaises(ValueError):
                    migrate(c,**options)
                self.assertEqual(snapshot(c),before)
                self.assertEqual(c.execute('PRAGMA foreign_keys').fetchone()[0],1)

    def test_retired_sequence_cleanup_is_versioned_and_repeatable(self):
        path = self.previous_schema(1)
        with closing(connect(path)) as c,c:
            self.assertIsNone(c.execute("SELECT 1 FROM sqlite_sequence WHERE name='exception_placements'").fetchone())
            c.execute("INSERT INTO sqlite_sequence(name,seq) VALUES ('exception_placements',900)")
        with closing(connect(path)) as c:
            result=migrate(c)
            self.assertEqual(result['status'],'applied_simplification')
            self.assertEqual(result['retired_sequence_rows_removed'],1)
            self.assertEqual(migrate(c)['status'],'already_applied')
            self.assertEqual(c.execute('PRAGMA foreign_keys').fetchone()[0],1)

    def test_version_2_upgrade_removes_only_placeholder_membership_and_is_repeatable(self):
        path = self.previous_schema(2)
        with closing(connect(path)) as c:
            before = read_rows(c)
            result = migrate(c)
            self.assertEqual(result['status'],'applied_simplification')
            self.assertEqual([row['product_id'] for row in result['excluded_catalog_only_hot_sellers']],['O1'])
            after = read_rows(c)
            self.assertEqual(after['hot_sellers'],[row for row in before['hot_sellers'] if row['product_id']!='O1'])
            for table in before.keys()-{'hot_sellers','schema_migrations','slots','shelves','shelf_rows','queue_origins'}:
                self.assertEqual(after[table],before[table],table)
            self.assertEqual(migrate(c)['status'],'already_applied')
            self.assertEqual(read_rows(c),after)
            self.assertEqual(c.execute('PRAGMA foreign_keys').fetchone()[0],1)

    def test_version_3_simplification_preserves_layout_inventory_and_cell_high_water_mark(self):
        path=self.previous_schema()
        with closing(connect(path)) as c:
            before=read_rows(c)
            result=migrate(c)
            after=read_rows(c)
            self.assertEqual(result['dropped_tables'],['shelf_rows','queue_origins'])
            self.assertNotIn('shelf_rows',after)
            self.assertNotIn('queue_origins',after)
            for table in before.keys()-{'shelves','slots','shelf_rows','queue_origins','schema_migrations'}:
                self.assertEqual(after[table],before[table],table)
            self.assertEqual([(row['slot_id'],row['slot_name']) for row in after['slots']],
                             [(row['slot_id'],row['slot_name']) for row in before['slots']])
            self.assertEqual(migrate(c)['status'],'already_applied')
        db=WarehouseDatabase(path)
        self.assertEqual(db.get_shelf(1),('1','1','A',[2,0,1,0]))
        self.assertEqual(LabelDatabase(path).read_shelves([1])[0].rows,((1,2),(2,0),(3,1),(4,0)))
        self.assertEqual(WarehouseLookup(path).find('P1')['locations'],['L1-1A1-1','L1-1A3-1'])
        db.save_shelf('1','A',[2,0,1,0,1],shelf_id=1)
        self.assertGreater(db.get_slot_address('1','1','A',5,1).slot_id,900)
        db.save_shelf('1','A',[2,0,1],shelf_id=1)
        self.assertEqual(WarehouseDatabase(path).get_shelf(1)[3],[2,0,1])

    def test_inconsistent_layout_migration_rolls_back_without_dropping_tables(self):
        path=self.previous_schema()
        with closing(connect(path)) as c,c:
            c.execute('UPDATE shelf_rows SET slot_count=9 WHERE row_id=1')
        with closing(connect(path)) as c:
            before=read_rows(c)
            with self.assertRaisesRegex(ValueError,'inconsistent cells'):
                migrate(c)
            self.assertEqual(read_rows(c),before)
            self.assertEqual(c.execute('PRAGMA foreign_keys').fetchone()[0],1)

    def test_returned_overlap_and_disagreeing_counts_never_overwrite(self):
        for kind in ('queue','count'):
            path = self.legacy()
            with closing(connect(path)) as c,c:
                if kind == 'queue':
                    c.execute('INSERT INTO on_hand_queue VALUES (?,?,?)',('R-1',17,FIRST))
                else:
                    c.execute("UPDATE exception_placements SET stock_qty=6 WHERE product_id='P-1'")
            with closing(connect(path)) as c:
                before = snapshot(c)
                with self.assertRaises(ValueError):
                    migrate(c,keep_sku='H06430-K56-N12',register_missing=True)
                self.assertEqual(snapshot(c),before)
            path.unlink()

    def test_collision_moves_both_primary_locations_onto_survivor(self):
        path = self.legacy()
        with closing(connect(path)) as c,c:
            for pid,slot in [('H06430-K56-N12',2),('H0643-0K5-6N12',3)]:
                c.execute('INSERT INTO placements(product_id,slot_id,stock_qty,assigned_at) VALUES (?,?,2,?)',(pid,slot,FIRST))
        self.apply(path)
        db=WarehouseDatabase(path)
        self.assertEqual(db.get_product_locations('H06430-K56-N12'),['L1-1A1-2','L1-1A1-3'])
        self.assertEqual(db.get_placement_details()['H06430K56N12'].stock_qty,2)

    def fresh(self):
        db = WarehouseDatabase(self.folder/'new.db')
        db.import_products({'06410-kfl-850':('Tên Việt','Honda name'),'ZERO':('Zero','')})
        db.save_shelf('1','A',[3])
        return db

    def test_shared_stock_and_primary_promotion_across_screens_scanner_and_labels(self):
        db=self.fresh()
        db.assign_exception('06410-kfl-850',1,FIRST,8)
        db.assign_exception('06410KFL850',2,FIRST,99)
        self.assertEqual([row[2].stock_qty for row in db.get_shelf_contents(1)],[8,8])
        db.update_placement_stock('06410-kfl-850',11,expected_slot_id=2,modified_at=FIRST)
        self.assertEqual([row[2].stock_qty for row in db.get_shelf_contents(1)],[11,11])
        lookup=WarehouseLookup(db.path)
        cells=lookup.find('06410-kfl-850',include_cell_contents=True)['cells']
        self.assertEqual([cell['products'][0]['stock_qty'] for cell in cells],[11,11])
        self.assertEqual([len(cell.products) for cell in LabelDatabase(db.path).read_shelves([1])[0].cells],[1,1,0])
        db.remove_exception_from_slot('06410-kfl-850',1)
        self.assertEqual(db.get_product_locations('06410KFL850'),['L1-1A1-2'])
        self.assertEqual(db.get_placement_details()['06410KFL850'].stock_qty,11)
        db.remove_exception_from_slot('06410KFL850',2)
        self.assertEqual(WarehouseDatabase(db.path).get_on_hand_products()['06410KFL850'].stock_qty,11)

    def test_shift_retains_known_zero_and_unknown_falls_back_and_reverts_exactly(self):
        db=self.fresh()
        db.add_to_on_hand({'06410-kfl-850':12,'ZERO':0},FIRST)
        before=db.capture_shift_transfer(['06410KFL850','ZERO'],1)
        db.assign_catalog_direct_to_slot(1,FIRST,{'06410-kfl-850':('Tên Việt','Honda name'),'ZERO':('Zero','')})
        self.assertEqual([db.get_placement_details()[pid].stock_qty for pid in ('06410KFL850','ZERO')],[12,0])
        db.revert_shift_transfer(before)
        self.assertEqual(db.get_on_hand_products()['ZERO'].stock_qty,0)
        self.assertEqual(db.get_on_hand_products()['06410KFL850'].stock_qty,12)
        db.assign_catalog_direct_to_slot(1,FIRST,{'ZERO':('Zero','')})
        db.assign_catalog_direct_to_slot(2,FIRST,{'ZERO':('Zero','')})
        self.assertEqual(db.get_placement_details()['ZERO'].stock_qty,0)
        db.import_catalog_products({'NEW':('Honda','')})
        db.assign_catalog_direct_to_slot(3,FIRST,{'NEW':('Honda','')})
        self.assertEqual(db.get_placement_details()['NEW'].stock_qty,999)

    def test_exception_and_catalog_assignment_do_not_create_hot_seller_membership(self):
        db=self.fresh()
        original=dict(db.get_products())
        db.import_catalog_products({'CAT':('Honda catalog part','')})
        db.assign_catalog_direct_to_slot(1,FIRST,{'CAT':('Honda catalog part','')})
        db.assign_exception('CAT',2,FIRST)
        db.assign_exception('UNREGISTERED',3,FIRST,4,'Waiting for CSV')
        db.assign_exception('ZERO',1,FIRST,2)
        db.assign_exception('ZERO',2,FIRST)
        self.assertEqual(dict(db.get_products()),original)
        self.assertEqual(db.get_product_locations('CAT'),['L1-1A1-1','L1-1A1-2'])
        staged=next(row for row in db.get_exception_staging() if row['product_id']=='UNREGISTERED')
        self.assertEqual((staged['csv_updated'],staged['catalog_updated']),(0,0))
        self.assertEqual(dict(WarehouseDatabase(db.path).get_products()),original)
        db.import_products({'UNREGISTERED':('Waiting for CSV','')})
        self.assertIn('UNREGISTERED',dict(db.get_products()))

    def test_catalog_only_on_hand_keeps_name_and_stock_after_reopening_desktop(self):
        db=self.fresh()
        db.import_catalog_products({'CAT':('Honda catalog part','')})
        db.assign_catalog_direct_to_slot(1,FIRST,{'CAT':('Honda catalog part','')},quantities={'CAT':5})
        db.move_slot_to_on_hand(1,FIRST,['CAT'])
        root=tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app=WarehouseMapperApp(root,db.path)
        self.assertNotIn('CAT',app.products)
        self.assertEqual(app.assignments.on_hand_tree.set('hand::CAT','product_name'),'Honda catalog part')
        self.assertEqual(app.on_hand_products['CAT'].stock_qty,5)
        app.database.assign_on_hand_to_slot(2,FIRST,['CAT'])
        app.reconcile_inventory_products(['CAT'])
        self.assertNotIn('CAT',app.products)
        self.assertEqual(app.database.get_product_locations('CAT'),['L1-1A1-2'])

    def test_empty_rows_rename_resize_and_exception_occupancy_on_fresh_schema(self):
        db=self.fresh()
        db.save_shelf('1','A',[2,0,1,0],shelf_id=1)
        first=db.get_slot_address('1','1','A',1,1)
        extra=db.get_slot_address('1','1','A',3,1)
        db.assign_exception('ZERO',first.slot_id,FIRST,5)
        db.assign_exception('ZERO',extra.slot_id,FIRST)
        with self.assertRaises(LayoutConflictError):
            db.save_shelf('1','A',[2],shelf_id=1)
        self.assertEqual(db.get_shelf(1)[3],[2,0,1,0])
        db.save_shelf('1','B',[2,0,1,0],shelf_id=1)
        self.assertEqual(db.get_slot_address('1','1','B',1,1).slot_id,first.slot_id)
        self.assertEqual(db.get_product_locations('ZERO'),['L1-1B1-1','L1-1B3-1'])
        self.assertEqual(LabelDatabase(db.path).read_shelves([1])[0].rows,((1,2),(2,0),(3,1),(4,0)))
        with self.assertRaises(ValueError):
            db.save_shelf('1','B',[2,-1],shelf_id=1)

    def test_cell_combine_does_not_add_shared_stock_or_lose_registration_flags(self):
        db=self.fresh()
        db.assign_exception('06410KFL850',1,FIRST,8)
        db.assign_exception('06410KFL850',2,FIRST)
        with self.assertRaises(ValueError):
            db.combine_slot_contents(1,2)
        db.combine_slot_contents(1,2,merge_duplicates=True)
        self.assertEqual(db.get_product_locations('06410KFL850'),['L1-1A1-2'])
        self.assertEqual(db.get_placement_details()['06410KFL850'].stock_qty,8)
        self.assertEqual(len(db.get_exception_staging()),1)
        db.swap_slot_contents(2,3)
        self.assertEqual(db.get_exception_staging()[0]['slot_name'],'L1-1A1-3')

    def test_database_constraints_and_normalization_and_timestamp_defaults(self):
        db=self.fresh()
        self.assertEqual(normalize_sku(' 06410-kfl-850 '),'06410KFL850')
        self.assertEqual(iso_timestamp(FIRST),UTC)
        self.assertEqual(vietnam_time(UTC),FIRST.replace('T',' '))
        with closing(db.connect()) as c:
            for pid,name in [('bad-code','Name'),('lower','Name'),('SPACE CODE','Name'),('ERR','#N/A')]:
                with self.assertRaises(sqlite3.IntegrityError):
                    c.execute('INSERT INTO catalog_products(product_id,full_name) VALUES (?,?)',(pid,name))
                c.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute('INSERT INTO exception_placements VALUES (?,?,?)',('ABSENT',1,UTC))
            c.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute('INSERT INTO exception_placements VALUES (?,?,?)',('ZERO',999,UTC))
            c.rollback()
            c.execute('INSERT INTO exception_placements VALUES (?,?,?)',('ZERO',1,UTC))
            with self.assertRaises(sqlite3.IntegrityError):
                c.commit()
            c.rollback()
            self.assertTrue(c.execute('SELECT imported_at FROM hot_sellers LIMIT 1').fetchone()[0].endswith('+00:00'))
            self.assertEqual(c.execute('PRAGMA foreign_keys').fetchone()[0],1)
            self.assertEqual(migrate(c)['status'],'already_applied')

    def test_desktop_search_csv_shift_and_vietnam_time(self):
        db=self.fresh()
        db.add_to_on_hand({'06410KFL850':12},FIRST)
        root=tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app=WarehouseMapperApp(root,db.path)
        # Hidden tabs load on their first visit.
        app.refresh_if_stale(app.primal_view)
        app.refresh_if_stale(app.exceptions_view)
        for query in ('06410-kfl-850','06410KFL850','tên việt','Honda name'):
            app.assignments.search_var.set(query)
            app.refresh_product_lists()
            self.assertEqual(app.assignments.catalog_tree.get_children(),('catalog::06410KFL850',))
            app.primal_view.search_var.set(query)
            app.primal_view.refresh_results(navigate=False)
            self.assertEqual(app.primal_view.catalog_tree.get_children(),('catalog::06410KFL850',))
            app.exceptions_view.catalog_search_var.set(query)
            app.exceptions_view._filter_catalog_tree()
            self.assertEqual(app.exceptions_view.catalog_tree.get_children(),('06410KFL850',))
        app.selected_address=db.get_slot_by_id(1)
        app.assignments.catalog_tree.selection_set('catalog::06410KFL850')
        with patch('ui.desktop.catalog_actions.messagebox.showerror',side_effect=AssertionError):
            app.assign_catalog_selection_to_address(to_shelf=True)
        self.assertEqual(db.get_placement_details()['06410KFL850'].stock_qty,12)
        app.refresh_address_contents()
        self.assertTrue(app.assignments.contents_tree.set('saved::06410KFL850','assigned_at').endswith('+07:00'))

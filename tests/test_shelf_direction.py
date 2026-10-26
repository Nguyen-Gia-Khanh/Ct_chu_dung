"""Shelf ID direction, designer persistence, and repeat-safe operational conversion."""
from contextlib import closing
import sqlite3
import tkinter as tk
from unittest.mock import patch

from mapper.persistence.database import WarehouseDatabase, LayoutConflictError
from barcode_web.lookup import WarehouseLookup
from utils.labels.app import LabelDatabase
from mapper.services.shelf_grid import build_grid, load_grid
from migrations.shelf_direction import migrate, preserved_data
from tests.support import WorkspaceTestCase
from ui.desktop.app import WarehouseMapperApp


class ShelfDirectionTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.folder / "warehouse.db"
        self.db = WarehouseDatabase(self.path)
        self.sid = self.db.save_shelf("1", "A", [3, 2], side="2")

    def test_side_never_selects_direction(self):
        for side in ("1", "2", "4", "left"):
            for reverse, expected in ((False, [1, 2, 3]), (True, [3, 2, 1])):
                with self.subTest(side=side, reverse=reverse):
                    grid = build_grid("1", side, "A", [3, 0, 1], revert_location_id=reverse)
                    self.assertEqual([c.cell for c in grid.rows[-1]], expected)
                    self.assertEqual([c.row for c in grid.rows[0]], [3])
                    self.assertEqual(grid.layout, (3, 0, 1))

    def populate(self):
        for pid, cell, qty in (("LEFT", 1, 7), ("MIDDLE", 2, 4), ("RIGHT", 3, 9)):
            self.db.assign_exception(pid, self.db.get_slot_in_shelf(self.sid, 1, cell).slot_id,
                                     "2026-10-01T08:00:00+00:00", qty, pid)
        self.db.assign_exception("LEFT", self.db.get_slot_in_shelf(self.sid, 2, 1).slot_id,
                                 "2026-10-02T08:00:00+00:00")

    def positions(self):
        grid, contents = load_grid(self.db, self.sid)
        return {(cell.row, position): (self.db.get_slot_by_name(cell.slot_name).slot_id,
                    tuple(sorted(pid for pid, _, p in contents if p.slot_name == cell.slot_name)))
                for row in grid.rows for position, cell in enumerate(row, 1)}

    def test_toggle_renames_ids_but_keeps_products_and_exceptions_in_place(self):
        self.populate()
        positions = self.positions()
        left_id = self.db.get_slot_in_shelf(self.sid, 1, 1).slot_id
        with closing(self.db.connect()) as c:
            before = preserved_data(c)
        for reverse in (True, False, True):
            self.db.save_shelf("1", "A", [3, 2], side="2", shelf_id=self.sid, revert_location_id=reverse)
            self.assertEqual(self.positions(), positions)
            self.assertEqual(self.db.get_slot_by_id(left_id).slot_number, 3 if reverse else 1)
            self.assertEqual(self.db.get_product_locations("LEFT"),
                             ["L1-2A1-3", "L1-2A2-2"] if reverse else ["L1-2A1-1", "L1-2A2-1"])
            summary = next(row for row in self.db.get_staged_exception_summary() if row['product_id'] == 'LEFT')
            self.assertEqual(set(summary['staged_locations'].split(', ')), set(self.db.get_product_locations('LEFT')))
            self.assertEqual(set(summary['locations'].split(', ')), set(self.db.get_product_locations('LEFT')))
            self.assertEqual(WarehouseLookup(self.path).find('LEFT')['locations'], self.db.get_product_locations('LEFT'))
            shelf = LabelDatabase(self.path).read_shelves([self.sid])[0]
            self.assertEqual(shelf.revert_location_id, reverse)
            self.assertEqual(next(c for c in shelf.cells if c.slot_id == left_id).slot_number, 3 if reverse else 1)
            with closing(self.db.connect()) as c:
                after = preserved_data(c)
                self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertEqual(c.execute('SELECT count(*) FROM wait_to_update_csv w JOIN slots s USING(slot_id) WHERE w.slot_name != s.slot_name').fetchone()[0], 0)
            for table in before.keys() - {"shelves", "slots", "wait_to_update_csv"}:
                self.assertEqual(after[table], before[table], table)
            # Only the copied name changes in exception staging; flags/times/IDs stay intact.
            self.assertEqual([row[:3] + row[4:] for row in after['wait_to_update_csv']],
                             [row[:3] + row[4:] for row in before['wait_to_update_csv']])
        self.db.save_shelf("1", "A", [3, 2], side="2", shelf_id=self.sid)
        self.assertEqual(self.positions(), positions)
        self.assertTrue(WarehouseDatabase(self.path).get_shelf_revert_location_id(self.sid))
        self.assertFalse(self.db.get_shelf_revert_location_id(self.db.save_shelf("1", "B", [2], side="4")))

    def test_reversed_resize_preserves_positions_and_blocks_occupied_right_edge(self):
        self.populate()
        before = self.positions()
        self.db.save_shelf('1', 'A', [3, 2], side='2', shelf_id=self.sid, revert_location_id=True)
        self.db.save_shelf('1', 'A', [4, 2], side='2', shelf_id=self.sid)
        for key, value in before.items():
            self.assertEqual(self.positions()[key], value)
        self.assertEqual(self.db.get_product_locations('LEFT'), ['L1-2A1-4', 'L1-2A2-2'])
        self.db.save_shelf('1', 'A', [3, 2], side='2', shelf_id=self.sid)
        with closing(self.db.connect()) as c:
            snapshot = preserved_data(c)
        with self.assertRaisesRegex(LayoutConflictError, 'still contains committed products'):
            self.db.save_shelf('1', 'A', [2, 2], side='2', shelf_id=self.sid, revert_location_id=False)
        with closing(self.db.connect()) as c:
            self.assertEqual(preserved_data(c), snapshot)
        self.assertTrue(self.db.get_shelf_revert_location_id(self.sid))
        self.assertEqual(self.positions(), before)

    def test_exception_name_conflict_rolls_back_whole_commit(self):
        self.populate()
        # A historical, detached staging record must not be silently merged or deleted.
        with closing(self.db.connect()) as c, c:
            c.execute("INSERT INTO wait_to_update_csv(product_id,slot_name) VALUES ('LEFT','L1-2A1-3')")
        with closing(self.db.connect()) as c:
            before = preserved_data(c)
        with self.assertRaisesRegex(LayoutConflictError, 'staged exception'):
            self.db.save_shelf('1', 'A', [3, 2], side='2', shelf_id=self.sid, revert_location_id=True)
        with closing(self.db.connect()) as c:
            self.assertEqual(preserved_data(c), before)
        self.assertFalse(self.db.get_shelf_revert_location_id(self.sid))

    def test_designer_preview_keeps_contents_then_commit_updates_every_view(self):
        self.populate()
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = WarehouseMapperApp(root, self.path)
        first = self.db.get_slot_in_shelf(self.sid, 1, 1)
        with patch("ui.desktop.shelf_actions.messagebox") as dialogs:
            dialogs.askyesno.return_value = True
            app.shelf_selector.set(next(label for label, sid in app.shelf_choices.items() if sid == self.sid))
            app.load_selected_shelf()
            app.selected_address = first
            app.exceptions_view.selected_address = first
            self.assertFalse(app.has_pending_changes())
            app.designer.reverse_location_checkbox.invoke()
            self.assertTrue(app.has_pending_changes())
            grid = app.shelf_browser.shelf_grid.model
            self.assertEqual([c.cell for c in grid.rows[-1]], [3, 2, 1])
            self.assertEqual([c.count for c in grid.rows[-1]], [1, 1, 1])
            self.assertEqual([c.count for c in grid.rows[0]], [1, 0])
            left_preview = grid.rows[-1][0].slot_name
            self.assertEqual([pid for pid, _, p in app.shelf_browser.current_contents if p.slot_name == left_preview], ['LEFT'])
            self.assertEqual(self.db.get_slot_by_id(first.slot_id), first)
            # Cache reload while editing also preserves the unsaved preview mapping.
            app.reload_database_state()
            self.assertIn('L1-2A1-3', app.committed_locations['LEFT'])
            self.assertTrue(app.commit_changes())
            self.assertFalse(app.has_pending_changes())
            self.assertEqual(app.selected_address.slot_id, first.slot_id)
            self.assertEqual(app.selected_address.slot_number, 3)
            app.exceptions_view.refresh()
            self.assertEqual(app.exceptions_view.selected_address.slot_id, first.slot_id)
            self.assertEqual(app.exceptions_view.cell_var.get(), '3')
            rows = [app.exceptions_view.pending_tree.item(i, 'values') for i in app.exceptions_view.pending_tree.get_children()]
            self.assertTrue(any('L1-2A1-3' in str(row) for row in rows))
            app.load_selected_shelf()
            app.designer.reverse_location_checkbox.invoke()
            self.assertEqual([c.cell for c in app.shelf_browser.shelf_grid.model.rows[-1]], [1, 2, 3])
            self.assertEqual([pid for pid, _, p in app.shelf_browser.current_contents if p.slot_name == 'L1-2A1-1'], ['LEFT'])
            # Discard is a preview-only operation and must keep the saved reverse setting.
            app.new_shelf()
            self.assertTrue(self.db.get_shelf_revert_location_id(self.sid))
            self.assertFalse(app.designer.revert_location_id_var.get())
            self.assertFalse(app.has_pending_changes())
            dialogs.showerror.assert_not_called()

    def legacy(self):
        self.db.save_shelf("1", "B", [1], side="4")
        self.db.save_shelf("1", "C", [1], side="1")
        self.db.save_shelf("2", "D", [1], side="2")
        self.db.save_shelf("1", "E", [1], side="left")
        with closing(self.db.connect()) as c, c:
            c.execute("ALTER TABLE shelves DROP COLUMN revert_location_id")
            c.execute("DELETE FROM schema_migrations")
            c.execute("INSERT INTO schema_migrations(version) VALUES (4)")
        return self.path

    def test_migration_is_scoped_preserves_data_and_respects_later_manual_toggle(self):
        self.legacy()
        with self.assertRaisesRegex(RuntimeError, "shelf direction migration"):
            WarehouseDatabase(self.path)
        with closing(sqlite3.connect(self.path)) as c:
            before = preserved_data(c)
            result = migrate(c)
            self.assertEqual(result["status"], "applied")
            self.assertEqual(len(result["converted_shelf_ids"]), 2)
            self.assertEqual(preserved_data(c), before)
            self.assertEqual(c.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.db.save_shelf("1", "A", [3, 2], side="2", shelf_id=self.sid, revert_location_id=False)
        with closing(sqlite3.connect(self.path)) as c:
            self.assertEqual(migrate(c)["status"], "already_applied")
        self.assertFalse(WarehouseDatabase(self.path).get_shelf_revert_location_id(self.sid))
        with closing(self.db.connect()) as c:
            flags = {(r["floor"], r["side"]): r["revert_location_id"] for r in c.execute("SELECT * FROM shelves")}
        self.assertEqual(flags, {("1", "2"): 0, ("1", "4"): 1, ("1", "1"): 0, ("2", "2"): 0, ("1", "LEFT"): 0})

    def test_failed_conversion_rolls_back_column_flags_and_version(self):
        self.legacy()
        with closing(sqlite3.connect(self.path)) as c:
            c.execute("CREATE TRIGGER unexpected_change AFTER UPDATE ON shelves BEGIN UPDATE shelves SET shelf_code = 'BROKEN' WHERE shelf_id = NEW.shelf_id; END")
            c.commit()
            before = preserved_data(c)
            with self.assertRaisesRegex(RuntimeError, "changed existing warehouse data"):
                migrate(c)
            self.assertEqual(preserved_data(c), before)
            self.assertNotIn("revert_location_id", [r[1] for r in c.execute("PRAGMA table_info(shelves)")])
            self.assertEqual(c.execute("SELECT version FROM schema_migrations").fetchall(), [(4,)])

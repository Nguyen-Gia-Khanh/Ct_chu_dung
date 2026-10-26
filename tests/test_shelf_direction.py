"""Shelf ID direction, designer persistence, and repeat-safe operational conversion."""
from contextlib import closing
import sqlite3
import tkinter as tk
from unittest.mock import patch

from mapper.persistence.database import WarehouseDatabase
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

    def test_toggle_preserves_every_location_and_inventory_record(self):
        self.db.import_products({"P1": "Bolts"})
        first = self.db.get_slot_in_shelf(self.sid, 1, 1)
        second = self.db.get_slot_in_shelf(self.sid, 1, 3)
        self.db.assign_exception("P1", first.slot_id, "2026-10-01T08:00:00+00:00", 7)
        self.db.assign_exception("P1", second.slot_id, "2026-10-02T08:00:00+00:00")
        with closing(self.db.connect()) as c:
            before = preserved_data(c)
        # updated_at is the normal explicit shelf edit timestamp.
        for reverse in (True, False, True):
            self.db.save_shelf("1", "A", [3, 2], side="2", shelf_id=self.sid, revert_location_id=reverse)
            reopened = WarehouseDatabase(self.path)
            self.assertEqual(reopened.get_shelf_revert_location_id(self.sid), reverse)
            grid, contents = load_grid(reopened, self.sid)
            self.assertEqual([c.cell for c in grid.rows[-1]], [3, 2, 1] if reverse else [1, 2, 3])
            self.assertEqual({p.slot_name for _, _, p in contents}, {first.slot_name, second.slot_name})
            with closing(reopened.connect()) as c:
                after = preserved_data(c)
            for table in before.keys() - {"shelves"}:
                self.assertEqual(after[table], before[table], table)
        self.db.save_shelf("1", "A", [3, 2], side="2", shelf_id=self.sid)
        self.assertTrue(self.db.get_shelf_revert_location_id(self.sid))
        self.assertFalse(self.db.get_shelf_revert_location_id(self.db.save_shelf("1", "B", [2], side="4")))

    def test_designer_checkbox_preview_commit_reload_and_reset(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = WarehouseMapperApp(root, self.path)
        with patch("ui.desktop.shelf_actions.messagebox") as dialogs:
            dialogs.askyesno.return_value = True
            app.shelf_selector.set(next(label for label, sid in app.shelf_choices.items() if sid == self.sid))
            app.load_selected_shelf()
            self.assertFalse(app.designer.revert_location_id_var.get())
            self.assertFalse(app.has_pending_changes())
            app.designer.reverse_location_checkbox.invoke()
            self.assertTrue(app.has_pending_changes())
            self.assertEqual([c.cell for c in app.shelf_browser.shelf_grid.cells.values() if c.row == 1], [3, 2, 1])
            self.assertFalse(app.database.get_shelf_revert_location_id(self.sid))
            self.assertTrue(app.commit_changes())
            self.assertFalse(app.has_pending_changes())
            self.assertTrue(app.database.get_shelf_revert_location_id(self.sid))
            app.load_selected_shelf()
            self.assertTrue(app.designer.revert_location_id_var.get())
            # Direction participates in the canvas redraw key, including same-layout hot switches.
            app.designer.reverse_location_checkbox.invoke()
            self.assertEqual([c.cell for c in app.shelf_browser.shelf_grid.cells.values() if c.row == 1], [1, 2, 3])
            app.new_shelf()
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

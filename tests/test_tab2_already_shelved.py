"""Tab 2: assigning a product that is already on a shelf from the queue button plays
the error sound and assigns nothing. The catalog button relocates it silently."""

from __future__ import annotations

from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from mapper.persistence.database import WarehouseDatabase
from ui.desktop import sounds
from ui.desktop.app import WarehouseMapperApp

FIRST_TIME = "2026-10-31T08:00:00+07:00"
HOT = "12251K97T01"
SIMILAR = "12251K97T01B"  # contains HOT's ID, so a search for HOT shows it too
SPARE = "C9"


class AlreadyShelvedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        db_path = Path(self.temp_dir.name) / "warehouse.db"
        database = WarehouseDatabase(db_path)
        database.commit_shelf("1", "A", [3], {}, set(), side="1")
        database.import_products({HOT: "Brake pad", SIMILAR: "Brake pad B"})
        database.import_catalog_products({SPARE: ("Spare part", "")})
        first = database.get_slot_address("1", "1", "A", 1, 1)
        database.assign_catalog_direct_to_slot(first.slot_id, FIRST_TIME, {HOT: ("Brake pad", "")}, quantities={HOT: 7})

        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = WarehouseMapperApp(self.root, database_path=db_path)
        self.app.notebook.select(self.app.assignments)
        view = self.app.assignments
        for variable, value in (
            (view.floor_var, "1"), (view.side_var, "1"), (view.shelf_var, "A"), (view.row_var, "1"), (view.cell_var, "2"),
        ):
            variable.set(value)
        self.app.load_assignment_address()
        sound = patch("ui.desktop.assignment_actions.play_error_sound")
        self.sound = sound.start()
        self.addCleanup(sound.stop)
        dialog = patch("ui.desktop.assignment_actions.StockQuantityDialog")
        self.dialog = dialog.start()
        self.addCleanup(dialog.stop)

    def search(self, text: str) -> None:
        self.app.assignments.search_var.set(text)
        self.app.refresh_product_lists()

    def assert_refused(self, message: str = f"Not assigned: {HOT} is already at L1-1A1-1.") -> None:
        self.sound.assert_called_once()
        self.dialog.assert_not_called()
        self.assertEqual(self.app.assignments.search_location_text.get(), message)
        self.assertEqual(self.app.status_text.get(), message)
        placements = self.app.database.get_placement_details()
        self.assertEqual((placements[HOT].slot_name, placements[HOT].stock_qty), ("L1-1A1-1", 7))
        self.assertNotIn(SIMILAR, placements)
        self.assertNotIn(SPARE, placements)
        self.assertIsNone(self.app.last_shift_transfer)

    def test_quick_queue_click_on_a_scanned_shelved_product(self) -> None:
        self.search(HOT)
        self.assertIn(f"product::{SIMILAR}", self.app.assignments.queue_tree.get_children())
        self.app.assign_queue_selection_to_address(to_shelf=True)
        self.assert_refused()
        self.assertEqual(self.app.queue_shift_clicks, 0)

    def test_stock_entry_queue_click_with_a_shelved_product_selected(self) -> None:
        self.search(HOT)
        self.app.assignments.queue_tree.selection_set(f"product::{HOT}", f"product::{SIMILAR}")
        self.app.assign_queue_selection_to_address(to_shelf=False)
        self.assert_refused()

    def test_reassigning_to_the_same_cell_is_refused_too(self) -> None:
        self.app.assignments.cell_var.set("1")
        self.app.load_assignment_address()
        self.search(HOT)
        self.app.assign_queue_selection_to_address(to_shelf=True)
        self.assert_refused()

    # The lower catalog button is the forced relocation: it moves shelved products
    # to the loaded cell with no sound, from a normal click or with Shift.
    def test_quick_catalog_click_relocates_a_shelved_product_without_a_sound(self) -> None:
        self.search(HOT)
        self.app.assignments.catalog_tree.selection_set(f"catalog::{HOT}")
        self.app.assign_catalog_selection_to_address(to_shelf=True)
        self.sound.assert_not_called()
        placements = self.app.database.get_placement_details()
        self.assertEqual((placements[HOT].slot_name, placements[HOT].stock_qty), ("L1-1A1-2", 7))
        self.assertIsNotNone(self.app.last_shift_transfer)

    def test_stock_entry_catalog_click_relocates_shelved_products_without_a_sound(self) -> None:
        self.search("")
        self.app.assignments.catalog_tree.selection_set(f"catalog::{HOT}", f"catalog::{SPARE}")
        self.dialog.return_value.result = {HOT: 4, SPARE: 2}
        with patch.object(self.app.root, "wait_window"):
            self.app.assign_catalog_selection_to_address(to_shelf=False)
        self.sound.assert_not_called()
        self.dialog.assert_called_once()
        placements = self.app.database.get_placement_details()
        self.assertEqual((placements[HOT].slot_name, placements[HOT].stock_qty), ("L1-1A1-2", 4))
        self.assertEqual((placements[SPARE].slot_name, placements[SPARE].stock_qty), ("L1-1A1-2", 2))

    def test_catalog_click_into_the_same_cell_has_no_sound(self) -> None:
        self.app.assignments.cell_var.set("1")
        self.app.load_assignment_address()
        self.search(HOT)
        self.app.assignments.catalog_tree.selection_set(f"catalog::{HOT}")
        self.app.assign_catalog_selection_to_address(to_shelf=True)
        self.sound.assert_not_called()
        self.assertEqual(self.app.database.get_placement_details()[HOT].slot_name, "L1-1A1-1")

    def test_family_search_still_moves_its_ready_rows_without_a_sound(self) -> None:
        self.search("12251")
        self.app.assign_queue_selection_to_address(to_shelf=True)
        self.sound.assert_not_called()
        placements = self.app.database.get_placement_details()
        self.assertEqual(placements[SIMILAR].slot_name, "L1-1A1-2")
        self.assertEqual(placements[HOT].slot_name, "L1-1A1-1")

    def test_unshelved_catalog_product_assigns_without_a_sound(self) -> None:
        self.search(SPARE)
        self.app.assignments.catalog_tree.selection_set(f"catalog::{SPARE}")
        self.app.assign_catalog_selection_to_address(to_shelf=True)
        self.sound.assert_not_called()
        self.assertEqual(self.app.database.get_placement_details()[SPARE].slot_name, "L1-1A1-2")


class ErrorSoundTests(unittest.TestCase):
    def test_plays_the_windows_critical_stop_sound(self) -> None:
        fake = Mock(MB_ICONHAND=16)
        widget = Mock()
        with patch.object(sounds, "winsound", fake):
            sounds.play_error_sound(widget)
        fake.MessageBeep.assert_called_once_with(16)
        widget.bell.assert_not_called()

    def test_falls_back_to_the_tk_bell(self) -> None:
        for winsound in (None, Mock(MB_ICONHAND=16, MessageBeep=Mock(side_effect=RuntimeError))):
            with self.subTest(winsound=winsound):
                widget = Mock()
                with patch.object(sounds, "winsound", winsound):
                    sounds.play_error_sound(widget)
                widget.bell.assert_called_once()


if __name__ == "__main__":
    unittest.main()

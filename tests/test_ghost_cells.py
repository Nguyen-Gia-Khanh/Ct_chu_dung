"""Ghost cells: removed cells that still hold products, and rows inserted or removed in the middle."""

from __future__ import annotations

from contextlib import closing
import tkinter as tk
import unittest

from mapper.persistence.database import GhostCellError, Placement, WarehouseDatabase
from mapper.services.layout_plan import SavedCell, ghost_warning, plan_layout
from mapper.services.shelf_grid import (
    FILLED_COLOR, GHOST_COLOR, GHOST_SPACER_COLOR, build_grid, cell_color, load_grid, next_cell, plan_block_shift,
    trim_ghosts,
)
from tests.support import WorkspaceTestCase
from ui.desktop.widgets import ShelfGridCanvas

TIME = "2026-11-04T08:00:00+07:00"


def name(row: int, cell: int) -> str:
    return f"L1-1A{row}-{cell}"


def saved_rows(widths, *, occupied=(), ghosts=(), reverse=False):
    """Saved cells keyed by a readable id (row * 100 + position)."""
    cells = []
    for row, width in enumerate(widths, 1):
        for position in range(1, width + 1):
            cells.append(SavedCell(row * 100 + position, row, position,
                                   ghost=(row, position) in ghosts, occupied=(row, position) in occupied))
    return cells


def plan(saved, saved_row_count, layout, **options):
    return plan_layout(saved, saved_row_count, layout, floor="1", side="1", shelf_code="A", **options)


class PlanLayoutTests(unittest.TestCase):
    def test_lowering_a_row_keeps_cut_cells_up_to_the_last_occupied_one_as_ghosts(self) -> None:
        result = plan(saved_rows([10], occupied={(1, 10)}), 1, [8])
        self.assertEqual([(c.position, c.number, c.ghost) for c in result.ghosts], [(9, 9, True), (10, 10, True)])
        self.assertEqual(result.kept[110].name, name(1, 10))
        self.assertEqual(result.kept[108].name, name(1, 8))
        self.assertFalse(result.kept[108].ghost)
        self.assertEqual((result.deleted, result.created), (frozenset(), ()))

    def test_empty_cut_cells_are_deleted(self) -> None:
        result = plan(saved_rows([10], occupied={(1, 3)}), 1, [8])
        self.assertEqual(result.deleted, {109, 110})
        self.assertEqual(result.ghosts, [])

    def test_cells_past_the_last_occupied_ghost_are_deleted(self) -> None:
        result = plan(saved_rows([10], occupied={(1, 9)}), 1, [7])
        self.assertEqual([c.position for c in result.ghosts], [8, 9])
        self.assertEqual(result.deleted, {110})

    def test_reversed_row_ghosts_take_their_position_as_number(self) -> None:
        # Reversed IDs: position 4 is cell 1. After shrinking to 2 it would clash with the new cell 1.
        result = plan(saved_rows([4], occupied={(1, 4)}), 1, [2], revert_location_id=True)
        self.assertEqual([(c.position, c.number) for c in (result.kept[101], result.kept[102])], [(1, 2), (2, 1)])
        self.assertEqual([(c.position, c.number, c.name) for c in result.ghosts],
                         [(3, 3, name(1, 3)), (4, 4, name(1, 4))])

    def test_removed_middle_row_with_products_becomes_a_ghost_row_above_the_top(self) -> None:
        result = plan(saved_rows([2, 2, 2], occupied={(2, 1)}), 3, [2, 2], row_origins=[1, 3])
        self.assertEqual((result.kept[301].row, result.kept[301].name, result.kept[301].ghost), (2, name(2, 1), False))
        self.assertEqual([(c.row, c.position, c.name) for c in result.ghosts], [(3, 1, name(3, 1))])
        self.assertEqual(result.deleted, {202})
        self.assertEqual(result.row_sources, {1: 1, 2: 3, 3: 2})

    def test_removed_empty_row_disappears(self) -> None:
        result = plan(saved_rows([2, 2, 2]), 3, [2, 2], row_origins=[1, 3])
        self.assertEqual(result.deleted, {201, 202})
        self.assertEqual(result.ghosts, [])
        self.assertEqual(result.kept[302].name, name(2, 2))

    def test_inserting_a_row_bumps_the_rows_above_with_their_cells(self) -> None:
        result = plan(saved_rows([2, 2, 2], occupied={(3, 2)}), 3, [2, 2, 4, 2], row_origins=[1, 2, None, 3])
        self.assertEqual(result.kept[302].name, name(4, 2))
        self.assertEqual(result.kept[202].name, name(2, 2))
        self.assertEqual([c.name for c in result.created], [name(3, cell) for cell in range(1, 5)])
        self.assertEqual(result.row_sources, {1: 1, 2: 2, 4: 3})

    def test_inserting_below_the_ground_row_bumps_every_row(self) -> None:
        result = plan(saved_rows([1, 1]), 2, [3, 1, 1], row_origins=[None, 1, 2])
        self.assertEqual((result.kept[101].name, result.kept[201].name), (name(2, 1), name(3, 1)))
        self.assertEqual([c.name for c in result.created], [name(1, 1), name(1, 2), name(1, 3)])

    def test_ghosts_move_with_their_row(self) -> None:
        saved = saved_rows([1, 3], occupied={(2, 3)}, ghosts={(2, 2), (2, 3)})
        result = plan(saved, 2, [1, 1, 1], row_origins=[1, None, 2])
        self.assertEqual([(c.row, c.position, c.name) for c in result.ghosts], [(3, 2, name(3, 2)), (3, 3, name(3, 3))])

    def test_existing_ghost_rows_stay_above_a_new_top_row(self) -> None:
        saved = saved_rows([2, 2, 1], occupied={(3, 1)}, ghosts={(3, 1)})
        result = plan(saved, 2, [2, 2, 3], row_origins=[1, 2, None])
        self.assertEqual([(c.row, c.name) for c in result.ghosts], [(4, name(4, 1))])
        self.assertEqual(result.row_sources[4], 3)

    def test_leftover_rows_stack_in_their_old_order(self) -> None:
        saved = saved_rows([1, 1, 1, 1], occupied={(2, 1), (4, 1)}, ghosts={(4, 1)})
        result = plan(saved, 3, [1, 1], row_origins=[1, 3])
        self.assertEqual([(c.row, c.name) for c in result.ghosts], [(3, name(3, 1)), (4, name(4, 1))])
        self.assertEqual(result.row_sources, {1: 1, 2: 3, 3: 2, 4: 4})

    def test_widening_turns_ghosts_back_into_cells(self) -> None:
        saved = saved_rows([10], occupied={(1, 10)}, ghosts={(1, 9), (1, 10)})
        result = plan(saved, 1, [10])
        self.assertEqual(result.ghosts, [])
        self.assertEqual(result.kept[110].name, name(1, 10))
        self.assertEqual(result.created, ())

    def test_partly_widening_keeps_the_rest_as_ghosts(self) -> None:
        saved = saved_rows([10], occupied={(1, 10)}, ghosts={(1, 9), (1, 10)})
        result = plan(saved, 1, [9])
        self.assertFalse(result.kept[109].ghost)
        self.assertEqual([c.position for c in result.ghosts], [10])

    def test_default_origins_add_and_remove_at_the_top(self) -> None:
        removed = plan(saved_rows([2, 2, 2], occupied={(3, 2)}), 3, [2, 2])
        self.assertEqual([(c.row, c.position) for c in removed.ghosts], [(3, 1), (3, 2)])
        added = plan(saved_rows([2, 2]), 2, [2, 2, 3])
        self.assertEqual([c.name for c in added.created], [name(3, 1), name(3, 2), name(3, 3)])
        self.assertEqual(added.row_sources, {1: 1, 2: 2})

    def test_new_shelf_creates_every_cell(self) -> None:
        result = plan([], 0, [2, 1], revert_location_id=True)
        self.assertEqual([(c.row, c.position, c.name) for c in result.created],
                         [(1, 1, name(1, 2)), (1, 2, name(1, 1)), (2, 1, name(2, 1))])

    def test_row_origins_must_match_rows_and_keep_their_order(self) -> None:
        saved = saved_rows([1, 1, 1])
        for origins in ([1, 2], [2, 1, 3], [1, 1, 3], [1, 2, 4], [0, 1, 2]):
            with self.subTest(origins=origins), self.assertRaises(ValueError):
                plan(saved, 3, [1, 1, 1], row_origins=origins)


class GhostWarningTests(unittest.TestCase):
    def test_no_occupied_ghosts_means_no_warning(self) -> None:
        self.assertEqual(ghost_warning(plan(saved_rows([4]), 1, [2])), "")

    def test_occupied_ghosts_are_listed_by_row_without_spacers(self) -> None:
        text = ghost_warning(plan(saved_rows([10, 2, 2], occupied={(1, 10), (1, 8), (2, 1), (2, 2)}), 3, [7, 2],
                                  row_origins=[1, 3]))
        self.assertEqual(text, "⚠ Ghost cells still hold products: Row 1 cells 8, 10; Row 3 (was Row 2) "
                               "cells 1–2. They stay red on every shelf view until you move the products out.")

    def test_a_single_cell_reads_cell(self) -> None:
        text = ghost_warning(plan(saved_rows([3], occupied={(1, 3)}), 1, [2]))
        self.assertIn("Row 1 cell 3.", text)


class GhostDatabaseTests(WorkspaceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.db = WarehouseDatabase(self.folder / "warehouse.db")
        self.db.import_products({"P1": "Bolts", "P2": "Nuts", "P3": "Washers"})

    def shelf(self, layout, placements=(), **options):
        """Commit a shelf with products at (row, cell); returns its id."""
        return self.db.commit_shelf("1", "A", layout, {
            pid: Placement(name(row, cell), 5, TIME) for pid, (row, cell) in placements}, set(), side="1", **options)

    def slot(self, row, cell):
        return self.db.get_slot_by_name(name(row, cell))

    def snapshot(self):
        with closing(self.db.connect()) as connection:
            return {table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                    for table in ("slots", "ghost_slots", "placements", "exception_placements",
                                  "on_hand_queue", "wait_to_update_csv")}

    def staging_names_match(self) -> bool:
        with closing(self.db.connect()) as connection:
            return connection.execute("""SELECT COUNT(*) FROM wait_to_update_csv w JOIN slots s USING(slot_id)
                                         WHERE w.slot_name != s.slot_name""").fetchone()[0] == 0

    def test_lowering_an_occupied_row_commits_and_keeps_the_products_in_ghost_cells(self) -> None:
        shelf_id = self.shelf([10], [("P1", (1, 10))])
        self.shelf([8], shelf_id=shelf_id)
        self.assertEqual(self.db.get_shelf(shelf_id)[3], [8])
        self.assertEqual(self.db.get_shelf_ghosts(shelf_id), [(1, 9, name(1, 9)), (1, 10, name(1, 10))])
        self.assertEqual(self.db.get_product_locations("P1"), [name(1, 10)])
        self.assertTrue(self.slot(1, 10).ghost)
        self.assertFalse(self.slot(1, 8).ghost)

    def test_emptied_ghosts_hide_at_once_and_are_deleted_at_the_next_commit(self) -> None:
        shelf_id = self.shelf([10], [("P1", (1, 10))])
        self.shelf([8], shelf_id=shelf_id)
        self.db.move_slot_to_on_hand(self.slot(1, 10).slot_id, TIME)
        self.assertEqual(self.db.get_shelf_ghosts(shelf_id), [])
        self.assertIsNotNone(self.slot(1, 10))
        self.shelf([8], shelf_id=shelf_id)
        self.assertIsNone(self.slot(1, 10))
        self.assertIsNone(self.slot(1, 9))

    def test_widening_the_row_turns_ghosts_back_into_cells(self) -> None:
        shelf_id = self.shelf([10], [("P1", (1, 10))])
        self.shelf([8], shelf_id=shelf_id)
        self.shelf([10], shelf_id=shelf_id)
        self.assertEqual((self.db.get_shelf(shelf_id)[3], self.db.get_shelf_ghosts(shelf_id)), ([10], []))
        self.assertFalse(self.slot(1, 10).ghost)
        self.assertEqual(self.db.get_product_locations("P1"), [name(1, 10)])

    def test_reversed_row_ghost_is_renamed_to_its_position(self) -> None:
        shelf_id = self.shelf([4], [("P1", (1, 1))], revert_location_id=True)  # cell 1 sits at position 4
        self.shelf([2], shelf_id=shelf_id)
        self.assertEqual(self.db.get_product_locations("P1"), [name(1, 4)])
        self.assertEqual([ghost[1] for ghost in self.db.get_shelf_ghosts(shelf_id)], [3, 4])

    def test_removing_a_middle_row_drops_upper_rows_and_lifts_its_products_to_a_ghost_row(self) -> None:
        shelf_id = self.shelf([2, 2, 2], [("P1", (2, 1)), ("P2", (3, 2))])
        self.shelf([2, 2], shelf_id=shelf_id, row_origins=[1, 3])
        self.assertEqual(self.db.get_shelf(shelf_id)[3], [2, 2])
        self.assertEqual(self.db.get_product_locations("P2"), [name(2, 2)])
        self.assertEqual(self.db.get_product_locations("P1"), [name(3, 1)])
        self.assertEqual(self.db.get_shelf_ghosts(shelf_id), [(3, 1, name(3, 1))])

    def test_inserting_a_middle_row_bumps_upper_rows_with_products_and_staged_names(self) -> None:
        shelf_id = self.shelf([2, 2], [("P1", (2, 2))])
        self.db.assign_exception("P1", self.slot(1, 1).slot_id, TIME, product_name="Bolts v2")
        self.db.assign_exception("P1", self.slot(2, 1).slot_id, TIME)
        self.shelf([2, 3, 2], shelf_id=shelf_id, row_origins=[1, None, 2])
        self.assertEqual(self.db.get_shelf(shelf_id)[3], [2, 3, 2])
        self.assertEqual(set(self.db.get_product_locations("P1")), {name(3, 2), name(1, 1), name(3, 1)})
        self.assertTrue(self.staging_names_match())
        self.assertEqual(self.db.get_shelf_ghosts(shelf_id), [])

    def test_a_new_top_row_pushes_ghost_rows_up(self) -> None:
        shelf_id = self.shelf([1, 1], [("P1", (2, 1))])
        self.shelf([1], shelf_id=shelf_id)
        self.shelf([1, 3], shelf_id=shelf_id, row_origins=[1, None])
        self.assertEqual(self.db.get_product_locations("P1"), [name(3, 1)])
        self.assertEqual(self.db.get_shelf(shelf_id)[3], [1, 3])

    def test_nothing_can_be_added_to_a_ghost_cell(self) -> None:
        shelf_id = self.shelf([3, 2], [("P1", (1, 3)), ("P2", (2, 1))])
        self.shelf([2, 2], shelf_id=shelf_id)
        ghost, normal = self.slot(1, 3).slot_id, self.slot(2, 1).slot_id
        self.db.add_to_on_hand({"P3": 4}, TIME)
        before = self.snapshot()
        attempts = {
            "on-hand": lambda: self.db.assign_on_hand_to_slot(ghost, TIME, ["P3"]),
            "catalog": lambda: self.db.assign_catalog_direct_to_slot(ghost, TIME, {"P3": "Washers"}),
            "exception": lambda: self.db.assign_exception("P2", ghost, TIME),
            "combine": lambda: self.db.combine_slot_contents(normal, ghost),
            "swap": lambda: self.db.swap_slot_contents(normal, ghost),
            "shift": lambda: self.db.shift_slot_contents({normal: ghost}),
            "commit": lambda: self.shelf([2, 2], [("P3", (1, 3))], shelf_id=shelf_id),
        }
        for label, attempt in attempts.items():
            with self.subTest(label), self.assertRaisesRegex(GhostCellError, name(1, 3)):
                attempt()
            self.assertEqual(self.snapshot(), before)

    def ghost_shelf(self) -> int:
        """Row 1 shrinks from 3 to 2 cells while P1 sits in cell 1-3."""
        shelf_id = self.shelf([3, 3], [("P1", (1, 3))])
        self.shelf([2, 3], shelf_id=shelf_id)
        self.assertTrue(self.slot(1, 3).ghost)
        return shelf_id

    def test_a_ghost_block_can_move_up(self) -> None:
        shelf_id = self.ghost_shelf()
        self.db.shift_slot_contents({self.slot(1, 3).slot_id: self.slot(2, 3).slot_id})
        self.assertEqual(self.db.get_product_locations("P1"), [name(2, 3)])
        self.assertEqual(self.db.get_shelf_ghosts(shelf_id), [])

    def test_a_full_ghost_can_switch_with_an_empty_cell(self) -> None:
        shelf_id = self.ghost_shelf()
        self.db.swap_slot_contents(self.slot(1, 3).slot_id, self.slot(2, 1).slot_id)
        self.assertEqual(self.db.get_product_locations("P1"), [name(2, 1)])
        self.assertEqual(self.db.get_shelf_ghosts(shelf_id), [])

    def test_a_ghost_can_be_combined_into_a_normal_cell(self) -> None:
        self.ghost_shelf()
        self.db.combine_slot_contents(self.slot(1, 3).slot_id, self.slot(2, 1).slot_id)
        self.assertEqual(self.db.get_product_locations("P1"), [name(2, 1)])

    def test_layout_cells_report_positions_ghosts_and_occupancy(self) -> None:
        shelf_id = self.shelf([3], [("P1", (1, 1))], revert_location_id=True)  # cell 1 is on the right
        self.shelf([2], shelf_id=shelf_id)
        row_count, cells = self.db.get_layout_cells(shelf_id)
        self.assertEqual(row_count, 1)
        self.assertEqual(sorted((c.position, c.ghost, c.occupied, c.name) for c in cells),
                         [(1, False, False, name(1, 2)), (2, False, False, name(1, 1)), (3, True, True, name(1, 3))])

    def test_load_grid_draws_ghosts_after_the_row_and_ghost_rows_on_top(self) -> None:
        shelf_id = self.shelf([3, 1], [("P1", (1, 3)), ("P2", (2, 1))])
        self.shelf([2], shelf_id=shelf_id)
        grid, _contents = load_grid(self.db, shelf_id)
        self.assertEqual(grid.layout, (2,))
        self.assertEqual([[(c.slot_name, c.ghost) for c in row] for row in grid.rows], [
            [(name(2, 1), True)],
            [(name(1, 1), False), (name(1, 2), False), (name(1, 3), True)],
        ])

    def test_tab4_summary_counts_the_ghosts_that_hold_products(self) -> None:
        from tkinter import TclError
        from ui.desktop.shelf_browser import ShelfBrowserView
        try:
            root = tk.Tk()
        except TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")
        root.withdraw()
        self.addCleanup(root.destroy)
        shelf_id = self.shelf([4], [("P1", (1, 4))])
        self.shelf([2], shelf_id=shelf_id)  # cell 3 is a spacer, cell 4 holds P1
        browser = ShelfBrowserView(root, self.db)
        browser.show_saved_shelf(shelf_id)
        self.assertTrue(browser.summary_text.get().endswith("· 2 cells · 1 ghost cell"), browser.summary_text.get())

    def test_label_printer_skips_ghost_cells(self) -> None:
        from utils.labels.app import LabelDatabase
        shelf_id = self.shelf([3, 1], [("P1", (1, 3)), ("P2", (2, 1))])
        self.shelf([2], shelf_id=shelf_id)
        labels = LabelDatabase(self.db.path)
        shelf = labels.read_shelves([shelf_id])[0]
        self.assertEqual(shelf.rows, ((1, 2),))
        self.assertEqual(sorted(cell.location_id for cell in shelf.cells), [name(1, 1), name(1, 2)])
        self.assertEqual(labels.list_shelves()[0]["cell_count"], 2)


class GhostGridTests(unittest.TestCase):
    def grid(self, layout, filled=(), ghosts=(), reverse=False):
        return build_grid("1", "1", "A", layout, filled, ghosts=ghosts, revert_location_id=reverse)

    def test_ghost_cells_follow_the_row_and_ghost_rows_sit_on_top(self) -> None:
        grid = self.grid([2, 1], [name(1, 4), name(4, 1)],
                         ghosts=[(1, 3, name(1, 3)), (1, 4, name(1, 4)), (4, 1, name(4, 1))])
        self.assertEqual(grid.layout, (2, 1))
        self.assertEqual([[c.slot_name for c in row] for row in grid.rows], [
            [name(4, 1)], [], [name(2, 1)], [name(1, 1), name(1, 2), name(1, 3), name(1, 4)]])
        self.assertEqual([c.slot_name for c in grid.ghosts], [name(1, 3), name(1, 4), name(4, 1)])

    def test_reversed_rows_draw_ghosts_right_of_cell_one(self) -> None:
        grid = self.grid([2], [name(1, 3)], ghosts=[(1, 3, name(1, 3))], reverse=True)
        self.assertEqual([c.cell for c in grid.rows[0]], [2, 1, 3])

    def test_ghost_colors(self) -> None:
        self.assertEqual(cell_color(2, ghost=True), GHOST_COLOR)
        self.assertEqual(cell_color(0, ghost=True), GHOST_SPACER_COLOR)
        self.assertEqual(cell_color(2, ghost=True, selected=True), GHOST_COLOR)
        self.assertEqual(cell_color(2), FILLED_COLOR)

    def test_next_cell_skips_ghosts(self) -> None:
        grid = self.grid([2, 1], [name(1, 3)], ghosts=[(1, 3, name(1, 3))])
        current = next(c for c in grid.cells() if c.slot_name == name(1, 2))
        self.assertEqual(next_cell(grid, current).slot_name, name(2, 1))

    def test_a_ghost_block_moves_up_but_never_into_a_ghost(self) -> None:
        grid = self.grid([2, 3], [name(1, 3), name(2, 1)], ghosts=[(1, 3, name(1, 3))])
        up = plan_block_shift(grid, {name(1, 3)}, 1, 0)
        self.assertEqual((up.moves, up.ghosts), ({name(1, 3): name(2, 3)}, ()))
        self.assertEqual(plan_block_shift(grid, {name(1, 2)}, 0, 1).ghosts, ())  # empty: nothing to carry
        grid = self.grid([2, 3], [name(1, 2), name(1, 3), name(2, 3)], ghosts=[(1, 3, name(1, 3))])
        right = plan_block_shift(grid, {name(1, 2)}, 0, 1)
        self.assertEqual((right.moves, right.ghosts), ({}, (name(1, 3),)))
        down = plan_block_shift(grid, {name(2, 3)}, -1, 0)
        self.assertEqual((down.moves, down.ghosts), ({}, (name(1, 3),)))

    def test_trim_drops_emptied_ghosts_from_the_right_and_empty_top_rows(self) -> None:
        grid = self.grid([2], [name(1, 4), name(2, 1)],
                         ghosts=[(1, 3, name(1, 3)), (1, 4, name(1, 4)), (2, 1, name(2, 1))])
        trimmed = trim_ghosts(grid, {name(1, 4): 0, name(2, 1): 0})
        self.assertEqual(trimmed.ghosts, ())
        self.assertEqual([[c.slot_name for c in row] for row in trimmed.rows], [[name(1, 1), name(1, 2)]])
        kept = trim_ghosts(grid, {name(1, 4): 1, name(2, 1): 0})
        self.assertEqual([c.slot_name for c in kept.ghosts], [name(1, 3), name(1, 4)])


class GhostCanvasTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.canvas = ShelfGridCanvas(self.root)
        self.canvas.pack()
        self.canvas.show(build_grid("1", "1", "A", [2], [name(1, 4)],
                                    ghosts=[(1, 3, name(1, 3)), (1, 4, name(1, 4))]))

    def test_ghosts_are_red_with_a_warning_sign(self) -> None:
        self.assertEqual(self.canvas.cell_fill(name(1, 4)), GHOST_COLOR)
        self.assertEqual(self.canvas.cell_fill(name(1, 3)), GHOST_SPACER_COLOR)
        self.assertTrue(self.canvas.cell_text(name(1, 4)).startswith("⚠"))
        self.assertFalse(self.canvas.cell_text(name(1, 1)).startswith("⚠"))

    def test_selected_ghost_keeps_its_red_fill(self) -> None:
        self.canvas.select(name(1, 4))
        self.assertEqual(self.canvas.cell_fill(name(1, 4)), GHOST_COLOR)

    def test_emptying_the_last_ghost_removes_the_ghost_cells(self) -> None:
        self.canvas.set_count(name(1, 4), 0)
        self.assertNotIn(name(1, 4), self.canvas)
        self.assertNotIn(name(1, 3), self.canvas)
        self.assertIn(name(1, 2), self.canvas)


if __name__ == "__main__":
    unittest.main()

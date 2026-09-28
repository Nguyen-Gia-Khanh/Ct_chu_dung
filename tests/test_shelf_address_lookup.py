"""Shelf address entry must find the exact saved shelf across all three views."""

from unittest import TestCase

from ui.desktop.shelf_address_lookup import find_shelf_id


class ShelfAddressLookupTests(TestCase):
    def test_matches_all_three_address_parts(self) -> None:
        shelves = [
            (10, "1", "1", "A"),
            (11, "1", "2", "A"),
            (12, "2", "1", "A"),
        ]
        self.assertEqual(find_shelf_id(shelves, " 1 ", "2", " a "), 11)
        self.assertEqual(find_shelf_id(shelves, "2", "1", "A"), 12)
        self.assertIsNone(find_shelf_id(shelves, "1", "3", "A"))
        self.assertIsNone(find_shelf_id(shelves, "1", "", "A"))

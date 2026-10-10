"""Reloading warehouse state must not redraw Tkinter tables twice."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from ui.desktop.state_actions import StateActions


class DesktopStateTests(TestCase):
    def test_reload_updates_search_indexes_without_redrawing_tables(self) -> None:
        app = StateActions()
        app.database = Mock()
        app.database.get_product_records.return_value = [("P1", "Bolts", "Bolt", "P1")]
        app.database.get_catalog_only_product_ids.return_value = set()
        app.database.get_display_catalog_products.return_value = [
            ("P1", "Bolts", "Bolt", "P1"), ("P2", "Washers", "Washer", "P2"),
        ]
        app.database.get_placement_details.return_value = {}
        app.database.get_on_hand_products.return_value = {}
        app.database.get_returned_queue_products.return_value = {}
        app.current_shelf_id = None
        app.preview_key = None
        app.transferred_stock = {}
        app.refresh_shelf_selector = Mock()
        app.refresh_product_lists = Mock()
        app.refresh_on_hand_queue = Mock()
        app.refresh_address_contents = Mock()
        app.refresh_change_summary = Mock()
        app.exceptions_view = SimpleNamespace(refresh=Mock())

        app.reload_database_state(reload_catalog=True)
        self.assertEqual(app.product_id_lookup["p2"], "P2")
        app.refresh_product_lists.assert_not_called()
        app.refresh_on_hand_queue.assert_not_called()

        app.refresh_all_views()
        app.refresh_product_lists.assert_called_once()
        app.refresh_on_hand_queue.assert_called_once()
        app.refresh_address_contents.assert_called_once()
        app.exceptions_view.refresh.assert_called_once()

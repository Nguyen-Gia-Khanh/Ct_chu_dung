"""Canonical SKU and name searches use caches and preserve inventory during imports."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from contextlib import closing
from unittest.mock import patch

from mapper.core.common import exact_product_search_id, normalize_search, product_search_text
from mapper.persistence.database import WarehouseDatabase
from tests.support import WorkspaceTestCase
from ui.desktop.app import WarehouseMapperApp


PRODUCT_ID = "91201KVB901"
CATALOG_ID = "22100ABC000"


class ProductSearchTests(WorkspaceTestCase):


    def make_app(self) -> WarehouseMapperApp:
        path = self.folder / "warehouse.db"
        database = WarehouseDatabase(path)
        database.import_products({PRODUCT_ID: ("Ốc vít", "Fastener")})
        database.import_catalog_products({
            CATALOG_ID: ("Reference", ''),
            "ABC1": ("First distinct ID", ''),
            "ABC2": ("Second distinct ID", ''),
        })
        database.save_shelf("1", "A", [1], side="1")
        slot = database.get_slot_address("1", "1", "A", 1, 1)
        database.add_to_on_hand({PRODUCT_ID: 7}, "2026-10-10T08:00:00+07:00")
        database.assign_on_hand_to_slot(slot.slot_id, "2026-10-10T08:01:00+07:00", [PRODUCT_ID])
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        return WarehouseMapperApp(root, path)

    def test_search_bars_use_caches_and_display_canonical_ids(self) -> None:
        app = self.make_app()
        primal = app.primal_view
        primal.refresh()
        exceptions = app.exceptions_view
        with patch.object(app.database, "connect", side_effect=AssertionError("Search opened SQLite")):
            for query in (PRODUCT_ID, "91201kvb901", "91201kvb901", "01kvb9", "oc vit", "fastener"):
                with self.subTest(query=query):
                    app.assignments.search_var.set(query)
                    app.refresh_product_lists()
                    self.assertEqual(app.assignments.queue_tree.get_children(), (f"product::{PRODUCT_ID}",))
                    self.assertEqual(app.assignments.catalog_tree.get_children(), (f"catalog::{PRODUCT_ID}",))
                    primal.search_var.set(query)
                    primal.refresh_results(navigate=False)
                    self.assertEqual(primal.primal_tree.get_children(), (f"primal::{PRODUCT_ID}",))
                    self.assertEqual(primal.catalog_tree.get_children(), (f"catalog::{PRODUCT_ID}",))
                    exceptions.catalog_search_var.set(query)
                    exceptions._filter_catalog_tree()
                    self.assertEqual(exceptions.catalog_tree.get_children(), (PRODUCT_ID,))
            app.assignments.search_var.set("91201kvb901")
            app.refresh_product_lists()
            self.assertIn("Already at", app.assignments.search_location_text.get())
            primal.search_var.set("91201kvb901")
            primal.refresh_results(navigate=False)
            self.assertIn(PRODUCT_ID, primal.search_status_text.get())
            app.assignments.search_var.set("22100abc000")
            app.refresh_product_lists()
            self.assertEqual(app.assignments.queue_tree.get_children(), ())
            self.assertEqual(app.assignments.catalog_tree.get_children(), (f"catalog::{CATALOG_ID}",))
        self.assertNotIn("product_id_search", app.assignments.queue_tree["columns"])
        self.assertNotIn("product_id_search", primal.catalog_tree["columns"])

    def test_csv_imports_and_inventory_readback_keep_dashless_cache(self) -> None:
        app = self.make_app()
        placement = app.database.get_placement_details()[PRODUCT_ID]
        source = self.folder / "products.csv"
        contents = f"code;name;short\n{PRODUCT_ID};Updated queue;Queue\n{CATALOG_ID};Updated reference;Ref\n"
        source.write_text(contents, encoding="utf-8", newline="")
        with (
            patch("ui.desktop.catalog_actions.filedialog.askopenfilename", return_value=str(source)),
            patch("ui.desktop.catalog_actions.ColumnMappingDialog") as mapping,
            patch.object(app.root, "wait_window"),
            patch("ui.desktop.catalog_actions.messagebox") as dialogs,
        ):
            mapping.return_value.result = (0, 1, 2)
            for import_csv in (app.import_catalog_csv, app.import_csv):
                import_csv()
                dialogs.showerror.assert_not_called()
                self.assertIn("91201kvb901", app.product_search[PRODUCT_ID])
                self.assertIn("22100abc000", app.catalog_search[CATALOG_ID])
        app.reconcile_inventory_products([PRODUCT_ID], queue_changed=False, catalog_changed=False)
        self.assertIn("91201kvb901", app.product_search[PRODUCT_ID])
        self.assertIn("91201kvb901", app.catalog_search[PRODUCT_ID])
        self.assertEqual(app.database.get_placement_details()[PRODUCT_ID], placement)
        self.assertEqual(source.read_text(encoding="utf-8"), contents)

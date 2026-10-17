"""Both desktop import buttons must preserve inventory and refresh catalog names."""

from __future__ import annotations

import tkinter as tk
from unittest.mock import patch

from mapper.features.csv_import import read_csv
from mapper.persistence.database import WarehouseDatabase
from tests.support import WorkspaceTestCase
from ui.desktop.app import WarehouseMapperApp


class CSVImportTests(WorkspaceTestCase):
    def test_ragged_csv_keeps_quoted_fields_for_each_supported_delimiter(self) -> None:
        source = self.folder / "products.csv"
        for delimiter in (",", ";", "\t", "|"):
            with self.subTest(delimiter=delimiter):
                source.write_text(
                    f"code{delimiter}name{delimiter}short\n\n"
                    f'P1{delimiter}"Name {delimiter} with\nnewline"{delimiter}Short\n'
                    f"P2{delimiter}Too short\n",
                    encoding="utf-8",
                    newline="",
                )
                data = read_csv(source)
                self.assertEqual(data.headers, ["code", "name", "short"])
                self.assertEqual(data.rows, [
                    ["P1", f"Name {delimiter} with\nnewline", "Short"],
                    ["P2", "Too short"],
                ])

    def test_import_modes_preserve_inventory_and_refresh_tab_three(self) -> None:
        path = self.folder / "warehouse.db"
        database = WarehouseDatabase(path)
        database.import_products({"P1": ("Queue original", "Queue")})
        database.import_catalog_products({"P1": ("Catalog original", '')})
        database.save_shelf("1", "A", [1], side="1")
        address = database.get_slot_address("1", "1", "A", 1, 1)
        database.add_to_on_hand({"P1": 7}, "2026-10-03T08:00:00+07:00")
        database.assign_on_hand_to_slot(address.slot_id, "2026-10-03T08:01:00+07:00", ["P1"])
        placement = database.get_placement_details()["P1"]

        source = self.folder / "products.csv"
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = WarehouseMapperApp(root, path)

        with (
            patch("ui.desktop.catalog_actions.filedialog.askopenfilename", return_value=str(source)),
            patch("ui.desktop.catalog_actions.ColumnMappingDialog") as mapping,
            patch.object(root, "wait_window"),
            patch("ui.desktop.catalog_actions.messagebox") as dialogs,
        ):
            mapping.return_value.result = (0, 1, 2)
            for catalog in (False, True):
                with self.subTest(catalog=catalog):
                    source.write_text(
                        "code;name;short;extra\n"
                        " P1 ;First name;First;x\n"
                        + ("P3;Reference; ;x\n" if catalog else "P2;Washers; ;x\n")
                        + ("P1;Warehouse name;Warehouse;x\n" if catalog else "P1;Final name;Final;x\n")
                        + ";No ID;;x\nP5; ;Invalid;x\nP4;Too short\n",
                        encoding="utf-8-sig",
                    )
                    queue_before = database.get_product_records()
                    catalog_before = database.get_catalog_products()
                    (app.import_catalog_csv if catalog else app.import_csv)()
                    dialogs.showerror.assert_not_called()
                    summary = dialogs.showinfo.call_args.args[1]
                    label = "catalog products" if catalog else "products"
                    self.assertIn(f"New {label}: 1", summary)
                    self.assertIn(f"Existing {label} updated: 1", summary)
                    self.assertIn("Blank/invalid rows skipped: 3", summary)
                    self.assertIn("Duplicate IDs inside CSV: 1", summary)
                    self.assertEqual(database.get_placement_details()["P1"], placement)
                    expected = ({'P1':('Warehouse','Warehouse name'),'P2':('Washers',''),'P3':('Reference','Reference')}
                                if catalog else {'P1':('Final name','Final'),'P2':('Washers','')})
                    self.assertEqual({pid:(name,brand) for pid,name,brand in database.get_catalog_products()},expected)
                    app.primal_view.refresh()
                    self.assertEqual(app.primal_view.catalog_products,expected)

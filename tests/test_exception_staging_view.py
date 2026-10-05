import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

from mapper.persistence.database import WarehouseDatabase
from ui.desktop.exceptions_view import ExceptionsView


class ExceptionStagingViewTest(unittest.TestCase):
    def test_buttons_and_staged_status(self):
        with tempfile.TemporaryDirectory() as folder:
            database = WarehouseDatabase(Path(folder) / "warehouse.db")
            database.initialize()
            database.commit_shelf("1", "A", [1], {}, set(), side="1")
            slot = database.get_slot_by_name("L1-1A1-1")
            root = tk.Tk()
            root.withdraw()
            try:
                view = ExceptionsView(root, database)
                view.pack()
                labels = []

                def collect(widget):
                    for child in widget.winfo_children():
                        if isinstance(child, ttk.Button):
                            labels.append(child.cget("text"))
                        collect(child)

                collect(view)
                for label in ("Save name", "Append back to CSV", "Add to catalog", "Wipe from treeview"):
                    self.assertIn(label, labels)

                view.selected_address = slot
                view.product_id_var.set("99999-ZZZ-999")
                view.product_name_var.set("Sample name")
                view.assign_exception()
                iid = view.pending_tree.get_children()[0]
                view.pending_tree.selection_set(iid)
                self.assertEqual(view.pending_tree.item(iid, "values")[3], "Hasn't Add to: CSV + catalog")

                view.add_to_catalog()
                self.assertEqual(view.pending_tree.item(iid, "values")[3], "Hasn't Add to: CSV")
                csv_path = Path(folder) / "products.csv"
                with patch("ui.desktop.exceptions_view.filedialog.askopenfilename", return_value=str(csv_path)):
                    with patch("ui.desktop.exceptions_view.messagebox.showinfo"):
                        view.append_to_csv()
                self.assertEqual(view.pending_tree.item(iid, "values")[3], "Updated")

                view.product_id_var.set("99999-ZZZ-999")
                view.product_name_var.set("Edited name")
                view.save_name()
                self.assertEqual(view.pending_tree.item(iid, "values")[3], "Hasn't Add to: CSV + catalog")
                with patch("ui.desktop.exceptions_view.messagebox.askyesno", return_value=True):
                    view.wipe_selected()
                self.assertEqual(view.pending_tree.get_children(), ())
                self.assertEqual(database.get_product_locations("99999-ZZZ-999"), [])
                self.assertNotIn("99999-ZZZ-999", {item[0] for item in database.get_catalog_products()})
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()

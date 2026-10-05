"""Unit tests for barcode scanner product ID formatting and scanner vs typer detection."""

import time
import tkinter as tk
from tkinter import ttk
import unittest

from utils.barcode_scanner import (
    BarcodeScanner,
    bind_auto_highlight,
    format_product_id,
    process_entry_return,
    select_all_entry_text,
)


class BarcodeScannerFormatTests(unittest.TestCase):
    def test_formats_standard_5_3_3(self) -> None:
        self.assertEqual(format_product_id("06410KFL850"), "06410-KFL-850")
        self.assertEqual(format_product_id("12100KWW740"), "12100-KWW-740")
        self.assertEqual(format_product_id("06410-KFL-850"), "06410-KFL-850")

    def test_formats_extended_5_3_5(self) -> None:
        self.assertEqual(format_product_id("04801K0G900ZC"), "04801-K0G-900ZC")
        self.assertEqual(format_product_id("52200KTL640ZB"), "52200-KTL-640ZB")
        self.assertEqual(format_product_id("52200-KTL-640ZB"), "52200-KTL-640ZB")

    def test_formats_5_3_4(self) -> None:
        self.assertEqual(format_product_id("08E50KVG700C"), "08E50-KVG-700C")
        self.assertEqual(format_product_id("08E50-KVG-700C"), "08E50-KVG-700C")

    def test_formats_5_3_2(self) -> None:
        self.assertEqual(format_product_id("9280012000"), "92800-120-00")
        self.assertEqual(format_product_id("92800-120-00"), "92800-120-00")

    def test_formats_5_3_any_single_suffix(self) -> None:
        self.assertEqual(format_product_id("12345ABC1"), "12345-ABC-1")

    def test_preserves_non_standard_hyphenated_identifiers(self) -> None:
        self.assertEqual(format_product_id("EXC-99999-OVERSIZE"), "EXC-99999-OVERSIZE")
        self.assertEqual(format_product_id("HOT-1"), "HOT-1")
        self.assertEqual(format_product_id("H06430-K56-N12"), "H06430-K56-N12")

    def test_handles_whitespace_and_empty(self) -> None:
        self.assertEqual(format_product_id("  04801K0G900ZC  "), "04801-K0G-900ZC")
        self.assertEqual(format_product_id(""), "")
        self.assertEqual(format_product_id(None), "")
        self.assertEqual(format_product_id("   "), "")

    def test_short_inputs_unchanged(self) -> None:
        self.assertEqual(format_product_id("12345"), "12345")
        self.assertEqual(format_product_id("12345678"), "12345678")


class BarcodeScannerDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.geometry("100x100+0+0")
        self.root.focus_force()
        self.root.update()

    def tearDown(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_scanner_burst_detection(self) -> None:
        scanned_result = []
        scanner = BarcodeScanner(self.root, callback=lambda code: scanned_result.append(code))

        # Simulate fast scanner keystrokes (<60ms apart)
        for char in "06410KFL850":
            self.root.event_generate(f"<KeyPress-{char}>")
        self.root.event_generate("<KeyPress-Return>")
        self.root.update()

        self.assertEqual(scanned_result, ["06410-KFL-850"])
        self.assertFalse(scanner.is_scanner())

    def test_human_typing_not_detected_as_scanner(self) -> None:
        scanned_result = []
        scanner = BarcodeScanner(
            self.root,
            callback=lambda code: scanned_result.append(code),
            max_gap=0.04,
        )

        # Simulate human typing with pauses > max_gap
        for char in "12345":
            self.root.event_generate(f"<KeyPress-{char}>")
            time.sleep(0.05)
        self.root.update()

        self.assertFalse(scanner.is_scanner())
        self.root.event_generate("<KeyPress-Return>")
        self.root.update()

        # Scanner callback should NOT have fired
        self.assertEqual(scanned_result, [])

    def test_entry_replacement_without_preselection(self) -> None:
        """Verify that scanning into an unselected entry with old text replaces it with formatted ID."""
        search_var = tk.StringVar(self.root, value="OLD-TEXT-999")
        entry = ttk.Entry(self.root, textvariable=search_var)
        entry.pack()

        scanned = []
        scanner = BarcodeScanner(self.root, callback=lambda code: scanned.append(code))

        def on_return(_event=None):
            return process_entry_return(entry, search_var, None, scanner=scanner)

        entry.bind("<Return>", on_return)
        bind_auto_highlight(entry)

        entry.focus_set()
        entry.selection_clear()
        entry.icursor(tk.END)
        self.root.update()

        # Scanner types into entry without it being pre-selected
        for char in "04801K0G900ZC":
            entry.event_generate(f"<KeyPress-{char}>")
        entry.event_generate("<KeyPress-Return>")
        self.root.update()
        self.root.update_idletasks()

        # The entry content must be replaced completely by the formatted ID (NOT appended!)
        self.assertEqual(search_var.get(), "04801-K0G-900ZC")
        self.assertTrue(entry.selection_present())


class BarcodeScannerTabRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        from unittest.mock import patch
        self.patcher1 = patch("tkinter.messagebox.showinfo")
        self.patcher2 = patch("tkinter.messagebox.showerror")
        self.patcher1.start()
        self.patcher2.start()

        self.root = tk.Tk()
        self.root.geometry("1050x650+0+0")
        self.root.withdraw()

        from ui.desktop.app import WarehouseMapperApp
        self.app = WarehouseMapperApp(self.root)

    def tearDown(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass
        self.patcher1.stop()
        self.patcher2.stop()

    def test_routing_to_tab2(self) -> None:
        self.app.notebook.select(self.app.assignments)
        self.app.on_tab_changed()
        self.app.on_global_barcode_scan("06410KFL850")
        self.assertEqual(self.app.assignments.search_var.get(), "06410-KFL-850")

    def test_routing_to_tab3(self) -> None:
        self.app.notebook.select(self.app.primal_view)
        self.app.on_tab_changed()
        self.app.on_global_barcode_scan("12100KWW740")
        self.assertEqual(self.app.primal_view.search_var.get(), "12100-KWW-740")

    def test_routing_to_tab5(self) -> None:
        self.app.notebook.select(self.app.cell_transfer)
        self.app.on_tab_changed()
        self.app.on_global_barcode_scan("04801K0G900ZC")
        self.assertEqual(self.app.cell_transfer.left.search_var.get(), "04801-K0G-900ZC")

    def test_routing_to_tab6(self) -> None:
        self.app.notebook.select(self.app.exceptions_view)
        self.app.on_tab_changed()
        self.app.on_global_barcode_scan("08E50KVG700C")
        self.assertEqual(self.app.exceptions_view.product_id_var.get(), "08E50-KVG-700C")


if __name__ == "__main__":
    unittest.main()

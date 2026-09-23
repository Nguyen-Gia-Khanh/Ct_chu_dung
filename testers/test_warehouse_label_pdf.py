"""Tests for warehouse label PDF layout and rendering features."""

from pathlib import Path
import re
import unittest

from utils.warehouse_label_pdf import (
    Cell,
    Product,
    _compute_layout_slots,
    render_labels_pdf,
)
from warehouse_label_printer import _PRINT_FILE_TIME


class TestWarehouseLabelPdf(unittest.TestCase):
    def test_compute_layout_slots_counts(self):
        mm = 72.0 / 25.4
        a4_w, a4_h = 297.0 * mm, 210.0 * mm

        # Full mode
        slots_full_ls = _compute_layout_slots(a4_w, a4_h, "full", 7, "landscape", mm)
        self.assertEqual(len(slots_full_ls), 3)

        slots_full_pt = _compute_layout_slots(a4_h, a4_w, "full", 7, "portrait", mm)
        self.assertEqual(len(slots_full_pt), 4)

        slots_full_15 = _compute_layout_slots(a4_w, a4_h, "full", 15, "landscape", mm)
        self.assertEqual(len(slots_full_15), 1)

        # Product only mode
        slots_prod_ls = _compute_layout_slots(a4_w, a4_h, "product_only", 7, "landscape", mm)
        self.assertEqual(len(slots_prod_ls), 4)
        # Verify 3 unrotated and 1 rotated 90 degrees
        unrotated_prod = [s for s in slots_prod_ls if not s.rotated]
        rotated_prod = [s for s in slots_prod_ls if s.rotated]
        self.assertEqual(len(unrotated_prod), 3)
        self.assertEqual(len(rotated_prod), 1)

        slots_prod_pt = _compute_layout_slots(a4_h, a4_w, "product_only", 7, "portrait", mm)
        self.assertEqual(len(slots_prod_pt), 4)

        slots_prod_15 = _compute_layout_slots(a4_w, a4_h, "product_only", 15, "landscape", mm)
        self.assertEqual(len(slots_prod_15), 1)

        # Location only mode
        slots_loc_ls = _compute_layout_slots(a4_w, a4_h, "location_only", 7, "landscape", mm)
        self.assertEqual(len(slots_loc_ls), 9)

        slots_loc_pt = _compute_layout_slots(a4_h, a4_w, "location_only", 7, "portrait", mm)
        self.assertEqual(len(slots_loc_pt), 9)
        self.assertTrue(all(s.rotated for s in slots_loc_pt))

        slots_loc_15_ls = _compute_layout_slots(a4_w, a4_h, "location_only", 15, "landscape", mm)
        self.assertEqual(len(slots_loc_15_ls), 3)

        slots_loc_15_pt = _compute_layout_slots(a4_h, a4_w, "location_only", 15, "portrait", mm)
        self.assertEqual(len(slots_loc_15_pt), 3)

    def test_slots_fit_within_page_bounds(self):
        mm = 72.0 / 25.4
        for print_mode in ["full", "product_only", "location_only"]:
            for h in [7, 15]:
                for ori, (pw, ph) in [("landscape", (297.0 * mm, 210.0 * mm)), ("portrait", (210.0 * mm, 297.0 * mm))]:
                    slots = _compute_layout_slots(pw, ph, print_mode, h, ori, mm)
                    for idx, s in enumerate(slots):
                        slot_w = s.h if s.rotated else s.w
                        slot_h = s.w if s.rotated else s.h
                        self.assertGreaterEqual(s.x, -0.01, f"Slot {idx} x < 0 in {print_mode} {ori} {h}cm")
                        self.assertGreaterEqual(s.y, -0.01, f"Slot {idx} y < 0 in {print_mode} {ori} {h}cm")
                        self.assertLessEqual(s.x + slot_w, pw + 0.01, f"Slot {idx} right > page_w in {print_mode} {ori} {h}cm")
                        self.assertLessEqual(s.y + slot_h, ph + 0.01, f"Slot {idx} top > page_h in {print_mode} {ori} {h}cm")

    def test_render_pdf_all_modes(self):
        cells = [
            Cell(
                shelf_id=1,
                slot_id=i,
                row_number=1,
                slot_number=i,
                location_id=f"L1-1A1-{i}",
                products=(Product(f"PID-{i}01", f"Test Product Name {i}"),) if i % 2 == 0 else (),
            )
            for i in range(1, 11)
        ]
        test_dir = Path(__file__).resolve().parent / "temp_test_pdf"
        test_dir.mkdir(exist_ok=True)
        try:
            for mode in ["full", "product_only", "location_only"]:
                out = test_dir / f"test_{mode}.pdf"
                res = render_labels_pdf(cells, out, label_height_cm=7, orientation="landscape", print_mode=mode)
                self.assertTrue(out.is_file())
                self.assertEqual(res.cells, 10)
                self.assertEqual(res.labels, 10)
                if mode == "full":
                    self.assertEqual(res.pages, 4)
                elif mode == "product_only":
                    self.assertEqual(res.pages, 3)
                elif mode == "location_only":
                    self.assertEqual(res.pages, 2)
                out.unlink()
        finally:
            if test_dir.is_dir():
                test_dir.rmdir()

    def test_print_file_time_regex(self):
        filenames = [
            "warehouse_labels_7cm_20260918_120000_123456.pdf",
            "warehouse_labels_7cm_landscape_20260918_120000_123456.pdf",
            "warehouse_labels_7cm_portrait_20260918_120000_123456.pdf",
            "warehouse_labels_location_only_7cm_landscape_20260918_120000_123456.pdf",
            "warehouse_labels_product_only_7cm_landscape_20260918_120000_123456.pdf",
        ]
        for name in filenames:
            match = _PRINT_FILE_TIME.search(name)
            self.assertIsNotNone(match, f"Regex failed to match: {name}")
            self.assertEqual(len(match.groups()), 3)


if __name__ == "__main__":
    unittest.main()

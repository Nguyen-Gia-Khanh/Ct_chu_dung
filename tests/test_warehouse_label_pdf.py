"""Tests for warehouse label PDF layout and rendering features."""

from pathlib import Path
import re
import unittest

from utils.labels.pdf import (
    Cell,
    Product,
    _compute_layout_slots,
    render_labels_pdf,
)
from utils.labels.app import _PRINT_FILE_TIME


class TestWarehouseLabelPdf(unittest.TestCase):
    def test_compute_layout_slots_counts(self):
        mm = 72.0 / 25.4
        a4_w, a4_h = 297.0 * mm, 210.0 * mm

        # 7cm tests
        self.assertEqual(len(_compute_layout_slots(a4_w, a4_h, "full", 7, "landscape", mm)), 3)
        self.assertEqual(len(_compute_layout_slots(a4_h, a4_w, "full", 7, "portrait", mm)), 4)
        self.assertEqual(len(_compute_layout_slots(a4_w, a4_h, "product_only", 7, "landscape", mm)), 4)
        self.assertEqual(len(_compute_layout_slots(a4_h, a4_w, "product_only", 7, "portrait", mm)), 6)
        self.assertEqual(len(_compute_layout_slots(a4_w, a4_h, "location_only", 7, "landscape", mm)), 9)
        self.assertEqual(len(_compute_layout_slots(a4_h, a4_w, "location_only", 7, "portrait", mm)), 9)

        # 4cm tests
        self.assertEqual(len(_compute_layout_slots(a4_w, a4_h, "full", 4, "landscape", mm)), 5)
        self.assertEqual(len(_compute_layout_slots(a4_h, a4_w, "full", 4, "portrait", mm)), 7)
        self.assertEqual(len(_compute_layout_slots(a4_w, a4_h, "product_only", 4, "landscape", mm)), 7)
        self.assertEqual(len(_compute_layout_slots(a4_h, a4_w, "product_only", 4, "portrait", mm)), 11)
        self.assertEqual(len(_compute_layout_slots(a4_w, a4_h, "location_only", 4, "landscape", mm)), 17)
        self.assertEqual(len(_compute_layout_slots(a4_h, a4_w, "location_only", 4, "portrait", mm)), 17)

        # 14.5cm tests
        self.assertEqual(len(_compute_layout_slots(a4_w, a4_h, "full", 14.5, "landscape", mm)), 1)
        self.assertEqual(len(_compute_layout_slots(a4_h, a4_w, "full", 14.5, "portrait", mm)), 2)
        self.assertEqual(len(_compute_layout_slots(a4_w, a4_h, "product_only", 14.5, "landscape", mm)), 2)
        self.assertEqual(len(_compute_layout_slots(a4_h, a4_w, "product_only", 14.5, "portrait", mm)), 2)
        self.assertEqual(len(_compute_layout_slots(a4_w, a4_h, "location_only", 14.5, "landscape", mm)), 4)
        self.assertEqual(len(_compute_layout_slots(a4_h, a4_w, "location_only", 14.5, "portrait", mm)), 4)

    def test_slots_fit_within_page_bounds_and_no_overlap(self):
        mm = 72.0 / 25.4
        for print_mode in ["full", "product_only", "location_only"]:
            for h in [4, 7, 14.5]:
                for ori, (pw, ph) in [("landscape", (297.0 * mm, 210.0 * mm)), ("portrait", (210.0 * mm, 297.0 * mm))]:
                    slots = _compute_layout_slots(pw, ph, print_mode, h, ori, mm)
                    boxes = []
                    for idx, s in enumerate(slots):
                        slot_w = s.h if s.rotated else s.w
                        slot_h = s.w if s.rotated else s.h
                        self.assertGreaterEqual(s.x, -0.01, f"Slot {idx} x < 0 in {print_mode} {ori} {h}cm")
                        self.assertGreaterEqual(s.y, -0.01, f"Slot {idx} y < 0 in {print_mode} {ori} {h}cm")
                        self.assertLessEqual(s.x + slot_w, pw + 0.01, f"Slot {idx} right > page_w in {print_mode} {ori} {h}cm")
                        self.assertLessEqual(s.y + slot_h, ph + 0.01, f"Slot {idx} top > page_h in {print_mode} {ori} {h}cm")
                        boxes.append((s.x, s.y, s.x + slot_w, s.y + slot_h))

                    # Non-overlap check between any two slots
                    for i in range(len(boxes)):
                        for j in range(i + 1, len(boxes)):
                            overlap = not (
                                boxes[i][2] <= boxes[j][0] + 0.01 or
                                boxes[j][2] <= boxes[i][0] + 0.01 or
                                boxes[i][3] <= boxes[j][1] + 0.01 or
                                boxes[j][3] <= boxes[i][1] + 0.01
                            )
                            self.assertFalse(
                                overlap,
                                f"Overlap between slots {i} and {j} in {print_mode} {ori} {h}cm: {boxes[i]} vs {boxes[j]}"
                            )

    def test_render_pdf_all_modes_and_sizes(self):
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
            for size in [4, 7, 14.5]:
                for mode in ["full", "product_only", "location_only"]:
                    out = test_dir / f"test_{size}_{mode}.pdf"
                    res = render_labels_pdf(cells, out, label_height_cm=size, orientation="landscape", print_mode=mode)
                    self.assertTrue(out.is_file())
                    self.assertEqual(res.cells, 10)
                    self.assertEqual(res.labels, 10)
                    out.unlink()
        finally:
            if test_dir.is_dir():
                test_dir.rmdir()

    def test_print_file_time_regex(self):
        filenames = [
            "warehouse_labels_4cm_20260925_120000_123456.pdf",
            "warehouse_labels_7cm_20260918_120000_123456.pdf",
            "warehouse_labels_14.5cm_portrait_20260925_120000_123456.pdf",
            "warehouse_labels_15cm_20260918_120000_123456.pdf",
            "warehouse_labels_location_only_4cm_landscape_20260925_120000_123456.pdf",
            "warehouse_labels_product_only_14.5cm_portrait_20260925_120000_123456.pdf",
        ]
        for name in filenames:
            match = _PRINT_FILE_TIME.search(name)
            self.assertIsNotNone(match, f"Regex failed to match: {name}")
            self.assertEqual(len(match.groups()), 3)
            # Verify datetime parsing works with groups
            dt_str = "".join(match.groups())
            self.assertEqual(len(dt_str), 20)  # YYYYMMDDHHMMSSffffff


if __name__ == "__main__":
    unittest.main()

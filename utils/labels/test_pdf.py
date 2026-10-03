"""Run with python -m unittest utils.labels.test_pdf."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pypdf import PdfReader

from utils.labels.pdf import Cell, Product, _split_location_id, render_labels_pdf


class LargeLabelLayoutTests(unittest.TestCase):
    def test_location_segments(self):
        for location, expected in (
            ("L1-1A1-3", ("L1-1", "A1-3")),
            ("L12-10A12-30", ("L12-10", "A12-30")),
            (" L2-3-A1-4 ", ("L2-3", "-A1-4")),
            ("Custom location", ("Custom location", "")),
        ):
            self.assertEqual(_split_location_id(location), expected)

    def test_rendered_header_products_and_other_heights(self):
        cell = Cell(1, 1, 1, 3, "L1-1A1-3", (Product("P01", "Pen"),))
        with TemporaryDirectory(dir=Path(__file__).parent) as folder:
            for height in (3, 7, 14.5):
                for orientation in ("portrait", "landscape"):
                    with self.subTest(height=height, orientation=orientation):
                        path = Path(folder) / "labels.pdf"
                        result = render_labels_pdf(
                            [cell], path, label_height_cm=height, orientation=orientation
                        )
                        self.assertEqual((result.labels, result.pages), (1, 1))
                        text = {}

                        def collect(value, cm, tm, font, size):
                            if value.strip():
                                text[value.strip()] = (cm[4] + tm[4], cm[5] + tm[5], size)

                        PdfReader(path).pages[0].extract_text(visitor_text=collect)
                        prefix, suffix = text["L1-1"], text["A1-3"]
                        if height == 14.5:
                            self.assertLess(prefix[0], suffix[0])
                            self.assertAlmostEqual(prefix[1], suffix[1])
                            self.assertGreater(prefix[1], text["P01"][1])
                            self.assertGreater(prefix[2], 72)
                            self.assertLessEqual(prefix[2], 144)
                            self.assertEqual(text["P01"][2], 64)
                        else:
                            self.assertLess(prefix[0], text["P01"][0])
                            self.assertLess(suffix[0], text["P01"][0])
                            self.assertGreater(prefix[1], suffix[1])

    def test_names_modes_pagination_and_safe_failure(self):
        long_name = "Vietnamese product with a very long descriptive name"
        cells = [
            Cell(1, i, 1, i, f"L1-1A1-{i}", (Product(f"PID-{i}", long_name),))
            for i in range(1, 4)
        ]
        with TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path = Path(folder) / "labels.pdf"
            for mode in ("full", "product_only", "location_only"):
                for limit in (True, False):
                    with self.subTest(mode=mode, limit=limit):
                        result = render_labels_pdf(
                            cells, path, label_height_cm=14.5, orientation="portrait",
                            print_mode=mode, limit_to_30_characters=limit,
                        )
                        pages = PdfReader(path).pages
                        self.assertEqual(result.pages, len(pages))
                        text = "\n".join(page.extract_text() for page in pages)
                        if mode != "location_only":
                            expected = long_name[:30] + "..." if limit else long_name
                            self.assertIn(expected, text)
                        if mode == "full":
                            self.assertEqual(result.pages, 2)

            previous = path.read_bytes()
            invalid = Cell(1, 1, 1, 1, "L1-1" + "W" * 500)
            with self.assertRaisesRegex(ValueError, "Location ID"):
                render_labels_pdf([invalid], path, label_height_cm=14.5)
            self.assertEqual(path.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()

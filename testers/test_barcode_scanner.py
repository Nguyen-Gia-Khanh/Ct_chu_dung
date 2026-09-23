"""Unit tests for barcode scanner product ID formatting (5-3-any format)."""

import unittest
from utils.barcode_scanner import format_product_id


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


if __name__ == "__main__":
    unittest.main()

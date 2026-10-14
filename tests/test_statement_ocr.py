"""Check automatic photo layout, wrapped rows, and text-safe Excel output."""

from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from openpyxl import load_workbook
from PIL import Image, ImageDraw

from tests.support import WorkspaceTestCase
from utils.ocr_work import statement_ocr
from utils.ocr_work.statement_ocr import COLUMNS, assemble, detect_rows, detect_table, discover_images, extract, write_excel


class StatementOCRTests(WorkspaceTestCase):
    def test_manual_run_uses_local_ocr_environment_without_options(self):
        script = Path(__file__).resolve().parents[1] / "utils" / "ocr_work" / "statement_ocr.py"
        interpreter = script.parents[2] / ".venv-ocr" / "Scripts" / "python.exe"
        with patch.object(sys, "executable", "other-python.exe"), patch.object(Path, "is_file", return_value=True):
            with patch("subprocess.call", return_value=0) as launch:
                with self.assertRaises(SystemExit) as stopped:
                    runpy.run_path(str(script), run_name="__main__")
                self.assertEqual(stopped.exception.code, 0)
                launch.assert_called_once_with([str(interpreter), str(script)])

    def test_each_photo_detects_its_own_perspective_and_columns(self):
        image = Image.new("RGB", (900, 800), "white")
        draw = ImageDraw.Draw(image)
        dividers = [30, 70, 145, 220, 400, 640, 715, 790, 870]
        for x in dividers:
            # Broken rules like the photographed statements, without row lines.
            for y in range(60, 420 if x in (220, 400, 640) else 740, 80):
                draw.line((x, y, x, y + 64), fill="black", width=3)
        source = np.float32([[0, 0], [899, 0], [899, 799], [0, 799]])
        for corners in (source, np.float32([[60, 80], [960, 40], [930, 870], [25, 800]])):
            matrix = cv2.getPerspectiveTransform(source, corners)
            photo = Image.fromarray(cv2.warpPerspective(np.asarray(image), matrix, (1000, 920), borderValue=(255, 255, 255)))
            table, layout = detect_table(photo)
            self.assertEqual(len(layout["columns"]), 9)
            proportions = np.array(layout["columns"]) / table.width
            np.testing.assert_allclose(proportions, (np.array(dividers) - 30) / 840, atol=0.015)
        with self.assertRaisesRegex(ValueError, "column boundaries"):
            detect_table(Image.new("RGB", (900, 800), "white"))

    def test_template_recovers_internal_divider_but_rejects_another_form(self):
        fractions = statement_ocr.COLUMN_FRACTIONS
        image = Image.new("RGB", (1100, 900), "white")
        draw = ImageDraw.Draw(image)
        for index, fraction in enumerate(fractions):
            if index != 4:
                x = 40 + round(fraction * 1000)
                draw.line((x, 70, x, 820), fill="black", width=3)
        source = np.float32([[0, 0], [1099, 0], [1099, 899], [0, 899]])
        target = np.float32([[80, 80], [1160, 35], [1120, 1010], [30, 950]])
        photo = Image.fromarray(cv2.warpPerspective(np.asarray(image), cv2.getPerspectiveTransform(source, target),
                                                   (1200, 1050), borderValue=(255, 255, 255)))
        table, layout = detect_table(photo, fractions)
        self.assertEqual(layout["inferred_columns"], [3, 4])
        np.testing.assert_allclose(np.array(layout["columns"]) / table.width, fractions, atol=0.006)
        table, layout = statement_ocr.normalize_table(table, layout)
        self.assertEqual(table.width, statement_ocr.MIN_TABLE_WIDTH)
        self.assertEqual(layout["columns"], [round(f * table.width) for f in fractions])
        wrong_form = Image.new("RGB", (1100, 900), "white")
        draw = ImageDraw.Draw(wrong_form)
        for x in range(40, 1041, 125):
            draw.line((x, 70, x, 820), fill="black", width=3)
        with self.assertRaisesRegex(ValueError, "column template"):
            detect_table(wrong_form, fractions)
        for missing in (0, 8):
            cropped = Image.new("RGB", (1100, 900), "white")
            draw = ImageDraw.Draw(cropped)
            for index, fraction in enumerate(fractions):
                if index != missing:
                    x = 40 + round(fraction * 1000)
                    draw.line((x, 70, x, 820), fill="black", width=3)
            with self.assertRaisesRegex(ValueError, "column template"):
                detect_table(cropped, fractions)

    def test_whole_paper_unwarping_recovers_bad_geometry_and_keeps_color(self):
        distant = Image.new("RGB", (1200, 1200), "#333366")
        ImageDraw.Draw(distant).rectangle((320, 250, 850, 850), fill="white")
        paper = statement_ocr.crop_document(distant)
        self.assertLess(paper.width, 700)
        self.assertGreater(paper.width, 530)  # Retain the complete paper plus a margin.
        original = Image.new("RGB", (1100, 900), "#333366")
        ImageDraw.Draw(original).rectangle((40, 40, 1060, 860), fill="white")
        path = self.folder / "curved.jpg"
        original.save(path)
        corrected = original.copy()
        draw = ImageDraw.Draw(corrected)
        for fraction in statement_ocr.COLUMN_FRACTIONS:
            x = 60 + round(fraction * 980)
            draw.line((x, 70, x, 820), fill="black", width=3)
        draw.rectangle((650, 400, 700, 450), fill="red")
        received = []

        class FakeUnwarper:
            def predict(self, pixels):
                received.append(pixels)
                return [{"doctr_img": np.asarray(corrected)[:, :, ::-1].copy()}]

        table, layout = statement_ocr.prepare_table(path, FakeUnwarper())
        self.assertEqual(len(received), 1)  # One complete paper, never individual OCR columns.
        self.assertGreater(received[0].shape[1], 900)
        self.assertGreater(received[0].shape[0], 750)
        pixels = np.asarray(table)
        self.assertGreater(np.sum((pixels[:, :, 0] > 200) & (pixels[:, :, 1] < 40) & (pixels[:, :, 2] < 40)), 100)
        self.assertEqual(len(layout["columns"]), 9)
        # A learned model can damage good geometry; reject that result and keep the readable grid.
        corrected.save(path)
        expected, _ = statement_ocr.prepare_table(path)
        class BadUnwarper:
            def predict(self, pixels):
                return [{"doctr_img": np.full((900, 1100, 3), 255, dtype=np.uint8)}]
        retained, _ = statement_ocr.prepare_table(path, BadUnwarper())
        np.testing.assert_array_equal(np.asarray(expected), np.asarray(retained))

    def test_native_digit_crops_stay_in_the_correct_rescaled_rows(self):
        table = Image.new("RGB", (800, 180), "white")
        draw = ImageDraw.Draw(table)
        for top in (10, 110):
            draw.rectangle((6, top, 20, top + 11), fill="black")
        layout = {"columns": [round(f * table.width) for f in statement_ocr.COLUMN_FRACTIONS]}
        scaled, layout = statement_ocr.normalize_table(table, layout)
        layout["rows"] = [0, 180, 360]
        received = []
        class Recognizer:
            def predict(self, crops, batch_size):
                received.extend(crops)
                return [{"rec_text": "001", "rec_score": 0.99}, {"rec_text": "002", "rec_score": 0.99}]
        tokens = statement_ocr.read_index_tokens(scaled, layout, Recognizer())
        self.assertEqual([crop.shape[:2] for crop in received], [(14, 17), (14, 17)])
        # Source glyphs remain 12 pixels tall, while boxes map into the 360-pixel output.
        self.assertLess(tokens[0]["box"][3], 180)
        self.assertGreater(tokens[1]["box"][1], 180)
        result = assemble([tokens, *[[] for _ in COLUMNS[1:]]], layout["rows"], 0.8)
        self.assertEqual([row["index"] for row in result["rows"]], ["001", "002"])
        heights = []
        class OCR:
            def predict(self, pixels):
                column = len(heights) + 1
                heights.append(pixels.shape[0])
                values = {1: ["17/06/2025 09:00", "17/06/2025 10:00"],
                          2: ["17/06/2025", "17/06/2025"], 3: ["0001", "0002"],
                          4: ["first", "second"], 5: ["1,000", ""],
                          6: ["", "2,000"], 7: ["5,000", "7,000"]}[column]
                factor = 1 if column >= 5 else 2
                nonempty = [(text, top) for text, top in zip(values, (10, 110)) if text]
                return [{"rec_texts": [text for text, _ in nonempty],
                         "rec_scores": [0.99 for _ in nonempty],
                         "rec_boxes": [[12, top * factor + 12, 35, (top + 12) * factor + 12]
                                       for _, top in nonempty]}]
        extracted = extract(scaled, layout, 0.8, OCR(), Recognizer())
        self.assertEqual(heights, [384, 384, 384, 384, 204, 204, 204])
        self.assertEqual(extracted["rows"][0]["money_out"], "1,000")
        self.assertEqual(extracted["rows"][1]["money_in"], "2,000")
        self.assertEqual([row["total_raw"] for row in extracted["rows"]], ["5,000", "7,000"])

    def test_wrapped_rows_missing_index_and_excel_text_are_preserved(self):
        def token(text, top, bottom=None, score=0.99):
            return {"text": text, "score": score, "box": [2, top, 25, bottom or top + 12]}

        columns = [[token("001", 10), token("003", 135)],
                   [token("17/06/2025 09:17:14", 10, 38), token("17/06/2025", 95), token("18/06/2025", 135)],
                   [token("17/06/2025", 11), token("17/06/2025", 96), token("18/06/2025", 136)],
                   [token("000123", 10)],
                   [token("first", 10), token("wrapped", 65), token("=formula", 95)],
                   [], [token("1,000,000", 10, score=0.65)], [token("9,001,042", 10)]]
        rows = detect_rows(columns, 180)
        result = assemble(columns, rows, 0.9)
        self.assertEqual(len(result["rows"]), 3)
        self.assertEqual(result["rows"][0]["content"], "first wrapped")
        self.assertEqual(result["rows"][1]["index"], "")
        self.assertEqual(result["rows"][1]["content"], "=formula")
        self.assertTrue(any(issue["issue"] == "low_confidence" for issue in result["issues"]))
        def prediction(tokens):
            return {"rec_texts": [t["text"] for t in tokens],
                    "rec_scores": [t["score"] for t in tokens],
                    "rec_boxes": [[12, t["box"][1] + 12, 35, t["box"][3] + 12] for t in tokens]}

        predictions = [prediction(tokens) for tokens in columns[1:]]
        crop_sizes = []

        class FakeOCR:
            def predict(self, crop):
                crop_sizes.append(crop.shape[:2])
                return [predictions.pop(0)]

        class FakeNumberRecognizer:
            def predict(self, crops, batch_size):
                self_test.assertEqual(len(crops), 2)  # Blank index cell does not generate a guess.
                self_test.assertTrue(all(crop.shape[0] < 30 for crop in crops))
                return [{"rec_text": "001", "rec_score": 0.99}, {"rec_text": "003", "rec_score": 0.99}]

        self_test = self
        layout = {"columns": [0, 40, 120, 200, 340, 550, 640, 730, 820]}
        table = Image.new("RGB", (820, 180), "white")
        ink = ImageDraw.Draw(table)
        ink.rectangle((4, 10, 20, 21), fill="black")
        ink.rectangle((4, 135, 20, 146), fill="black")
        extracted = extract(table, layout, 0.9, FakeOCR(), FakeNumberRecognizer())
        self.assertEqual(extracted["rows"], result["rows"])
        self.assertEqual(len(crop_sizes), 7)
        layout["inferred_columns"] = [3, 4]
        predictions.extend(prediction(tokens) for tokens in columns[1:])
        inferred = extract(table, layout, 0.9, FakeOCR(), FakeNumberRecognizer())
        self.assertEqual([(issue["row"], issue["column"]) for issue in inferred["issues"]
                          if issue["issue"] == "column_boundary_inferred"],
                         [(row, name) for row in range(1, 4) for name in ("id", "content")])
        with self.assertRaisesRegex(ValueError, "No transaction"):
            detect_rows([[] for _ in COLUMNS], 180)
        folder = self.folder
        for name in ("page10.png", "page2.JPG", "readme.txt"):
            (folder / name).touch()
        self.assertEqual([path.name for path in discover_images(folder)], ["page2.JPG", "page10.png"])
        result["source"] = "page2.JPG"
        output = folder / "result.xlsx"
        write_excel(output, [result], [{"source_file": "bad.jpg", "error": "Unreadable image"}])
        workbook = load_workbook(output)
        try:
            self.assertEqual(workbook.sheetnames, ["Data"])
            self.assertEqual(workbook["Data"].max_column, 9)
            self.assertEqual(workbook["Data"]["I1"].value, "flagged")
            self.assertEqual(workbook["Data"]["D2"].value, "000123")
            self.assertEqual(workbook["Data"]["E3"].value, "=formula")
            self.assertEqual(workbook["Data"]["E3"].data_type, "s")
            self.assertIsNone(workbook["Data"]["F2"].value)
            self.assertIn("money_in: low confidence 0.65 < 0.90", workbook["Data"]["I2"].value)
            self.assertIn("missing or non numeric index", workbook["Data"]["I3"].value)
            self.assertEqual(workbook["Data"]["G2"].fill.fgColor.rgb, "00F4CCCC")
            self.assertEqual(workbook["Data"]["A3"].fill.fgColor.rgb, "00F4CCCC")
            self.assertEqual(workbook["Data"]["D2"].fill.fill_type, None)
            self.assertEqual(workbook["Data"]["F2"].fill.fill_type, None)
            self.assertEqual(workbook["Data"]["I2"].fill.fgColor.rgb, "00FFF2CC")
            self.assertEqual(workbook["Data"]["I5"].value, "bad.jpg: Unreadable image")
            self.assertEqual(workbook["Data"].auto_filter.ref, "A1:I5")
        finally:
            workbook.close()
        with self.assertRaises(FileExistsError):
            write_excel(output, [result], [])

    def test_amount_conflicts_and_index_gaps_highlight_only_affected_cells(self):
        def token(text, top):
            return {"text": text, "score": 0.99, "box": [2, top, 25, top + 12]}

        columns = [[token(text, 10), token(text, 50)] for text in
                   ("001", "09:17:14", "17/06/2025", "000123", "description", "", "", "9,000")]
        columns[0][1]["text"] = "003"
        columns[5] = [token("1,000", 50)]
        columns[6] = [token("2,000", 50)]
        result = assemble(columns, [0, 40, 80], 0.8)
        result["source"] = "page1.jpg"
        path = self.folder / "conflicts.xlsx"
        # A second photo verifies issue row numbers are local to each photo.
        write_excel(path, [{"source": "clean.jpg", "rows": [result["rows"][1]], "issues": []}, result])
        workbook = load_workbook(path)
        try:
            sheet = workbook["Data"]
            pink_cells = {cell.coordinate for row in sheet.iter_rows(min_row=2) for cell in row
                          if cell.fill.fgColor.rgb == "00F4CCCC"}
            self.assertEqual(pink_cells, {"F3", "G3", "A4", "F4", "G4"})
            self.assertIsNone(sheet["I2"].value)
            self.assertIn("no amount detected", sheet["I3"].value)
            self.assertIn("both amount columns populated", sheet["I4"].value)
            self.assertIn("index gap or duplicate", sheet["I4"].value)
        finally:
            workbook.close()

    def test_confidence_cutoff_ignores_small_weak_fragments(self):
        columns = [[{"text": text, "score": 0.99, "box": [2, 10, 25, 22]}] for text in
                   ("001", "09:17:14", "17/06/2025", "000123", "long readable description", "", "1,000", "9,000")]
        columns[5] = []  # A blank outgoing amount is valid when incoming has a value.
        columns[4][0]["score"] = 0.95
        columns[4].append({"text": ".", "score": 0.2, "box": [26, 10, 30, 22]})
        for score in (0.85, 0.80, 0.79):
            columns[6][0]["score"] = score
            result = assemble(columns, [0, 40], 0.80)
            self.assertGreater(result["confidence"][0]["content"], 0.90)
            self.assertEqual([issue["column"] for issue in result["issues"]], ["money_in"] if score < 0.8 else [])
        columns[6][0]["score"] = 0.99
        columns[3] = []
        self.assertEqual(assemble(columns, [0, 40], 0.8)["issues"],
                         [{"row": 1, "column": "id", "issue": "no_text_detected"}])
        columns[3] = [{"text": "000123", "score": 0.99, "box": [2, 10, 25, 22]}]
        columns[6][0]["text"] = "1,00J"
        result = assemble(columns, [0, 40], 0.8)
        self.assertEqual(result["issues"], [{"row": 1, "column": "money_in", "issue": "non_numeric_amount"}])
        self.assertEqual(result["rows"][0]["money_in"], "1,00J")
        result["source"] = "page.jpg"
        path = self.folder / "non_numeric.xlsx"
        write_excel(path, [result])
        book = load_workbook(path)
        try:
            self.assertEqual(book.active["G2"].fill.fgColor.rgb, "00F4CCCC")
            self.assertIn("money_in: non numeric amount", book.active["I2"].value)
        finally:
            book.close()

    def test_batch_writes_only_one_workbook_and_keeps_failures_visible(self):
        folder = self.folder
        images = folder / "images"
        images.mkdir()
        for name in ("page1.png", "page2.png"):
            (images / name).touch()
        result = {"rows": [dict.fromkeys(COLUMNS, "001")], "issues": []}
        with patch.multiple(statement_ocr, SCRIPT_DIR=folder, IMAGE_FOLDER="images", OUTPUT_FILENAME="result.xlsx"):
            with patch.object(statement_ocr, "create_ocr", return_value=(None, None, None)), patch.object(statement_ocr, "prepare_table", return_value=(None, {})):
                with patch.object(statement_ocr, "extract", side_effect=[ValueError("Unreadable image"), result]):
                    statement_ocr.main()
        self.assertEqual(sorted(path.name for path in folder.iterdir()), ["images", "result.xlsx"])
        workbook = load_workbook(folder / "result.xlsx")
        try:
            self.assertEqual(workbook.sheetnames, ["Data"])
            self.assertIsNone(workbook["Data"]["I2"].value)
            self.assertEqual(workbook["Data"]["I3"].value, "page1.png: Failed: Unreadable image")
        finally:
            workbook.close()


if __name__ == "__main__":
    unittest.main()

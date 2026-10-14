"""Statement OCR Pipeline for Google Colab.

Reads bank statement photos from a Google Drive folder, performs table detection,
perspective correction, and OCR extraction using PaddleOCR (PP-OCRv6), then exports
all records directly to Google Sheets with conditional formatting for review.
"""

import bisect
from datetime import datetime
import os
from pathlib import Path
import re
import statistics
import sys
from uuid import uuid4
import cv2
import numpy as np
from PIL import Image, ImageOps

COLUMNS = ("index", "time", "date", "id", "content", "money_out", "money_in", "total_raw")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def discover_images(folder):
    """Find and sort image files naturally by number/name."""
    def natural_key(path):
        return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                     for part in re.split(r"(\d+)", path.name))
    return sorted((p for p in folder.iterdir()
                   if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in IMAGE_SUFFIXES),
                  key=natural_key)


def validate_edges(edges, extent, expected=None):
    if expected is not None and len(edges) != expected:
        raise ValueError(f"Expected {expected} boundaries, got {len(edges)}")
    if len(edges) < 2 or edges[0] != 0 or edges[-1] != extent:
        raise ValueError("Boundaries must span the entire rectified table")
    if any(b - a < 3 for a, b in zip(edges, edges[1:])):
        raise ValueError("Boundaries must be increasing and at least three pixels apart")


def assemble(column_results, row_edges, min_confidence):
    """Group OCR tokens into detected rows and flag potential issues."""
    cells = [[[] for _ in COLUMNS] for _ in range(len(row_edges) - 1)]
    issues = []
    for column, tokens in enumerate(column_results):
        for token in tokens:
            x0, y0, x1, y1 = token["box"]
            row = bisect.bisect_right(row_edges, (y0 + y1) / 2) - 1
            if not 0 <= row < len(cells):
                issues.append({"column": COLUMNS[column], "issue": "outside_rows", "token": token})
                continue
            cells[row][column].append(token)
            margin = max(2, (y1 - y0) * 0.15)
            if y0 < row_edges[row] - margin or y1 > row_edges[row + 1] + margin:
                issues.append({"row": row + 1, "column": COLUMNS[column], "issue": "box_crosses_row", "token": token})

    records, confidence = [], []
    for row_number, row in enumerate(cells, 1):
        record, scores = {}, {}
        for name, tokens in zip(COLUMNS, row):
            tokens.sort(key=lambda t: (round(t["box"][1] / 5), t["box"][0]))
            record[name] = " ".join(t["text"] for t in tokens).strip()
            characters = sum(len(t["text"].strip()) for t in tokens)
            scores[name] = sum(t["score"] * len(t["text"].strip()) for t in tokens) / characters if characters else None
            if scores[name] is not None and scores[name] < min_confidence:
                issues.append({"row": row_number, "column": name, "issue": "low_confidence",
                               "score": scores[name], "threshold": min_confidence})
        if not record["index"].isdigit():
            issues.append({"row": row_number, "column": "index", "issue": "missing_or_non_numeric_index"})
        for name in ("time", "date", "id", "content", "total_raw"):
            if not record[name]:
                issues.append({"row": row_number, "column": name, "issue": "no_text_detected"})
        if not record["money_out"] and not record["money_in"]:
            issues.append({"row": row_number, "issue": "no_amount_detected"})
        if record["money_out"] and record["money_in"]:
            issues.append({"row": row_number, "issue": "both_amount_columns_populated"})
        records.append(record)
        confidence.append(scores)

    indices = [int(r["index"]) if r["index"].isdigit() else None for r in records]
    for row, (previous, current) in enumerate(zip(indices, indices[1:]), 2):
        if previous is not None and current is not None and current != previous + 1:
            issues.append({"row": row, "issue": "index_gap_or_duplicate", "previous": previous, "current": current})
    return {"rows": records, "confidence": confidence, "issues": issues}


def rectify(image, corners):
    """Correct perspective distortion of the detected table region."""
    points = np.asarray(corners, dtype=np.float32)
    if points.shape != (4, 2) or not cv2.isContourConvex(points.astype(np.int32)):
        raise ValueError("Could not determine a convex table outline")
    width = round(max(np.linalg.norm(points[1] - points[0]), np.linalg.norm(points[2] - points[3])))
    height = round(max(np.linalg.norm(points[3] - points[0]), np.linalg.norm(points[2] - points[1])))
    if min(width, height) < 30:
        raise ValueError("Detected table is too small")
    target = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    matrix = cv2.getPerspectiveTransform(points, target)
    return Image.fromarray(cv2.warpPerspective(np.asarray(image), matrix, (width, height)))


def detect_table(image):
    """Find table's 9 vertical column dividers and compute corners."""
    scale = min(1, 1200 / max(image.size))
    photo = cv2.resize(np.asarray(image), (round(image.width * scale), round(image.height * scale)))
    height, width = photo.shape[:2]
    gray = cv2.cvtColor(photo, cv2.COLOR_RGB2GRAY)
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 31, 10)
    binary[cv2.cvtColor(photo, cv2.COLOR_RGB2HSV)[:, :, 1] > 80] = 0
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                             np.ones((max(5, height // 80), 1), np.uint8))
    lines = cv2.HoughLinesP(binary, 1, np.pi / 720, threshold=max(20, height // 27),
                           minLineLength=height // 10, maxLineGap=height // 30)
    candidates = []
    for x0, y0, x1, y1 in (() if lines is None else lines.reshape(-1, 4)):
        if abs(y1 - y0) > height * 0.15 and abs(x1 - x0) < abs(y1 - y0) * 0.25:
            middle = x0 + (height / 2 - y0) * (x1 - x0) / (y1 - y0)
            candidates.append((middle, (x0, y0, x1, y1)))
    groups = []
    for middle, line in sorted(candidates):
        if not groups or middle - statistics.mean(item[0] for item in groups[-1]) > max(3, width * 0.008):
            groups.append([])
        groups[-1].append((middle, line))
    if len(groups) != 9:
        raise ValueError(f"Found {len(groups)} column boundaries; expected 9 for this eight-column statement. "
                         "Use a clearer photo showing all the vertical dividers.")
    rules, tops, bottoms = [], [], []
    for group in groups:
        points = np.array([(x, y) for _, (x0, y0, x1, y1) in group
                           for x, y in ((x0, y0), (x1, y1))], dtype=float)
        rules.append(np.polyfit(points[:, 1], points[:, 0], 1))
        tops.append(float(points[:, 1].min()))
        bottoms.append(float(points[:, 1].max()))
    middle_x = np.array([np.polyval(rule, height / 2) for rule in rules])

    def horizontal_edge(ends, padding):
        ends = np.array(ends)
        best, valid = (-1, float("-inf")), None
        for left in range(8):
            for right in range(left + 1, 9):
                edge = np.polyfit(middle_x[[left, right]], ends[[left, right]], 1)
                residual = np.abs(np.polyval(edge, middle_x) - ends)
                support = residual < height * 0.015
                score = (int(support.sum()), -float(residual[support].sum()))
                if score > best:
                    best, valid = score, support
        if best[0] < 5:
            raise ValueError("Table outline is unclear; use a photo showing the full table")
        edge = np.polyfit(middle_x[valid], ends[valid], 1)
        edge[1] += padding
        return edge

    top_edge = horizontal_edge(tops, -6)
    bottom_edge = horizontal_edge(bottoms, 6)

    def intersection(rule, edge):
        y = np.clip((edge[0] * rule[1] + edge[1]) / (1 - edge[0] * rule[0]), 0, height - 1)
        return float(np.polyval(rule, y) / scale), float(y / scale)

    corners = [intersection(rule, edge) for rule, edge in
               ((rules[0], top_edge), (rules[-1], top_edge),
                (rules[-1], bottom_edge), (rules[0], bottom_edge))]
    table = rectify(image, corners)
    target = np.float32([[0, 0], [table.width - 1, 0],
                         [table.width - 1, table.height - 1], [0, table.height - 1]])
    matrix = cv2.getPerspectiveTransform(np.float32(corners), target)
    points = np.float32([[[np.polyval(rule, height / 2) / scale,
                          height / 2 / scale]] for rule in rules[1:-1]])
    columns = [0, *[round(float(point[0])) for point in cv2.perspectiveTransform(points, matrix)[:, 0]], table.width]
    validate_edges(columns, table.width, 9)
    return table, {"image_size": list(image.size), "corners": corners, "columns": columns}


def detect_rows(column_results, height):
    """Use transaction numbers and dates as row anchors."""
    anchors = []
    for column in range(3):
        for token in column_results[column]:
            text = token["text"].strip()
            if (column == 0 and text.isdigit()) or (column in (1, 2) and re.match(r"\d{1,2}/\d{1,2}/\d{4}", text)):
                anchors.append(token)
    if not anchors:
        raise ValueError("No transaction numbers or dates detected; cannot identify statement rows")
    line_height = min(statistics.median(t["box"][3] - t["box"][1] for t in anchors), height / 40)
    groups = []
    for token in sorted(anchors, key=lambda t: t["box"][1]):
        y = token["box"][1]
        if not groups or y - statistics.median(groups[-1]) > max(3, line_height * 0.75):
            groups.append([])
        groups[-1].append(y)
    starts = [max(0, round(statistics.median(group) - line_height * 0.35)) for group in groups]
    rows = [*starts, height]
    if any(b - a < 3 for a, b in zip(rows, rows[1:])):
        raise ValueError("Detected transaction rows overlap")
    return rows


def create_ocr():
    """Initialize PaddleOCR and TextRecognition (auto detects GPU vs CPU)."""
    from paddleocr import PaddleOCR, TextRecognition
    import paddle

    device = "gpu" if paddle.is_compiled_with_cuda() else "cpu"
    print(f"Loading PP-OCRv6 models on device: {device.upper()}...")

    ocr_kwargs = {
        "device": device,
        "text_detection_model_name": "PP-OCRv6_medium_det",
        "text_recognition_model_name": "PP-OCRv6_medium_rec",
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "text_rec_score_thresh": 0.0,
    }
    rec_kwargs = {
        "model_name": "PP-OCRv6_medium_rec",
        "device": device,
    }
    if device == "cpu":
        ocr_kwargs["enable_mkldnn"] = False
        ocr_kwargs["cpu_threads"] = 4
        rec_kwargs["enable_mkldnn"] = False
        rec_kwargs["cpu_threads"] = 4

    ocr = PaddleOCR(**ocr_kwargs)
    numbers = TextRecognition(**rec_kwargs)
    return ocr, numbers


def read_tokens(image, ocr, scale=1):
    crop = np.asarray(image)[:, :, ::-1].copy()
    if scale > 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    crop = cv2.copyMakeBorder(crop, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    tokens = []
    for prediction in ocr.predict(crop):
        for text, score, box in zip(prediction["rec_texts"], prediction["rec_scores"], prediction["rec_boxes"], strict=True):
            if text.strip():
                x0, y0, x1, y1 = (int(v) for v in box)
                tokens.append({"text": text, "score": float(score),
                               "box": [round((x0 - 12) / scale + 2), round((y0 - 12) / scale),
                                       round((x1 - 12) / scale + 2), round((y1 - 12) / scale)]})
    return tokens


def read_index_tokens(table, layout, recognizer):
    left, right = layout["columns"][:2]
    crops, boxes = [], []
    for top, bottom in zip(layout["rows"], layout["rows"][1:]):
        crop = np.asarray(table.crop((left + 3, top, right - 3, bottom)))[:, :, ::-1].copy()
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY_INV, 31, 10)
        _, _, stats, _ = cv2.connectedComponentsWithStats(ink)
        letters = [(x, y, x + w, y + h) for x, y, w, h, area in stats[1:]
                   if area >= 5 and w >= 2 and h >= 4 and h < crop.shape[0] * 0.8 and h <= crop.shape[1]]
        if not letters:
            continue
        x0 = max(0, min(b[0] for b in letters) - 1)
        y0 = max(0, min(b[1] for b in letters) - 1)
        x1 = min(crop.shape[1], max(b[2] for b in letters) + 1)
        y1 = min(crop.shape[0], max(b[3] for b in letters) + 1)
        crops.append(crop[y0:y1, x0:x1])
        boxes.append([x0 + 3, y0 + top, x1 + 3, y1 + top])
    tokens = []
    if crops:
        for box, prediction in zip(boxes, recognizer.predict(crops, batch_size=8), strict=True):
            text = prediction["rec_text"].strip()
            if text:
                tokens.append({"text": text, "score": float(prediction["rec_score"]), "box": box})
    return tokens


def extract(table, layout, threshold, ocr, number_recognizer):
    column_results = [[]]
    for column in range(1, len(COLUMNS)):
        left, right = layout["columns"][column:column + 2]
        print(f"  Reading col {column + 1}/8: {COLUMNS[column]}...", flush=True)
        image = table.crop((left + 2, 0, right - 2, table.height))
        column_results.append(read_tokens(image, ocr, scale=3 if image.width < 60 else 1))
    layout["rows"] = detect_rows(column_results, table.height)
    print(f"  Reading {len(layout['rows']) - 1} row numbers...", flush=True)
    column_results[0] = read_index_tokens(table, layout, number_recognizer)
    return assemble(column_results, layout["rows"], threshold)


def prepare_table(path):
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    return detect_table(image)


def export_to_google_sheets(gc, results, failures, sheet_title):
    """Create a Google Sheet with formatting and flagged rows highlighted."""
    headers = list(COLUMNS) + ["flagged"]
    all_rows = [headers]

    for result in results:
        flags = {}
        for issue in result["issues"]:
            message = issue["issue"].replace("_", " ")
            if issue.get("column"):
                message = issue["column"] + ": " + message
            if issue["issue"] == "low_confidence":
                message += f" {issue['score']:.2f} < {issue['threshold']:.2f}"
            if "row" not in issue:
                message += ": " + issue.get("token", {}).get("text", "")
            flags.setdefault(issue.get("row"), []).append(message)

        for number, record in enumerate(result["rows"], 1):
            messages = flags.get(number, [])
            flagged = result["source"] + ": " + "; ".join(dict.fromkeys(messages)) if messages else ""
            row_data = [str(record.get(col) or "") for col in COLUMNS] + [flagged]
            all_rows.append(row_data)

        if flags.get(None):
            all_rows.append([""] * len(COLUMNS) + [result["source"] + ": " + "; ".join(dict.fromkeys(flags[None]))])

    for failure in failures:
        all_rows.append([""] * len(COLUMNS) + [failure["source_file"] + ": " + failure["error"]])

    print(f"Creating Google Sheet: '{sheet_title}'...")
    sh = gc.create(sheet_title)
    ws = sh.sheet1
    ws.title = "Statement Results"

    # Resize sheet grid to fit all rows and columns
    num_rows = max(len(all_rows) + 50, 100)
    num_cols = max(len(headers), 10)
    ws.resize(rows=num_rows, cols=num_cols)

    # Fast batch write
    ws.update(range_name='A1', values=all_rows)

    # Format sheet
    col_widths = [80, 180, 130, 180, 500, 150, 150, 150, 600]
    requests = []

    # 1. Custom column widths
    for i, width in enumerate(col_widths):
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": i,
                    "endIndex": i + 1,
                },
                "properties": {"pixelSize": width},
                "fields": "pixelSize",
            }
        })

    # 2. Header styling: dark slate blue (#243746), bold white text, centered
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": ws.id,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": 0,
                "endColumnIndex": len(headers),
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {"red": 36 / 255, "green": 55 / 255, "blue": 70 / 255},
                    "textFormat": {
                        "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                        "bold": True,
                    },
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
        }
    })

    # 3. Freeze row 1
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": ws.id,
                "gridProperties": {
                    "frozenRowCount": 1,
                },
            },
            "fields": "gridProperties.frozenRowCount",
        }
    })

    # 4. Highlight flagged rows with soft yellow (#FFF2CC)
    requests.append({
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [{
                    "sheetId": ws.id,
                    "startRowIndex": 1,
                    "endRowIndex": len(all_rows),
                    "startColumnIndex": 0,
                    "endColumnIndex": len(headers),
                }],
                "booleanRule": {
                    "condition": {
                        "type": "CUSTOM_FORMULA",
                        "values": [{"userEnteredValue": '=$I2<>""'}],
                    },
                    "format": {
                        "backgroundColor": {"red": 255 / 255, "green": 242 / 255, "blue": 204 / 255},
                    },
                },
            },
            "index": 0,
        }
    })

    try:
        sh.batch_update({"requests": requests})
    except Exception as e:
        print(f"Formatting note: {e}")

    return sh, len(all_rows) - 1


def export_to_excel(path, results, failures=()):
    """Export local Excel backup file."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = Workbook()
    data = workbook.active
    data.title = "Data"
    data.append((*COLUMNS, "flagged"))
    for result in results:
        flags = {}
        for issue in result["issues"]:
            message = issue["issue"].replace("_", " ")
            if issue.get("column"):
                message = issue["column"] + ": " + message
            if issue["issue"] == "low_confidence":
                message += f" {issue['score']:.2f} < {issue['threshold']:.2f}"
            if "row" not in issue:
                message += ": " + issue.get("token", {}).get("text", "")
            flags.setdefault(issue.get("row"), []).append(message)
        for number, record in enumerate(result["rows"], 1):
            messages = flags.get(number, [])
            flagged = result["source"] + ": " + "; ".join(dict.fromkeys(messages)) if messages else None
            data.append((*[record[name] or None for name in COLUMNS], flagged))
            data.row_dimensions[data.max_row].height = min(160, max(30, 15 * (len(record["content"]) // 75 + 1)))
        if flags.get(None):
            data.append((*[None for _ in COLUMNS], result["source"] + ": " + "; ".join(dict.fromkeys(flags[None]))))
    for failure in failures:
        data.append((*[None for _ in COLUMNS], failure["source_file"] + ": " + failure["error"]))
    data.freeze_panes = "A2"
    data.auto_filter.ref = data.dimensions
    data.row_dimensions[1].height = 24
    for cell in data[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="243746")
    for column, width in enumerate((9, 24, 16, 24, 78, 20, 20, 20, 100), 1):
        data.column_dimensions[data.cell(1, column).column_letter].width = width
    for row in data.iter_rows(min_row=2):
        for cell in row:
            cell.data_type = "s"
            cell.number_format = "@"
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        if row[-1].value:
            row[-1].fill = PatternFill("solid", fgColor="FFF2CC")
    workbook.save(path)

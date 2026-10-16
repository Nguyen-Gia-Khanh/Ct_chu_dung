"""Laptop-side JPEG processing. Frames stay in memory; only decoded scans are saved."""

import base64
import time

import cv2
import numpy as np
import zxingcpp

MAX_FRAME_BYTES = 1_000_000
MAX_FRAME_PIXELS = 1920 * 1080
FORMATS = (zxingcpp.BarcodeFormat.LinearCodes, zxingcpp.BarcodeFormat.QRCode, zxingcpp.BarcodeFormat.DataMatrix)
# Sharpen across vertical bars, without mixing pixels along their length.
VERTICAL_SHARPEN = np.array([[-.25, 1.5, -.25]], dtype=np.float32)
BARCODE_DETECTOR = cv2.barcode_BarcodeDetector()


def jpeg_dimensions(data):
    """Check JPEG dimensions before native decoding can allocate its pixel buffer."""
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("Send a JPEG camera frame.")
    offset = 2
    while offset < len(data):
        if data[offset] != 255:
            break
        while offset < len(data) and data[offset] == 255:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in (0xDA, 0xD9):
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            continue
        length = int.from_bytes(data[offset:offset + 2], "big")
        if length < 2 or offset + length > len(data):
            break
        if marker in (0xC0, 0xC1, 0xC2):
            if length < 8:
                break
            height = int.from_bytes(data[offset + 3:offset + 5], "big")
            width = int.from_bytes(data[offset + 5:offset + 7], "big")
            if width < 16 or height < 16 or width * height > MAX_FRAME_PIXELS:
                raise ValueError("Camera frame dimensions are out of range.")
            return width, height
        offset += length
    raise ValueError("Invalid or unsupported JPEG frame.")


def straighten(image, points):
    """Map a label quadrilateral to a rectangle, retaining space around its ink."""
    center = points.mean(axis=0)
    points = center + (points - center) * 1.20
    # Cyclic order avoids duplicated corners from sum/difference ordering at 45 degrees.
    order = np.argsort(np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0]))
    points = points[order].astype(np.float32)
    width = int(round(max(np.linalg.norm(points[1] - points[0]), np.linalg.norm(points[2] - points[3]))))
    height = int(round(max(np.linalg.norm(points[2] - points[1]), np.linalg.norm(points[3] - points[0]))))
    if min(width, height) < 16:
        return None
    target = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    result = cv2.warpPerspective(image, cv2.getPerspectiveTransform(points, target), (width, height),
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    return result


def red_regions(image):
    """Locate red ink on white packaging without treating black contents as labels."""
    scale = min(1, 640 / image.shape[1])
    small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 65, 45), (12, 255, 255)) | cv2.inRange(hsv, (168, 65, 45), (179, 255, 255))
    # Join the barcode's disconnected red bars; do not filter the decoding image here.
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 21), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:3]:
        if cv2.contourArea(contour) < 150:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if min(w, h) < 10:
            continue
        # Try an untouched crop before resampling; quiet zones matter for linear codes.
        margin = max(12, int(max(w, h) * .15))
        left, top = max(0, int((x - margin) / scale)), max(0, int((y - margin) / scale))
        right = min(image.shape[1], int((x + w + margin) / scale))
        bottom = min(image.shape[0], int((y + h + margin) / scale))
        yield image[top:bottom, left:right]
        hull = cv2.convexHull(contour)
        quad = cv2.approxPolyDP(hull, .03 * cv2.arcLength(hull, True), True)
        # ponytail: ink contours approximate the label; curved bags need a real sample to tune further.
        points = (quad.reshape(4, 2) if len(quad) == 4 else cv2.boxPoints(cv2.minAreaRect(contour)))
        corrected = straighten(image, points.astype(np.float32) / scale)
        if corrected is not None:
            yield corrected


def read(image):
    # Ask for one symbol so the native reader can stop after the first valid read.
    item = zxingcpp.read_barcode(np.ascontiguousarray(image), formats=FORMATS, try_invert=False,
                                text_mode=zxingcpp.TextMode.Plain, return_errors=False)
    if item is None or not item.valid or not item.text:
        return []
    return [{"text": item.text, "format": str(item.format),
             "position": [[p.x, p.y] for p in (item.position.top_left, item.position.top_right,
                                               item.position.bottom_right, item.position.bottom_left)]}]


def barcode_region(gray):
    """Use OpenCV's native barcode locator, rather than grouping label/text edges."""
    scale = min(1, 480 / gray.shape[1])
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    # The native locator's scale scoring needs context around a very shallow strip.
    padding = max(0, round((small.shape[1] * .75 - small.shape[0]) / 2))
    padded = cv2.copyMakeBorder(small, padding, padding, 0, 0, cv2.BORDER_CONSTANT, value=255)
    found, candidates = BARCODE_DETECTOR.detectMulti(padded)
    if not found:
        return None
    return (max(candidates, key=cv2.contourArea) - np.float32([0, padding])) / scale


def barcode_mask(gray, points):
    """Show thresholded ink only inside the native candidate, white everywhere else."""
    scale = min(1, 640 / gray.shape[1])
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    preview = np.full_like(small, 255)
    if points is not None:
        filtered = cv2.filter2D(small, -1, VERTICAL_SHARPEN)
        binary = cv2.adaptiveThreshold(filtered, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY, 31, 9)
        inside = np.zeros_like(small)
        cv2.fillConvexPoly(inside, np.round(points * scale).astype(np.int32), 255)
        preview[inside != 0] = binary[inside != 0]
    encoded = cv2.imencode('.png', preview)[1]
    return 'data:image/png;base64,' + base64.b64encode(encoded).decode('ascii')


def decode_frame(data, *, enhance=True):
    started = time.perf_counter()
    if not 0 < len(data) <= MAX_FRAME_BYTES:
        raise ValueError("Camera frame is too large or empty.")
    width, height = jpeg_dimensions(data)
    try:
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error as error:
        raise ValueError("Invalid JPEG camera frame.") from error
    if image is None or image.shape[:2] != (height, width):
        raise ValueError("Invalid JPEG camera frame.")
    box = mask = None
    stage = "original strip"
    results = read(image)
    if enhance:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # Keep the original's detail first; flatten uneven illumination only on a miss.
        if not results:
            background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, np.ones((1, 51), np.uint8))
            contrast = cv2.divide(gray, np.maximum(background, 1), scale=255)
            results = read(cv2.filter2D(contrast, -1, VERTICAL_SHARPEN))
            stage = "local contrast"
        # Never crop a decoder input to an unconfirmed box: it may contain only part of a code.
        # Linear readers may report only a single scanline; use the locator for bar height.
        points = barcode_region(gray)
        if points is None and results:
            points = np.float32(results[0]['position'])
            center, (w, h), angle = cv2.minAreaRect(points)
            band = max(8, height * .08)
            points = cv2.boxPoints((center, (max(w, band), max(h, band)), angle))
        mask = barcode_mask(gray, points)
        if points is not None:
            x, y, w, h = cv2.boundingRect(points)
            left, top = max(0, x), max(0, y)
            right, bottom = min(width, x + w), min(height, y + h)
            box = [left / width, top / height, (right - left) / width, (bottom - top) / height]
    return {"results": results, "milliseconds": round((time.perf_counter() - started) * 1000, 1),
            "stage": stage if results else "no barcode", "box": box, "mask": mask}

"""Laptop-side JPEG processing. Frames stay in memory; only decoded scans are saved."""

import time

import cv2
import numpy as np
import zxingcpp

MAX_FRAME_BYTES = 1_000_000
MAX_FRAME_PIXELS = 1920 * 1080
FORMATS = (zxingcpp.BarcodeFormat.LinearCodes, zxingcpp.BarcodeFormat.QRCode, zxingcpp.BarcodeFormat.DataMatrix)
SHARPEN = np.array([[0, -.25, 0], [-.25, 2, -.25], [0, -.25, 0]], dtype=np.float32)


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
    results = zxingcpp.read_barcodes(np.ascontiguousarray(image), formats=FORMATS,
                                   text_mode=zxingcpp.TextMode.Plain, return_errors=False)
    return [{"text": item.text, "format": str(item.format)} for item in results if item.valid and item.text][:1]


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
    results = read(image)
    stage = "original"
    if not results and enhance:
        # Green makes red ink dark against white, while luminance washes red ink out.
        for region in (*red_regions(image), image):
            green = region[:, :, 1]
            results = read(green)
            stage = "red contrast / crop / correction"
            if results:
                break
            filtered = cv2.filter2D(green, -1, SHARPEN)
            results = read(filtered)
            stage = "kernel filter"
            if results:
                break
            _, binary = cv2.threshold(filtered, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
            results = read(binary)
            stage = "threshold"
            if results:
                break
    return {"results": results, "milliseconds": round((time.perf_counter() - started) * 1000, 1),
            "stage": stage if results else "no barcode"}

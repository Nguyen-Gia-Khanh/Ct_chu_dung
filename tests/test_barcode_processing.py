"""Generated red component labels on white packaging with black background contents."""

import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import zxingcpp

from barcode_web.processing import decode_frame, jpeg_dimensions, read, red_regions


def component_label():
    bars = np.asarray(zxingcpp.write_barcode(zxingcpp.BarcodeFormat.Code128, "06410KFL850", 660, 240))
    label = cv2.cvtColor(bars, cv2.COLOR_GRAY2BGR)
    label[bars < 128] = (35, 35, 220)
    # A red stamp border is representative of the outlined component label.
    cv2.rectangle(label, (2, 2), (label.shape[1] - 3, label.shape[0] - 3), (35, 35, 220), 3)
    return label


def packaging(label, corners=None):
    image = np.full((720, 1280, 3), 245, np.uint8)
    cv2.rectangle(image, (20, 450), (320, 690), (20, 20, 20), -1)
    cv2.circle(image, (1100, 170), 120, (30, 30, 30), -1)
    height, width = label.shape[:2]
    if corners is None:
        image[240:240 + height, 350:350 + width] = label
    else:
        source = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
        transform = cv2.getPerspectiveTransform(source, np.float32(corners))
        warped = cv2.warpPerspective(label, transform, (1280, 720), borderValue=(245, 245, 245))
        mask = cv2.warpPerspective(np.full((height, width), 255, np.uint8), transform, (1280, 720))
        image[mask > 0] = warped[mask > 0]
    return image


def jpeg(image):
    return cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()


class BarcodeProcessingTests(unittest.TestCase):
    def test_red_labels_rotation_perspective_and_low_contrast(self):
        label = component_label()
        scenes = [packaging(label),
                  packaging(label, [[310, 80], [1030, 280], [880, 600], [270, 360]]),
                  packaging(label, [[440, 100], [820, 280], [670, 620], [300, 410]]),
                  packaging(cv2.addWeighted(label, .45, np.full_like(label, 255), .55, 0))]
        started = time.perf_counter()
        for index, scene in enumerate(scenes):
            with self.subTest(scene=index):
                self.assertEqual(decode_frame(jpeg(scene))["results"][0]["text"], "06410KFL850")
                regions = list(red_regions(scene))
                self.assertTrue(regions, "red crop should survive black contents on white packaging")
                self.assertTrue(any(read(region[:, :, 1]) for region in regions), "crop/correction must preserve readable bars")
        print(f"Four synthetic component frames decoded in {(time.perf_counter() - started) * 1000:.0f} ms on laptop.")

    def test_fallback_processing_when_original_has_no_result(self):
        original_read = read
        calls = 0
        def miss_original(image):
            nonlocal calls
            calls += 1
            return [] if calls == 1 else original_read(image)
        with patch("barcode_web.processing.read", side_effect=miss_original):
            answer = decode_frame(jpeg(packaging(component_label())))
        self.assertEqual(answer["results"][0]["text"], "06410KFL850")
        self.assertNotEqual(answer["stage"], "original")

    def test_black_qr_blank_and_unfiltered_frames(self):
        qr = np.asarray(zxingcpp.write_barcode(zxingcpp.BarcodeFormat.QRCode, "warehouse-test-001", 264, 264))
        self.assertEqual(decode_frame(jpeg(qr), enhance=False)["results"][0]["text"], "warehouse-test-001")
        blank = np.full((720, 1280, 3), 255, np.uint8)
        self.assertEqual(decode_frame(jpeg(blank))["results"], [])
        self.assertEqual(decode_frame(jpeg(packaging(component_label())), enhance=False)["results"][0]["text"], "06410KFL850")

    def test_rejects_invalid_and_oversized_images_before_native_decode(self):
        data = jpeg(packaging(component_label()))
        self.assertEqual(jpeg_dimensions(data), (1280, 720))
        # Replace the JPEG SOF dimensions with a compressed-image bomb header.
        offset = data.index(b"\xff\xc0") + 5
        bomb = data[:offset] + b"\xff\xff\xff\xff" + data[offset + 4:]
        for invalid in (b"not jpeg", data[:20], bomb, data * (1_000_000 // len(data) + 1)):
            with self.subTest(length=len(invalid)), self.assertRaises(ValueError):
                decode_frame(invalid)


if __name__ == "__main__":
    unittest.main()

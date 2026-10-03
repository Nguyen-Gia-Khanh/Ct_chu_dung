"""Offline checks for store persistence, tab ownership, and partial batches."""

from threading import Barrier, Event, get_ident
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mapper.features.kiotviet_settings import load_settings, save_settings, validate_store_url, validate_tab_count
from mapper.features.web_upload import LocationUpdate, UploadError, UploadProduct, WebsiteUploader
from tests.support import WorkspaceTestCase


URL = "https://hondaminhdung.kiotviet.vn/man/#/Products"


class PlaywrightUploadTests(WorkspaceTestCase):
    def test_settings_survive_restart_and_invalid_edits_preserve_previous_values(self):
        path = self.folder / "settings.json"
        self.assertEqual(load_settings(path), ("", 1))
        save_settings("  " + URL + "  ", "3", path)
        self.assertEqual(load_settings(path), (URL, 3))
        for url in ("", "https://kiotviet.vn", "https://evilkiotviet.vn/man/#/Products",
                    "https://shop.kiotviet.vn.evil.com/man/#/Products",
                    "https://x .kiotviet.vn/man/#/Products", "http://shop.kiotviet.vn/man/#/Products",
                    "https://user:pass@shop.kiotviet.vn/man/#/Products", URL + "?fake"):
            with self.assertRaises(ValueError):
                save_settings(url, 2, path)
        for tabs in (0, 11, "", "1.5", True, "two"):
            with self.assertRaises(ValueError):
                validate_tab_count(tabs)
        self.assertEqual(load_settings(path), (URL, 3))
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_settings(path)

    def test_only_the_saved_store_matches(self):
        uploader = WebsiteUploader(store_url=URL)
        self.assertTrue(uploader._matches_store(SimpleNamespace(url=URL)))
        self.assertFalse(uploader._matches_store(SimpleNamespace(url=URL.replace("hondaminhdung", "other"))))
        self.assertFalse(uploader._matches_store(SimpleNamespace(url="chrome://settings")))
        self.assertEqual(validate_store_url(URL.replace("hondaminhdung", "MY-STORE")),
                         URL.replace("hondaminhdung", "my-store"))

    def test_concurrent_tabs_have_separate_thread_owned_runtimes(self):
        barrier = Barrier(3)
        created, completed, closed, disconnected = [], [], [], []

        def connect(uploader, _progress):
            uploader.owner = get_ident()
            uploader.page = SimpleNamespace(close=lambda: closed.append(uploader.owner))
            created.append(uploader)

        def new_tab(uploader):
            self.assertEqual(uploader.owner, get_ident())
            uploader.page = SimpleNamespace(close=lambda: closed.append(uploader.owner))

        def modify(uploader, product, _progress, *, save):
            self.assertTrue(save)
            self.assertEqual(uploader.owner, get_ident())
            barrier.wait(timeout=5)  # Sequential scheduling cannot pass this.
            return product.product_id

        def disconnect(uploader):
            self.assertEqual(uploader.owner, get_ident())
            disconnected.append(uploader.owner)

        with patch.object(WebsiteUploader, "connect", connect), \
                patch.object(WebsiteUploader, "_new_upload_tab", new_tab), \
                patch.object(WebsiteUploader, "modify_location", modify), \
                patch.object(WebsiteUploader, "disconnect", disconnect):
            result = WebsiteUploader(store_url=URL).run_batch(
                [LocationUpdate(f"P{i}", ("A", "B")) for i in range(6)],
                lambda _text: None, completed.append, location_only=True, save=True, tab_count=3,
            )
        self.assertEqual(len({uploader.owner for uploader in created}), 3)
        self.assertEqual(sorted(completed), [f"P{i}" for i in range(6)])
        self.assertEqual(len(closed), 3)
        self.assertEqual(len(disconnected), 3)
        self.assertIn("6 products", result)

    def test_failure_stops_new_products_and_reports_successful_in_flight_items(self):
        barrier, failed = Barrier(2), Event()
        attempted, completed, disconnected, closed = [], [], [], []

        def connect(uploader, _progress):
            uploader.page = SimpleNamespace()

        def new_tab(uploader):
            uploader.page = SimpleNamespace(close=lambda: closed.append(True))

        def modify(uploader, product, _progress, *, save):
            attempted.append(product.product_id)
            barrier.wait(timeout=5)
            if product.product_id == "P0":
                raise UploadError("Save may have reached the website; inspect before retrying")
            self.assertTrue(failed.wait(timeout=5))
            return "saved"

        def disconnect(uploader):
            disconnected.append(True)
            failed.set()

        with patch.object(WebsiteUploader, "connect", connect), \
                patch.object(WebsiteUploader, "_new_upload_tab", new_tab), \
                patch.object(WebsiteUploader, "modify_location", modify), \
                patch.object(WebsiteUploader, "disconnect", disconnect):
            with self.assertRaisesRegex(UploadError, "1/6.*product"):
                WebsiteUploader(store_url=URL).run_batch(
                    [LocationUpdate(f"P{i}", "A") for i in range(6)],
                    lambda _text: None, completed.append, location_only=True, save=True, tab_count=2,
                )
        self.assertEqual(sorted(attempted), ["P0", "P1"])
        self.assertEqual(completed, ["P1"])
        self.assertEqual(len(disconnected), 2)
        self.assertEqual(closed, [])  # Error tabs stay available for inspection.

    def test_single_tab_keeps_existing_tab_and_cannot_duplicate_a_product(self):
        uploader = WebsiteUploader(store_url=URL)
        with patch.object(WebsiteUploader, "connect"), \
                patch.object(WebsiteUploader, "_new_upload_tab") as new_tab, \
                patch.object(WebsiteUploader, "upload", return_value="filled") as upload, \
                patch.object(WebsiteUploader, "disconnect"):
            result = uploader.run_batch([UploadProduct("P1", 3, "A")], lambda _text: None,
                                        lambda _id: None, location_only=False, save=False)
            self.assertEqual(result, "filled")
            new_tab.assert_not_called()
            self.assertFalse(upload.call_args.kwargs["save"])
        with self.assertRaisesRegex(UploadError, "each product ID only once"):
            uploader.run_batch([LocationUpdate("P1", "A")] * 2, None, None,
                               location_only=True, save=True, tab_count=2)


if __name__ == "__main__":
    unittest.main()

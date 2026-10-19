"""Offline checks for store persistence, tab ownership, and partial batches."""

from threading import Barrier, Event, get_ident
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mapper.features.kiotviet_settings import load_settings, save_settings, validate_store_url, validate_tab_count
from mapper.features.web_upload import LocationUpdate, UploadError, UploadProduct, WebsiteUploader
from tests.support import WorkspaceTestCase


URL = "https://hondaminhdung.kiotviet.vn/man/#/Products"


class PlaywrightUploadTests(WorkspaceTestCase):
    def test_connect_does_not_require_an_open_store_tab(self):
        uploader = WebsiteUploader(store_url=URL)
        with patch.object(uploader, "_connect") as attach, patch.object(uploader, "_choose_tab") as select:
            uploader.browser = SimpleNamespace(is_connected=lambda: True)
            self.assertIn("Chrome connected", uploader.connect())
        attach.assert_called_once()
        select.assert_not_called()
        self.assertTrue(uploader.is_connected())

    def test_web_action_opens_saved_url_when_no_store_tab_exists(self):
        page = SimpleNamespace(url="about:blank", is_closed=lambda: False)
        page.goto = lambda url, **_kwargs: setattr(page, "url", url)
        context = SimpleNamespace(pages=[], new_page=lambda: page)
        uploader = WebsiteUploader(store_url=URL)
        uploader.browser = SimpleNamespace(contexts=[context])
        uploader._choose_tab(wait_ready=False)
        self.assertIs(uploader.page, page)
        self.assertEqual(page.url, URL)

    def test_empty_edit_form_reloads_once_before_retrying_without_saving(self):
        uploader = WebsiteUploader(store_url=URL, timeout=0, step_delay=0)
        response = SimpleNamespace(url="https://api-man1.kiotviet.vn/api/products/1/initialdata",
                                   ok=True, body=lambda: b"{}")
        uploader.page = SimpleNamespace(reload=Mock(), expect_response=lambda *_args, **_kwargs:
                                        nullcontext(SimpleNamespace(value=response)))
        ready_checks = iter((False, True))

        def dom(action, *_args):
            return next(ready_checks) if action == "edit_ready" else True if action != "errors" else ""

        with patch.object(uploader, "_evaluate_async", return_value={"ok": True, "kiotviet_id": "1"}) as open_edit, \
                patch.object(uploader, "_dom", side_effect=dom), \
                patch.object(uploader, "_save_product") as save:
            uploader._open_product(LocationUpdate("P1", "A"))
        self.assertEqual(open_edit.call_count, 2)
        uploader.page.reload.assert_called_once()
        save.assert_not_called()

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
            uploader.page = SimpleNamespace(close=lambda: closed.append(uploader.owner), is_closed=lambda: False)
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
                patch.object(WebsiteUploader, "_choose_tab"), \
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

    def test_free_tab_takes_next_product_while_slow_tab_waits_for_response(self):
        slow_started, next_started = Event(), Event()
        completed = []

        def modify(uploader, product, _progress, *, save):
            self.assertEqual(uploader.step_delay, 0)
            if product.product_id == "P0":
                slow_started.set()
                self.assertTrue(next_started.wait(timeout=5))
            elif product.product_id == "P1":
                self.assertTrue(slow_started.wait(timeout=5))
            elif product.product_id == "P2":
                self.assertNotIn("P0", completed)
                next_started.set()
            return "response received"

        with patch.object(WebsiteUploader, "connect"), \
                patch.object(WebsiteUploader, "_choose_tab"), \
                patch.object(WebsiteUploader, "_new_upload_tab"), \
                patch.object(WebsiteUploader, "modify_location", modify), \
                patch.object(WebsiteUploader, "disconnect"):
            WebsiteUploader(store_url=URL).run_batch(
                [LocationUpdate(f"P{i}", "A") for i in range(4)],
                lambda _text: None, completed.append, location_only=True, save=True, tab_count=2,
            )
        self.assertEqual(sorted(completed), [f"P{i}" for i in range(4)])

    def test_existing_location_reads_do_not_serialize_workers(self):
        barrier = Barrier(2)
        selected = []

        def read_shelves(_uploader):
            barrier.wait(timeout=5)
            return {"A": "11"}

        def modify(uploader, product, progress, *, save):
            uploader._set_location(product, progress)
            return "saved"

        with patch.object(WebsiteUploader, "connect"), \
                patch.object(WebsiteUploader, "_choose_tab"), \
                patch.object(WebsiteUploader, "_new_upload_tab"), \
                patch.object(WebsiteUploader, "_dom", return_value=True), \
                patch.object(WebsiteUploader, "_shelf_ids_by_name", read_shelves), \
                patch.object(WebsiteUploader, "_select_location_ids", lambda _u, p, _ids: selected.append(p.product_id)), \
                patch.object(WebsiteUploader, "modify_location", modify), \
                patch.object(WebsiteUploader, "disconnect"):
            WebsiteUploader(store_url=URL).run_batch(
                [LocationUpdate("P0", "A"), LocationUpdate("P1", "A")],
                lambda _text: None, lambda _id: None, location_only=True, save=True, tab_count=2,
            )
        self.assertEqual(sorted(selected), ["P0", "P1"])

    def test_save_requires_successful_response_for_the_same_product_and_never_retries(self):
        product = LocationUpdate("P1", "A")
        for status, saved in ((200, {"Id": 1, "Code": "P1"}), (500, {}),
                              (200, {"Id": 2, "Code": "P1"}), (200, {"Id": 1, "Code": "P2"})):
            with self.subTest(status=status, saved=saved):
                uploader = WebsiteUploader(store_url=URL, step_delay=0)
                uploader._kiotviet_id = "1"
                order = []

                def response_body():
                    order.append("response body")
                    return {"Data": saved}

                response = SimpleNamespace(ok=status == 200, status=status,
                                           json=response_body)
                uploader.page = SimpleNamespace(expect_response=lambda *_args, **_kwargs:
                                                nullcontext(SimpleNamespace(value=response)))
                with patch.object(uploader, "_click", side_effect=lambda *_args: order.append("save")) as click, \
                        patch.object(uploader, "_dom", return_value=False):
                    if status == 200 and saved == {"Id": 1, "Code": "P1"}:
                        self.assertIn("Location saved", uploader._save_product(product, lambda _text: None, location_only=True))
                    else:
                        with self.assertRaisesRegex(UploadError, "No automatic retry"):
                            uploader._save_product(product, lambda _text: None)
                click.assert_called_once()
                self.assertEqual(order, ["save", "response body"] if status == 200 else ["save"])

    def test_page_focus_session_stays_attached_until_disconnect(self):
        session = Mock()
        page = SimpleNamespace(is_closed=lambda: False,
                               context=SimpleNamespace(new_cdp_session=Mock(return_value=session)))
        uploader = WebsiteUploader(page=page, store_url=URL)
        uploader._prepare_page()
        uploader._prepare_page()
        page.context.new_cdp_session.assert_called_once_with(page)
        session.send.assert_any_call("Emulation.setFocusEmulationEnabled", {"enabled": True})
        session.detach.assert_not_called()
        uploader.disconnect()
        session.detach.assert_called_once()

    def test_failure_stops_new_products_and_reports_successful_in_flight_items(self):
        barrier, failed = Barrier(2), Event()
        attempted, completed, disconnected, closed = [], [], [], []

        def connect(uploader, _progress):
            uploader.page = SimpleNamespace(is_closed=lambda: False)

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
                patch.object(WebsiteUploader, "_choose_tab"), \
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

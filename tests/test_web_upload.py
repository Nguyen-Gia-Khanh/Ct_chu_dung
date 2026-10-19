"""Focused checks for the KiotViet location-creation workflow."""

import unittest
from unittest.mock import ANY, Mock, call, patch

from mapper.features.web_upload import (
    CREATE_LOCATION_XPATH,
    DOM_SCRIPT,
    NEW_LOCATION_XPATH,
    OPEN_PRODUCT_SCRIPT,
    SAVE_LOCATION_XPATH,
    LocationUpdate,
    UploadProduct,
    WebsiteUploader,
)


class LocationCreationTests(unittest.TestCase):
    def test_new_location_is_filled_and_explicitly_saved(self):
        uploader = WebsiteUploader(step_delay=0)
        product = LocationUpdate("P1", "L1-1A1-1")
        uploader._wait = Mock()
        uploader._click = Mock()
        uploader._fill_input = Mock()
        uploader._select_location_ids = Mock()
        # First read, recheck under the creation lock, then the post-create poll.
        uploader._shelf_ids_by_name = Mock(side_effect=[{}, {}, {product.location_id: "42"}])

        uploader._set_location(product, Mock())

        self.assertEqual(uploader._click.call_args_list, [
            call(CREATE_LOCATION_XPATH, "opening Add location"),
            call(SAVE_LOCATION_XPATH, "saving the new location"),
        ])
        uploader._fill_input.assert_called_once_with(NEW_LOCATION_XPATH, product.location_id)
        uploader._select_location_ids.assert_called_once_with(product, {product.location_id: "42"})

    def test_existing_location_does_not_open_creation_dialog(self):
        uploader = WebsiteUploader(step_delay=0)
        product = LocationUpdate("P1", "L1-1A1-1")
        uploader._wait = Mock()
        uploader._click = Mock()
        uploader._fill_input = Mock()
        uploader._select_location_ids = Mock()
        uploader._shelf_ids_by_name = Mock(return_value={product.location_id: "42"})

        uploader._set_location(product, Mock())

        uploader._click.assert_not_called()
        uploader._fill_input.assert_not_called()
        uploader._select_location_ids.assert_called_once_with(product, {product.location_id: "42"})


class UploadInteractionTests(unittest.TestCase):
    def test_empty_location_clears_without_populating_or_checking(self):
        uploader = WebsiteUploader(step_delay=0)
        product = LocationUpdate("P1", "")
        uploader.is_connected = Mock(return_value=True)
        uploader._choose_tab = Mock()
        uploader._open_product = Mock()
        uploader._clear_location = Mock()
        uploader._set_location = Mock()
        uploader._location_values_match = Mock()
        uploader._shelf_ids_by_name = Mock()
        uploader._wait = Mock()
        uploader._save_product = Mock(return_value="cleared")

        self.assertEqual(uploader.modify_location(product, save=True), "cleared")

        uploader._clear_location.assert_called_once_with()
        uploader._set_location.assert_not_called()
        uploader._location_values_match.assert_not_called()
        uploader._shelf_ids_by_name.assert_not_called()
        uploader._wait.assert_not_called()
        uploader._save_product.assert_called_once_with(product, ANY, location_only=True)

    def test_clear_uses_selector_without_fetching_or_creating_shelves(self):
        uploader = WebsiteUploader(step_delay=0)
        uploader._wait = Mock()
        uploader._dom = Mock(return_value=True)
        uploader._shelf_ids_by_name = Mock()
        uploader._click = Mock()

        uploader._clear_location()

        uploader._dom.assert_called_once_with("location_clear", ANY)
        uploader._shelf_ids_by_name.assert_not_called()
        uploader._click.assert_not_called()

    def test_normal_upload_has_no_fixed_pause(self):
        uploader = WebsiteUploader(step_delay=2)
        product = UploadProduct("P1", 7, "L1-1A1-1")
        uploader.is_connected = Mock(return_value=True)
        uploader._choose_tab = Mock()
        uploader._pause = Mock()
        uploader._open_product = Mock()
        uploader._set_stock = Mock()
        uploader._set_location = Mock()
        uploader._wait = Mock()

        uploader.upload(product, save=False)

        uploader._pause.assert_not_called()
        uploader._open_product.assert_called_once_with(product)

    def test_explicit_save_override_allows_a_batch_to_advance(self):
        uploader = WebsiteUploader(step_delay=0)
        product = LocationUpdate("P1", "L1-1A1-1")
        uploader.is_connected = Mock(return_value=True)
        uploader._choose_tab = Mock()
        uploader._open_product = Mock()
        uploader._set_location = Mock()
        uploader._wait = Mock()
        uploader._save_product = Mock(return_value="saved")

        result = uploader.modify_location(product, save=True)

        self.assertEqual(result, "saved")
        uploader._save_product.assert_called_once_with(
            product,
            ANY,
            location_only=True,
        )

    def test_final_save_skips_verification_but_keeps_pause(self):
        uploader = WebsiteUploader(step_delay=2)
        product = UploadProduct("P1", 7, "L1-1A1-1")
        uploader._click = Mock()
        uploader._wait = Mock()
        uploader._pause = Mock()
        uploader._open_product = Mock()

        uploader._save_product(product, Mock())

        uploader._pause.assert_called_once_with()
        uploader.page.reload.assert_not_called()
        uploader._open_product.assert_not_called()

    def test_clear_skips_readback_even_when_save_verification_is_enabled(self):
        uploader = WebsiteUploader(step_delay=0)
        product = LocationUpdate("P1", "")
        uploader._click = Mock()
        uploader._wait = Mock()
        uploader._pause = Mock()

        with patch("mapper.features.web_upload.VERIFY_AFTER_SAVE", True):
            result = uploader._save_product(product, Mock(), location_only=True)

        self.assertEqual(result, "Location cleared: P1.")
        uploader.page.reload.assert_not_called()

    def test_dom_automation_does_not_force_focus_or_scroll(self):
        for script in (OPEN_PRODUCT_SCRIPT, DOM_SCRIPT):
            self.assertNotIn(".focus()", script)
            self.assertNotIn("scroll", script.lower())
        self.assertIn("targetClick", DOM_SCRIPT)
        self.assertIn("preventDefault", DOM_SCRIPT)


if __name__ == "__main__":
    unittest.main()

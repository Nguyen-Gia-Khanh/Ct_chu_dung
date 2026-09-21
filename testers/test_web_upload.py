"""Focused checks for the KiotViet location-creation workflow."""

import unittest
from unittest.mock import ANY, Mock, call

from mapper.web_upload import (
    CREATE_LOCATION_XPATH,
    DOM_SCRIPT,
    NEW_LOCATION_XPATH,
    SAVE_LOCATION_XPATH,
    LocationUpdate,
    UploadProduct,
    WebsiteUploader,
)


class LocationCreationTests(unittest.TestCase):
    def test_new_location_is_filled_and_explicitly_saved(self):
        uploader = WebsiteUploader(driver=Mock(), step_delay=0)
        product = LocationUpdate("P1", "L1-1A1-1")
        uploader._wait = Mock()
        uploader._click = Mock()
        uploader._fill_input = Mock()
        uploader._select_location_id = Mock()
        uploader._get_shelves_by_name = Mock(side_effect=[
            (set(), {}),
            ({product.location_id}, {product.location_id: "42"}),
        ])

        uploader._set_location(product, Mock())

        self.assertEqual(uploader._click.call_args_list, [
            call(CREATE_LOCATION_XPATH, "opening Add location"),
            call(SAVE_LOCATION_XPATH, "saving the new location"),
        ])
        uploader._fill_input.assert_called_once_with(NEW_LOCATION_XPATH, product.location_id)
        uploader._select_location_id.assert_called_once_with(product, "42")

    def test_existing_location_does_not_open_creation_dialog(self):
        uploader = WebsiteUploader(driver=Mock(), step_delay=0)
        product = LocationUpdate("P1", "L1-1A1-1")
        uploader._wait = Mock()
        uploader._click = Mock()
        uploader._fill_input = Mock()
        uploader._select_location_id = Mock()
        uploader._get_shelves_by_name = Mock(return_value=(
            {product.location_id}, {product.location_id: "42"},
        ))

        uploader._set_location(product, Mock())

        uploader._click.assert_not_called()
        uploader._fill_input.assert_not_called()
        uploader._select_location_id.assert_called_once_with(product, "42")


class UploadInteractionTests(unittest.TestCase):
    def test_normal_upload_has_no_fixed_pause(self):
        uploader = WebsiteUploader(driver=Mock(), step_delay=2)
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
        uploader = WebsiteUploader(driver=Mock(), step_delay=0)
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
        uploader = WebsiteUploader(driver=Mock(), step_delay=2)
        product = UploadProduct("P1", 7, "L1-1A1-1")
        uploader._click = Mock()
        uploader._wait = Mock()
        uploader._pause = Mock()
        uploader._open_product = Mock()

        uploader._save_product(product, Mock())

        uploader._pause.assert_called_once_with()
        uploader.driver.refresh.assert_not_called()
        uploader._open_product.assert_not_called()

    def test_dom_automation_does_not_force_focus_or_scroll(self):
        self.assertNotIn(".focus()", DOM_SCRIPT)
        self.assertNotIn("scrollIntoView", DOM_SCRIPT)
        self.assertIn("targetClick", DOM_SCRIPT)
        self.assertIn("preventDefault", DOM_SCRIPT)


if __name__ == "__main__":
    unittest.main()

"""Focused checks for the KiotViet location-creation workflow."""

import unittest
from unittest.mock import Mock, call

from mapper.web_upload import (
    CREATE_LOCATION_XPATH,
    NEW_LOCATION_XPATH,
    SAVE_LOCATION_XPATH,
    LocationUpdate,
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


if __name__ == "__main__":
    unittest.main()

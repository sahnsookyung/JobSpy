import unittest
from unittest.mock import Mock, patch

from jobspy.scrapers.japandev import JapanDev


class _FilterOption:
    full_id = "seniority-junior"


class JapanDevScraperTestCase(unittest.TestCase):
    def test_filter_clicks_are_individually_time_bounded(self) -> None:
        locator = Mock()
        locator.get_attribute.return_value = ""
        page = Mock()
        page.locator.return_value = locator

        with patch("jobspy.scrapers.japandev.expect") as expect:
            expect.return_value.to_have_class.return_value = None
            JapanDev()._click_filter(page, _FilterOption())

        locator.wait_for.assert_called_once_with(state="visible", timeout=2000)
        locator.scroll_into_view_if_needed.assert_called_once_with(timeout=2000)
        locator.click.assert_called_once_with(force=False, no_wait_after=True, timeout=2000)


if __name__ == "__main__":
    unittest.main()

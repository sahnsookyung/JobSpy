import os
import unittest
from unittest.mock import Mock, patch

from jobspy.scrapers import utils


class BrowserRuntimeTestCase(unittest.TestCase):
    def test_official_chrome_uses_constrained_runtime_flags(self) -> None:
        launch = Mock(return_value="browser")
        playwright = Mock()
        playwright.chromium.launch = launch

        with patch.dict(os.environ, {"JOBSPY_PLAYWRIGHT_CHANNEL": "chrome"}, clear=False):
            browser = utils.launch_playwright_browser(playwright)

        self.assertEqual(browser, "browser")
        _, kwargs = launch.call_args
        self.assertEqual(kwargs["channel"], "chrome")
        self.assertTrue(kwargs["headless"])
        self.assertIn("--use-gl=angle", kwargs["args"])
        self.assertIn("--use-angle=swiftshader", kwargs["args"])
        self.assertIn("--disable-extensions", kwargs["args"])

    def test_bundled_chromium_omits_channel(self) -> None:
        launch = Mock(return_value="browser")
        playwright = Mock()
        playwright.chromium.launch = launch

        with patch.dict(os.environ, {"JOBSPY_PLAYWRIGHT_CHANNEL": "bundled"}, clear=False):
            utils.launch_playwright_browser(playwright)

        _, kwargs = launch.call_args
        self.assertNotIn("channel", kwargs)

    def test_remaining_timeout_ms_never_returns_a_negative_budget(self) -> None:
        with patch("jobspy.scrapers.utils.time.monotonic", return_value=100.0):
            self.assertEqual(utils.remaining_timeout_ms(101.25), 1250)
            self.assertEqual(utils.remaining_timeout_ms(99.0), 0)

    def test_context_applies_the_navigation_timeout(self) -> None:
        browser = Mock()
        context = Mock()
        browser.new_context.return_value = context

        utils.create_playwright_context(browser, request_timeout=45)

        context.set_default_timeout.assert_called_once_with(45000)
        context.set_default_navigation_timeout.assert_called_once_with(45000)

    def test_managed_context_closes_context_and_browser(self) -> None:
        context = Mock()
        browser = Mock()
        with patch("jobspy.scrapers.utils.sync_playwright") as sync, \
            patch("jobspy.scrapers.utils.launch_playwright_browser", return_value=browser), \
            patch("jobspy.scrapers.utils.create_playwright_context", return_value=context):
            with utils.managed_playwright_context(request_timeout=45) as actual:
                self.assertIs(actual, context)

        context.close.assert_called_once_with()
        browser.close.assert_called_once_with()
        sync.return_value.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()

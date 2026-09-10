from unittest import TestCase
from unittest.mock import MagicMock, patch

from src.ridi_provider import RIDI_HOME_URL, get_ridi_session_status


class RidiPassiveSessionStatusTests(TestCase):
    def test_status_inspects_context_without_creating_page(self):
        context = MagicMock()
        context.cookies.return_value = [
            {
                "name": "ridi_auth",
                "value": "secret",
                "domain": ".ridibooks.com",
            }
        ]
        browser = MagicMock()
        browser.contexts = [context]

        playwright = MagicMock()
        playwright.chromium.connect_over_cdp.return_value = browser

        with patch("src.ridi_provider.sync_playwright") as sync_playwright:
            sync_playwright.return_value.start.return_value = playwright
            status = get_ridi_session_status(cdp_url="http://127.0.0.1:9222")

        self.assertTrue(status["chrome_running"])
        self.assertTrue(status["authenticated"])
        self.assertEqual(status["message"], "RIDI conectado.")
        playwright.chromium.connect_over_cdp.assert_called_once_with("http://127.0.0.1:9222")
        context.cookies.assert_called_once_with([RIDI_HOME_URL])
        context.new_page.assert_not_called()
        playwright.stop.assert_called_once_with()

    def test_status_reports_offline_when_cdp_is_unavailable(self):
        playwright = MagicMock()
        playwright.chromium.connect_over_cdp.side_effect = RuntimeError("CDP unavailable")

        with patch("src.ridi_provider.sync_playwright") as sync_playwright:
            sync_playwright.return_value.start.return_value = playwright
            status = get_ridi_session_status(cdp_url="http://127.0.0.1:9222")

        self.assertFalse(status["chrome_running"])
        self.assertFalse(status["authenticated"])
        self.assertEqual(status["message"], "Chrome RIDI não iniciado.")
        playwright.stop.assert_called_once_with()

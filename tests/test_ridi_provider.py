"""Offline tests for the RIDI provider contracts."""
import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.ridi_provider import (
    RIDI_CDP_URL,
    RIDI_PAGE_ADVANCE_DELAY_MS,
    RIDI_HOSTS,
    RIDI_PROFILE_RELATIVE_PATH,
    RidiCaptureConflictError,
    RidiCaptureIncompleteError,
    RidiCaptureResult,
    RidiCapturedPage,
    RidiSessionRequiredError,
    RidiSessionVerificationPendingError,
    RidiViewerCaptureError,
    RidiViewerStructureError,
    _CaptureStore,
    _read_expected_data_indexes,
    collect_ridi_viewer_pages,
    discover_ridi_chapters,
    get_ridi_profile_dir,
    install_ridi_blob_capture,
    is_ridi_chapter_url,
    is_ridi_title_url,
    require_usable_ridi_session,
    ridi_browser_page,
    ridi_cdp_browser_page,
    save_ridi_captured_pages,
    get_ridi_session_status,
    start_ridi_chrome,
)


class RidiUrlTests(unittest.TestCase):
    def test_recognizes_confirmed_title_url_structure(self):
        self.assertTrue(is_ridi_title_url("https://ridibooks.com/books/4895003169"))
        self.assertTrue(is_ridi_title_url("http://ridibooks.com/books/4895003169/"))
        self.assertTrue(is_ridi_title_url("https://ridibooks.com/books/4895003169?from=test#details"))

    def test_recognizes_confirmed_viewer_url(self):
        self.assertTrue(is_ridi_chapter_url("https://ridibooks.com/books/4895003169/view"))
        self.assertTrue(is_ridi_chapter_url("http://ridibooks.com/books/4895003169/view/"))
        self.assertTrue(is_ridi_chapter_url("https://ridibooks.com/books/4895003169/view?chapter=1#reader"))

    def test_title_and_viewer_are_distinct(self):
        self.assertFalse(is_ridi_title_url("https://ridibooks.com/books/4895003169/view"))
        self.assertFalse(is_ridi_chapter_url("https://ridibooks.com/books/4895003169"))

    def test_rejects_unconfirmed_or_deceptive_hosts(self):
        rejected = (
            "https://www.ridibooks.com/books/4895003169",
            "https://example.com/books/4895003169",
            "https://ridibooks.com.example.com/books/4895003169",
            "https://user@ridibooks.com/books/4895003169",
            "https://ridibooks.com:443/books/4895003169",
        )
        for url in rejected:
            with self.subTest(url=url):
                self.assertFalse(is_ridi_title_url(url))

    def test_rejects_invalid_paths_and_values(self):
        rejected = (
            None,
            "",
            "ridibooks.com/books/4895003169",
            "https://ridibooks.com/books/not-numeric",
            "https://ridibooks.com/books/4895003169/extra",
            "https://ridibooks.com/other/4895003169/view",
        )
        for url in rejected:
            with self.subTest(url=url):
                self.assertFalse(is_ridi_title_url(url))
                self.assertFalse(is_ridi_chapter_url(url))

    def test_public_constants_are_conservative(self):
        self.assertEqual(RIDI_HOSTS, frozenset({"ridibooks.com"}))
        self.assertEqual(RIDI_PROFILE_RELATIVE_PATH, Path(".cache/ridibooks_chrome_profile"))
        self.assertEqual(RIDI_CDP_URL, "http://127.0.0.1:9222")
        self.assertEqual(RIDI_PAGE_ADVANCE_DELAY_MS, 1_000)


class RidiDiscoveryTests(unittest.TestCase):
    def test_discovers_only_explicit_viewer_rows_and_sorts(self):
        page = unittest.mock.MagicMock()
        page.url = "https://ridibooks.com/books/4895003169"
        page.evaluate.return_value = {
            "title": "죽어 마땅한 것들",
            "chapters": [
                {"number": 2, "title": "2화", "viewerUrl": "https://ridibooks.com/books/4895003199/view"},
                {"number": 1, "title": "1화", "viewerUrl": "https://ridibooks.com/books/4895003169/view"},
                {"number": 4, "title": "4화", "viewerUrl": "https://ridibooks.com/books/4895003203/view"},
                {"number": 3, "title": "3화", "viewerUrl": "https://ridibooks.com/books/4895003200/view"},
            ],
        }
        result = discover_ridi_chapters(page, "https://ridibooks.com/books/4895003169")
        self.assertEqual(result.title, "죽어 마땅한 것들")
        self.assertEqual([ch.number for ch in result.chapters], [1, 2, 3, 4])
        self.assertEqual(result.chapters[1].viewer_url, "https://ridibooks.com/books/4895003199/view")
        page.goto.assert_called_once()

    def test_rejects_conflicting_number_mapping(self):
        page = unittest.mock.MagicMock()
        page.url = "https://ridibooks.com/books/4895003169"
        page.evaluate.return_value = {"title": "Work", "chapters": [
            {"number": 1, "viewerUrl": "https://ridibooks.com/books/1/view"},
            {"number": 1, "viewerUrl": "https://ridibooks.com/books/2/view"},
        ]}
        with self.assertRaisesRegex(Exception, "conflicting viewer URLs"):
            discover_ridi_chapters(page, "https://ridibooks.com/books/4895003169")


class RidiProfileTests(unittest.TestCase):
    def test_resolves_profile_without_creating_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            expected = home / ".cache" / "ridibooks_chrome_profile"
            self.assertEqual(get_ridi_profile_dir(home), expected)
            self.assertFalse(expected.exists())


class RidiSessionTests(unittest.TestCase):
    def setUp(self):
        self.page = Mock(name="page")

    def test_without_probe_reports_pending_verification(self):
        with self.assertRaisesRegex(
            RidiSessionVerificationPendingError,
            "authentication indicator has not been established",
        ):
            require_usable_ridi_session(self.page)

    def test_true_probe_accepts_session(self):
        probe = Mock(return_value=True)
        require_usable_ridi_session(self.page, session_probe=probe)
        probe.assert_called_once_with(self.page)

    def test_false_probe_requires_manual_login(self):
        probe = Mock(return_value=False)
        with self.assertRaisesRegex(RidiSessionRequiredError, "complete login manually"):
            require_usable_ridi_session(self.page, session_probe=probe)

    def test_probe_exception_is_preserved(self):
        failure = ValueError("probe failed")

        def probe(_page):
            raise failure

        with self.assertRaises(ValueError) as raised:
            require_usable_ridi_session(self.page, session_probe=probe)
        self.assertIs(raised.exception, failure)


class RidiBrowserLifecycleTests(unittest.TestCase):
    def make_playwright(self, *, pages=None, launch_error=None):
        page = Mock(name="page")
        context = Mock(name="context")
        context.pages = [page] if pages is None else pages
        if not context.pages:
            context.new_page.return_value = page

        playwright = Mock(name="playwright")
        if launch_error is None:
            playwright.chromium.launch_persistent_context.return_value = context
        else:
            playwright.chromium.launch_persistent_context.side_effect = launch_error

        manager = Mock(name="playwright_manager")
        manager.start.return_value = playwright
        return manager, playwright, context, page

    def test_reuses_first_page_and_closes_owned_resources(self):
        manager, playwright, context, page = self.make_playwright()
        profile = Path("/tmp/ridi-test-profile")

        with patch("src.ridi_provider.sync_playwright", return_value=manager) as factory:
            with ridi_browser_page(user_data_dir=profile) as yielded:
                self.assertIs(yielded, page)

        factory.assert_called_once_with()
        manager.start.assert_called_once_with()
        playwright.chromium.launch_persistent_context.assert_called_once_with(
            user_data_dir=str(profile),
            channel="chrome",
            headless=False,
        )
        context.new_page.assert_not_called()
        context.close.assert_called_once_with()
        playwright.stop.assert_called_once_with()

    def test_creates_page_when_context_has_none(self):
        manager, _playwright, context, page = self.make_playwright(pages=[])
        with patch("src.ridi_provider.sync_playwright", return_value=manager):
            with ridi_browser_page(user_data_dir=Path("/tmp/ridi-test-profile")) as yielded:
                self.assertIs(yielded, page)
        context.new_page.assert_called_once_with()

    def test_body_failure_is_preserved_and_resources_close(self):
        manager, playwright, context, _page = self.make_playwright()
        failure = LookupError("caller failed")

        with patch("src.ridi_provider.sync_playwright", return_value=manager):
            with self.assertRaises(LookupError) as raised:
                with ridi_browser_page(user_data_dir=Path("/tmp/ridi-test-profile")):
                    raise failure

        self.assertIs(raised.exception, failure)
        context.close.assert_called_once_with()
        playwright.stop.assert_called_once_with()

    def test_launch_failure_is_preserved_and_playwright_stops(self):
        failure = RuntimeError("launch failed")
        manager, playwright, context, _page = self.make_playwright(launch_error=failure)

        with patch("src.ridi_provider.sync_playwright", return_value=manager):
            with self.assertRaises(RuntimeError) as raised:
                with ridi_browser_page(user_data_dir=Path("/tmp/ridi-test-profile")):
                    self.fail("context manager should not yield")

        self.assertIs(raised.exception, failure)
        context.close.assert_not_called()
        playwright.stop.assert_called_once_with()

    def test_cleanup_does_not_mask_body_failure(self):
        manager, playwright, context, _page = self.make_playwright()
        context.close.side_effect = RuntimeError("close failed")
        playwright.stop.side_effect = RuntimeError("stop failed")
        failure = KeyError("original")

        with patch("src.ridi_provider.sync_playwright", return_value=manager):
            with self.assertRaises(KeyError) as raised:
                with ridi_browser_page(user_data_dir=Path("/tmp/ridi-test-profile")):
                    raise failure

        self.assertIs(raised.exception, failure)
        context.close.assert_called_once_with()
        playwright.stop.assert_called_once_with()


class RidiCdpBrowserLifecycleTests(unittest.TestCase):
    def make_playwright(self, *, page_url="https://ridibooks.com/", pages=None, connect_error=None):
        page = Mock(name="page")
        page.url = page_url
        context = Mock(name="context")
        context.pages = [page] if pages is None else pages
        if not context.pages:
            context.new_page.return_value = page

        browser = Mock(name="browser")
        browser.contexts = [context]

        playwright = Mock(name="playwright")
        if connect_error is None:
            playwright.chromium.connect_over_cdp.return_value = browser
        else:
            playwright.chromium.connect_over_cdp.side_effect = connect_error

        manager = Mock(name="playwright_manager")
        manager.start.return_value = playwright
        return manager, playwright, browser, context, page

    def test_attaches_to_existing_ridi_page_without_closing_external_browser(self):
        manager, playwright, browser, context, page = self.make_playwright()

        with patch("src.ridi_provider.sync_playwright", return_value=manager):
            with ridi_cdp_browser_page() as yielded:
                self.assertIs(yielded, page)

        playwright.chromium.connect_over_cdp.assert_called_once_with(RIDI_CDP_URL)
        context.new_page.assert_not_called()
        browser.close.assert_not_called()
        context.close.assert_not_called()
        playwright.stop.assert_called_once_with()

    def test_creates_page_when_connected_context_has_no_ridi_page(self):
        other = Mock(name="other_page")
        other.url = "https://example.com/"
        manager, _playwright, browser, context, page = self.make_playwright(pages=[other])
        context.new_page.return_value = page

        with patch("src.ridi_provider.sync_playwright", return_value=manager):
            with ridi_cdp_browser_page(cdp_url="http://127.0.0.1:9333") as yielded:
                self.assertIs(yielded, page)

        context.new_page.assert_called_once_with()
        browser.close.assert_not_called()
        context.close.assert_not_called()

    def test_rejects_empty_cdp_url_before_starting_playwright(self):
        with patch("src.ridi_provider.sync_playwright") as factory:
            with self.assertRaises(ValueError):
                with ridi_cdp_browser_page(cdp_url=""):
                    self.fail("context manager should not yield")
        factory.assert_not_called()

    def test_connection_failure_is_preserved_and_playwright_stops(self):
        failure = RuntimeError("cdp failed")
        manager, playwright, _browser, _context, _page = self.make_playwright(connect_error=failure)

        with patch("src.ridi_provider.sync_playwright", return_value=manager):
            with self.assertRaises(RuntimeError) as raised:
                with ridi_cdp_browser_page():
                    self.fail("context manager should not yield")

        self.assertIs(raised.exception, failure)
        playwright.stop.assert_called_once_with()

    def test_body_failure_is_preserved_and_external_browser_remains_open(self):
        manager, playwright, browser, context, _page = self.make_playwright()
        failure = LookupError("caller failed")

        with patch("src.ridi_provider.sync_playwright", return_value=manager):
            with self.assertRaises(LookupError) as raised:
                with ridi_cdp_browser_page():
                    raise failure

        self.assertIs(raised.exception, failure)
        browser.close.assert_not_called()
        context.close.assert_not_called()
        playwright.stop.assert_called_once_with()


class RidiBlobCaptureTests(unittest.TestCase):
    @staticmethod
    def payload(data_index, content=b"jpeg-bytes", mime_type="image/jpeg"):
        return {
            "dataIndex": data_index,
            "mimeType": mime_type,
            "size": len(content),
            "base64": base64.b64encode(content).decode("ascii"),
        }

    def test_capture_store_preserves_original_bytes_and_hash(self):
        store = _CaptureStore()
        content = b"\xff\xd8\xfforiginal-jpeg"
        store.add_payload(self.payload(7, content))
        captured = store.get(7)
        self.assertIsNotNone(captured)
        self.assertEqual(captured.data_index, 7)
        self.assertEqual(captured.page_number, 8)
        self.assertEqual(captured.content, content)
        self.assertEqual(len(captured.sha256), 64)

    def test_capture_store_accepts_identical_recapture(self):
        store = _CaptureStore()
        payload = self.payload(3, b"same")
        store.add_payload(payload)
        store.add_payload(payload)
        self.assertEqual(store.indexes, (3,))

    def test_capture_store_rejects_conflicting_recapture(self):
        store = _CaptureStore()
        store.add_payload(self.payload(3, b"first"))
        with self.assertRaises(RidiCaptureConflictError):
            store.add_payload(self.payload(3, b"second"))

    def test_capture_store_rejects_size_mismatch(self):
        store = _CaptureStore()
        payload = self.payload(1, b"abc")
        payload["size"] = 999
        with self.assertRaisesRegex(RidiViewerCaptureError, "size mismatch"):
            store.add_payload(payload)

    def test_capture_store_rejects_non_image_blob(self):
        store = _CaptureStore()
        with self.assertRaisesRegex(RidiViewerCaptureError, "MIME"):
            store.add_payload(self.payload(1, b"abc", "application/octet-stream"))

    def test_instrumentation_is_installed_as_init_script_without_fetch_or_stealth(self):
        page = Mock(name="page")
        install_ridi_blob_capture(page)
        page.add_init_script.assert_called_once()
        script = page.add_init_script.call_args.args[0]
        self.assertIn("URL.createObjectURL", script)
        self.assertIn("value.arrayBuffer()", script)
        self.assertIn("img[data-index]", script)
        self.assertNotIn("fetch(", script)
        self.assertNotIn("AutomationControlled", script)
        self.assertNotIn("navigator.webdriver", script)


class RidiViewerStructureTests(unittest.TestCase):
    def make_page_with_indexes(self, values):
        page = Mock(name="page")
        page.locator.return_value.evaluate_all.return_value = values
        return page

    def test_reads_complete_zero_based_logical_index_set(self):
        page = self.make_page_with_indexes(["2", "0", "1", "2"])
        self.assertEqual(_read_expected_data_indexes(page), (0, 1, 2))

    def test_rejects_gap_in_logical_index_set(self):
        page = self.make_page_with_indexes(["0", "2"])
        with self.assertRaisesRegex(RidiViewerStructureError, "not contiguous"):
            _read_expected_data_indexes(page)

    def test_rejects_empty_logical_index_set(self):
        page = self.make_page_with_indexes([])
        with self.assertRaisesRegex(RidiViewerStructureError, "did not expose"):
            _read_expected_data_indexes(page)


class RidiCaptureResultTests(unittest.TestCase):
    @staticmethod
    def captured(index, content, mime_type="image/jpeg"):
        import hashlib

        return RidiCapturedPage(
            data_index=index,
            mime_type=mime_type,
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
        )

    def test_save_maps_zero_based_index_to_one_based_page_name_and_preserves_bytes(self):
        first = self.captured(0, b"\xff\xd8\xff-first")
        second = self.captured(1, b"\x89PNG\r\n\x1a\n-second", "image/png")
        result = RidiCaptureResult(expected_indexes=(0, 1), pages=(first, second))

        with tempfile.TemporaryDirectory() as temporary:
            saved = save_ridi_captured_pages(result, Path(temporary) / "chapter")
            self.assertEqual([path.name for path in saved], ["page-001.jpg", "page-002.png"])
            self.assertEqual(saved[0].read_bytes(), first.content)
            self.assertEqual(saved[1].read_bytes(), second.content)

    def test_save_rejects_incomplete_result_before_writing(self):
        first = self.captured(0, b"\xff\xd8\xff-first")
        result = RidiCaptureResult(expected_indexes=(0, 1), pages=(first,))
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "chapter"
            with self.assertRaises(RidiCaptureIncompleteError) as raised:
                save_ridi_captured_pages(result, target)
            self.assertEqual(raised.exception.missing, (1,))
            self.assertFalse(target.exists())

    def test_collect_reports_login_redirect_as_session_required(self):
        page = Mock(name="page")
        page.url = "https://ridibooks.com/account/login?return_url=%2Fbooks%2F4895003169%2Fview"

        with self.assertRaisesRegex(RidiSessionRequiredError, "redirected to the login page"):
            collect_ridi_viewer_pages(page, "https://ridibooks.com/books/4895003169/view")

        page.add_init_script.assert_called_once()
        page.wait_for_selector.assert_not_called()


    def test_collect_rejects_negative_page_advance_delay_before_touching_page(self):
        page = Mock(name="page")
        with self.assertRaisesRegex(ValueError, "page advance delay"):
            collect_ridi_viewer_pages(
                page,
                "https://ridibooks.com/books/4895003169/view",
                page_advance_delay_ms=-1,
            )
        page.add_init_script.assert_not_called()
        page.goto.assert_not_called()

    def test_collect_allows_zero_page_advance_delay(self):
        page = Mock(name="page")
        page.url = "https://ridibooks.com/books/4895003169/view"
        page.locator.return_value.evaluate_all.return_value = ["0"]

        payload = {
            "dataIndex": 0,
            "mimeType": "image/jpeg",
            "size": 4,
            "base64": base64.b64encode(b"jpeg").decode("ascii"),
        }
        page.evaluate.side_effect = [[payload], None]

        result = collect_ridi_viewer_pages(
            page,
            "https://ridibooks.com/books/4895003169/view",
            page_advance_delay_ms=0,
        )

        self.assertEqual(result.expected_indexes, (0,))
        self.assertEqual(len(result.pages), 1)
        page.wait_for_timeout.assert_not_called()

    def test_collect_separates_page_advance_delay_from_poll_interval(self):
        page = Mock(name="page")
        page.url = "https://ridibooks.com/books/4895003169/view"

        index_inventory = Mock(name="index_inventory")
        index_inventory.evaluate_all.return_value = ["0", "1"]
        locator_zero = Mock(name="locator_zero")
        locator_one = Mock(name="locator_one")
        locator_zero.first = locator_zero
        locator_one.first = locator_one

        def locator_side_effect(selector):
            if selector == "img[data-index]":
                return index_inventory
            if selector == 'img[data-index="0"]':
                return locator_zero
            if selector == 'img[data-index="1"]':
                return locator_one
            raise AssertionError(selector)

        page.locator.side_effect = locator_side_effect
        first_payload = {
            "dataIndex": 0,
            "mimeType": "image/jpeg",
            "size": 3,
            "base64": base64.b64encode(b"one").decode("ascii"),
        }
        second_payload = {
            "dataIndex": 1,
            "mimeType": "image/jpeg",
            "size": 3,
            "base64": base64.b64encode(b"two").decode("ascii"),
        }
        page.evaluate.side_effect = [[], [first_payload], [second_payload], [], None]

        result = collect_ridi_viewer_pages(
            page,
            "https://ridibooks.com/books/4895003169/view",
            poll_interval_ms=50,
            page_advance_delay_ms=1_000,
        )

        self.assertEqual(len(result.pages), 2)
        page.wait_for_timeout.assert_called_once_with(1_000)

    def test_collect_rejects_non_viewer_url_before_touching_page(self):
        page = Mock(name="page")
        with self.assertRaises(ValueError):
            collect_ridi_viewer_pages(page, "https://ridibooks.com/books/4895003169")
        page.add_init_script.assert_not_called()
        page.goto.assert_not_called()

    def test_get_ridi_session_status_reports_running_and_authenticated_without_exposing_cookie_value(self):
        fake_context = unittest.mock.MagicMock()
        fake_context.cookies.return_value = [
            {"name": "ridi_auth", "domain": ".ridibooks.com", "value": "secret"},
        ]
        fake_page = unittest.mock.MagicMock()
        fake_page.context = fake_context
        manager = unittest.mock.MagicMock()
        manager.__enter__.return_value = fake_page
        manager.__exit__.return_value = False

        with patch("src.ridi_provider.ridi_cdp_browser_page", return_value=manager):
            status = get_ridi_session_status()

        self.assertTrue(status["chrome_running"])
        self.assertTrue(status["authenticated"])
        self.assertNotIn("secret", repr(status))

    def test_start_ridi_chrome_does_not_launch_second_instance_when_cdp_is_running(self):
        running = {
            "chrome_running": True,
            "authenticated": False,
            "message": "Chrome RIDI aberto. Faça login no RIDI.",
        }
        with patch("src.ridi_provider.get_ridi_session_status", return_value=running), patch(
            "src.ridi_provider.subprocess.Popen"
        ) as popen:
            status = start_ridi_chrome()

        popen.assert_not_called()
        self.assertFalse(status["started"])


if __name__ == "__main__":
    unittest.main()

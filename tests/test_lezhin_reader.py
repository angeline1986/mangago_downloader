import pytest

from src.lezhin.errors import LezhinReaderError
from src.lezhin.reader import (read_cut_image, read_cut_indexes,
                               require_episode_access, wait_for_response)
from src.lezhin.session import lezhin_cdp_session


class FakePage:
    def __init__(self, rows):
        self.rows = rows

    def evaluate(self, _script):
        return self.rows

    def wait_for_function(self, _script, timeout):
        assert timeout > 0

    def locator(self, selector):
        return FakeLocator(selector, self.rows)

    def wait_for_timeout(self, _milliseconds):
        pass


class FakeLocator:
    def __init__(self, selector, rows):
        self.selector = selector
        self.rows = rows

    def evaluate_all(self, _script):
        wanted = self.selector.split('"')[1]
        return [row for row in self.rows if str(row["index"]) == wanted]


@pytest.mark.parametrize("rows", [
    [{"index": "0"}, {"index": "1"}, {"index": "2"}],
])
def test_reader_indexes_are_sorted_and_continuous(rows):
    assert read_cut_indexes(FakePage(rows)) == (0, 1, 2)


@pytest.mark.parametrize("rows", [
    [], [{"index": "0"}, {"index": "2"}],
    [{"index": "0"}, {"index": "0"}], [{"index": "x"}],
])
def test_reader_rejects_empty_missing_duplicate_or_invalid_indexes(rows):
    with pytest.raises(LezhinReaderError):
        read_cut_indexes(FakePage(rows))


def test_response_is_associated_by_exact_observed_image_url():
    response = object()
    responses = {"https://cdn.example/cut.webp?signature=hidden": [response]}
    found = wait_for_response(
        FakePage([]), responses,
        "https://cdn.example/cut.webp?signature=hidden", 1000, 3,
    )
    assert found is response
    assert responses == {}


def test_virtualized_image_is_read_again_from_the_requested_cut():
    rows = [
        {"index": "0", "src": "https://cdn.test/a.webp", "loaded": True},
        {"index": "1", "src": "https://cdn.test/b.webp", "loaded": True},
    ]
    page = FakePage(rows)
    assert read_cut_image(page, 1)["src"] == "https://cdn.test/b.webp"


def test_login_redirect_is_reported_before_reader_waits():
    with pytest.raises(LezhinReaderError, match="manual login"):
        require_episode_access("https://www.lezhinus.com/en/login")


def test_cdp_connection_failure_is_safe_and_does_not_echo_endpoint(monkeypatch):
    class Chromium:
        def connect_over_cdp(self, _endpoint):
            raise OSError("offline")

    class Driver:
        chromium = Chromium()
        def stop(self):
            pass

    class Starter:
        @staticmethod
        def start():
            return Driver()

    import src.lezhin.session as session
    monkeypatch.setattr(session, "sync_playwright", lambda: Starter())
    with pytest.raises(session.LezhinSessionError) as error:
        with lezhin_cdp_session("http://127.0.0.1:9223"):
            pass
    assert "127.0.0.1" not in str(error.value)


def test_session_disconnect_does_not_close_external_chrome_or_existing_page(monkeypatch):
    class Page:
        url = "https://www.lezhinus.com/en/comic/title/1"
        closed = False
        def set_default_timeout(self, _timeout):
            pass
        def close(self):
            self.closed = True

    class Context:
        pages = [Page()]

    class Browser:
        contexts = [Context()]
        closed = False
        def close(self):
            self.closed = True

    browser = Browser()
    class Chromium:
        def connect_over_cdp(self, _endpoint, no_defaults=False):
            assert no_defaults is True
            return browser

    class Driver:
        chromium = Chromium()
        stopped = False
        def stop(self):
            self.stopped = True

    driver = Driver()
    class Starter:
        @staticmethod
        def start():
            return driver

    import src.lezhin.session as session
    monkeypatch.setattr(session, "sync_playwright", lambda: Starter())
    with lezhin_cdp_session():
        pass
    assert not browser.closed
    assert not browser.contexts[0].pages[0].closed
    assert driver.stopped

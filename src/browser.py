"""Playwright browser helpers used by search and chapter scraping."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)


@contextmanager
def browser_page(*, headless: bool = True) -> Iterator[Page]:
    """Create an isolated Chromium page and clean it up deterministically."""
    playwright: Playwright = sync_playwright().start()
    browser: Browser | None = None
    context: BrowserContext | None = None
    try:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            viewport={"width": 1280, "height": 1800},
            ignore_https_errors=False,
        )
        page = context.new_page()
        page.set_default_timeout(15_000)
        yield page
    finally:
        if context is not None:
            context.close()
        if browser is not None:
            browser.close()
        playwright.stop()

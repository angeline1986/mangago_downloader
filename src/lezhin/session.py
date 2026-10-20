"""Attach Playwright to an externally owned, dedicated Lezhin Chrome."""
from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from .errors import LezhinSessionError
from .urls import is_lezhin_url


LEZHIN_CDP_URL = "http://127.0.0.1:9223"
LEZHIN_HOME_URL = "https://www.lezhinus.com/en"


def get_lezhin_cdp_url() -> str:
    """Read a loopback-only configurable endpoint, defaulting to the pilot port."""
    value = os.environ.get("LEZHIN_CDP_URL", LEZHIN_CDP_URL)
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.port != 9223):
        raise ValueError("LEZHIN_CDP_URL must use HTTP on a loopback address")
    if (parsed.path not in {"", "/"} or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError("LEZHIN_CDP_URL must be a plain loopback endpoint")
    return value.rstrip("/")


def get_lezhin_profile_dir(home: Path | None = None) -> Path:
    """Return the future dedicated profile location without creating it."""
    base = Path.home() if home is None else Path(home)
    override = os.environ.get("LEZHIN_CHROME_PROFILE")
    profile = (Path(override).expanduser() if override else
               base / ".mangago_downloader" / "lezhin-chrome-profile")
    protected = {
        base / ".cache" / "ridibooks_chrome_profile",
        base / "Library" / "Application Support" / "Google" / "Chrome" / "Default",
    }
    if profile.resolve() in {path.resolve() for path in protected}:
        raise ValueError("Lezhin profile must not reuse a Ridi or personal Chrome profile")
    return profile


@dataclass
class LezhinSession:
    browser: Browser
    context: BrowserContext
    page: Page
    owns_page: bool


@contextmanager
def lezhin_cdp_session(cdp_url: str | None = None) -> Iterator[LezhinSession]:
    """Connect to CDP without closing the browser or an existing user page."""
    endpoint = get_lezhin_cdp_url() if cdp_url is None else cdp_url
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.port != 9223 or parsed.path not in {"", "/"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Lezhin CDP endpoint must be loopback HTTP")
    playwright: Playwright | None = None
    session: LezhinSession | None = None
    try:
        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.connect_over_cdp(endpoint, no_defaults=True)
            if not browser.contexts:
                raise LezhinSessionError("Connected Chrome has no browser context")
            context = browser.contexts[0]
            page = next((item for item in context.pages if is_lezhin_url(item.url)), None)
            if page is None:
                raise LezhinSessionError(
                    "Nenhuma aba Lezhin está aberta. Clique em Iniciar Lezhin antes de Desvendar."
                )
            owns_page = False
            page.set_default_timeout(15_000)
            session = LezhinSession(browser, context, page, owns_page)
        except LezhinSessionError:
            raise
        except Exception as exc:
            raise LezhinSessionError(
                "Could not connect to the dedicated Lezhin Chrome session"
            ) from exc
        yield session
    finally:
        if session is not None and session.owns_page:
            try:
                session.page.close()
            except Exception:
                pass
        if playwright is not None:
            playwright.stop()

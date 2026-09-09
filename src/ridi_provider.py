"""Foundational RIDI URL, profile, browser, session, and viewer capture contracts."""
from __future__ import annotations

import base64
import binascii
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Callable, Dict, Iterator, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


RIDI_HOSTS = frozenset({"ridibooks.com"})
RIDI_PROFILE_RELATIVE_PATH = Path(".cache/ridibooks_chrome_profile")
RIDI_CDP_URL = "http://127.0.0.1:9222"
RIDI_HOME_URL = "https://ridibooks.com/"
RIDI_CHROME_MAC_PATH = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
RIDI_PAGE_ADVANCE_DELAY_MS = 1_000

_RIDI_TITLE_PATH_RE = re.compile(r"^/books/\d+/?$")
_RIDI_CHAPTER_PATH_RE = re.compile(r"^/books/\d+/view/?$")
_SUPPORTED_IMAGE_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


class RidiProviderError(RuntimeError):
    """Base exception for the RIDI provider."""


class RidiSessionVerificationPendingError(RidiProviderError):
    """Raised when no verified RIDI session indicator is available."""


class RidiSessionRequiredError(RidiProviderError):
    """Raised when an approved probe reports that RIDI login is required."""


class RidiViewerCaptureError(RidiProviderError):
    """Base exception for RIDI viewer capture failures."""


class RidiViewerStructureError(RidiViewerCaptureError):
    """Raised when the viewer does not expose the confirmed logical page structure."""


class RidiCaptureConflictError(RidiViewerCaptureError):
    """Raised when one data-index is observed with different image bytes."""


class RidiCaptureIncompleteError(RidiViewerCaptureError):
    """Raised when traversal finishes without capturing every expected data-index."""

    def __init__(self, expected: Sequence[int], captured: Sequence[int]):
        self.expected = tuple(expected)
        self.captured = tuple(captured)
        captured_set = set(self.captured)
        self.missing = tuple(index for index in self.expected if index not in captured_set)
        super().__init__(
            "RIDI viewer capture incomplete: "
            f"captured {len(self.captured)} of {len(self.expected)} page(s); "
            f"missing data-index values: {list(self.missing)}"
        )


SessionProbe = Callable[[Page], bool]


@dataclass(frozen=True)
class RidiDiscoveredChapter:
    """One chapter explicitly exposed by the RIDI work page with a viewer URL."""

    number: int
    title: str
    viewer_url: str


@dataclass(frozen=True)
class RidiDiscoveryResult:
    """Work metadata and chapters that RIDI currently exposes as directly viewable."""

    title: str
    work_url: str
    chapters: Tuple[RidiDiscoveredChapter, ...]


@dataclass(frozen=True)
class RidiCapturedPage:
    """One original image Blob correlated to its logical RIDI data-index."""

    data_index: int
    mime_type: str
    content: bytes
    sha256: str

    @property
    def page_number(self) -> int:
        return self.data_index + 1


@dataclass(frozen=True)
class RidiCaptureResult:
    """Complete in-memory RIDI viewer capture ordered by logical data-index."""

    expected_indexes: Tuple[int, ...]
    pages: Tuple[RidiCapturedPage, ...]

    @property
    def expected_pages(self) -> int:
        return len(self.expected_indexes)


class _CaptureStore:
    def __init__(self) -> None:
        self._pages: Dict[int, RidiCapturedPage] = {}

    @property
    def indexes(self) -> Tuple[int, ...]:
        return tuple(sorted(self._pages))

    def get(self, data_index: int) -> Optional[RidiCapturedPage]:
        return self._pages.get(data_index)

    def add_payload(self, payload: Mapping[str, object]) -> None:
        try:
            data_index = int(payload["dataIndex"])
            mime_type = str(payload["mimeType"] or "").lower()
            declared_size = int(payload["size"])
            encoded = str(payload["base64"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RidiViewerCaptureError(f"Invalid RIDI capture payload: {payload!r}") from exc

        if data_index < 0:
            raise RidiViewerCaptureError(f"Invalid RIDI data-index: {data_index}")
        if not mime_type.startswith("image/"):
            raise RidiViewerCaptureError(f"Unexpected RIDI Blob MIME type: {mime_type!r}")

        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise RidiViewerCaptureError(f"Invalid base64 payload for data-index {data_index}") from exc

        if len(content) != declared_size:
            raise RidiViewerCaptureError(
                f"RIDI Blob size mismatch for data-index {data_index}: "
                f"declared {declared_size}, decoded {len(content)}"
            )

        digest = hashlib.sha256(content).hexdigest()
        page = RidiCapturedPage(
            data_index=data_index,
            mime_type=mime_type,
            content=content,
            sha256=digest,
        )
        previous = self._pages.get(data_index)
        if previous is not None:
            if previous.sha256 != page.sha256 or previous.content != page.content:
                raise RidiCaptureConflictError(
                    f"RIDI data-index {data_index} was captured with different image bytes"
                )
            return
        self._pages[data_index] = page

    def ordered_pages(self, expected_indexes: Sequence[int]) -> Tuple[RidiCapturedPage, ...]:
        return tuple(self._pages[index] for index in expected_indexes if index in self._pages)


_RIDI_BLOB_CAPTURE_INIT_SCRIPT = r"""
(() => {
  if (window.top !== window) return;
  if (window.__ridiBlobCaptureInstalled) return;
  window.__ridiBlobCaptureInstalled = true;

  const records = new Map();
  const deliveries = [];
  const originalCreateObjectURL = URL.createObjectURL.bind(URL);

  function toBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    const chunkSize = 0x8000;
    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += chunkSize) {
      const chunk = bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length));
      binary += String.fromCharCode(...chunk);
    }
    return btoa(binary);
  }

  function maybeDeliver(record) {
    if (!record || record.delivered || record.dataIndex === null || record.base64 === null) return;
    record.delivered = true;
    deliveries.push({
      dataIndex: record.dataIndex,
      mimeType: record.mimeType,
      size: record.size,
      base64: record.base64,
    });
    records.delete(record.objectUrl);
    record.base64 = null;
  }

  function scanImages() {
    for (const image of document.querySelectorAll('img[data-index]')) {
      const rawIndex = image.getAttribute('data-index');
      if (rawIndex === null || !/^\d+$/.test(rawIndex)) continue;
      const sources = [image.currentSrc, image.src];
      for (const source of sources) {
        if (!source) continue;
        const record = records.get(source);
        if (!record) continue;
        record.dataIndex = Number(rawIndex);
        maybeDeliver(record);
      }
    }
  }

  URL.createObjectURL = function(value) {
    const objectUrl = originalCreateObjectURL(value);
    if (value instanceof Blob && typeof value.type === 'string' && value.type.startsWith('image/')) {
      const record = {
        objectUrl: objectUrl,
        dataIndex: null,
        mimeType: value.type,
        size: value.size,
        base64: null,
        delivered: false,
      };
      records.set(objectUrl, record);
      value.arrayBuffer().then((buffer) => {
        record.base64 = toBase64(buffer);
        scanImages();
        maybeDeliver(record);
      }).catch(() => {});
      setTimeout(scanImages, 0);
      setTimeout(scanImages, 5);
      setTimeout(scanImages, 25);
      setTimeout(scanImages, 100);
    }
    return objectUrl;
  };

  const observer = new MutationObserver(scanImages);
  const beginObservation = () => {
    if (document.documentElement) {
      observer.observe(document.documentElement, {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ['src', 'data-index'],
      });
      scanImages();
    }
  };
  if (document.documentElement) beginObservation();
  else document.addEventListener('DOMContentLoaded', beginObservation, {once: true});

  const intervalId = setInterval(scanImages, 50);

  window.__ridiCaptureDrain = function() {
    scanImages();
    return deliveries.splice(0, deliveries.length);
  };
  window.__ridiCaptureStop = function() {
    clearInterval(intervalId);
    observer.disconnect();
  };
})();
"""


def _is_ridi_url_with_path(url: Optional[str], path_pattern: re.Pattern[str]) -> bool:
    if not url:
        return False

    try:
        parsed = urlparse(url)
        port = parsed.port
    except (TypeError, ValueError):
        return False

    if parsed.scheme.lower() not in {"http", "https"}:
        return False
    if parsed.username is not None or parsed.password is not None or port is not None:
        return False
    if parsed.netloc.lower() not in RIDI_HOSTS:
        return False
    return path_pattern.fullmatch(parsed.path) is not None


def is_ridi_title_url(url: Optional[str]) -> bool:
    """Return True only for the confirmed RIDI title URL structure."""
    return _is_ridi_url_with_path(url, _RIDI_TITLE_PATH_RE)


def is_ridi_chapter_url(url: Optional[str]) -> bool:
    """Return True only for the confirmed RIDI viewer URL structure."""
    return _is_ridi_url_with_path(url, _RIDI_CHAPTER_PATH_RE)


def get_ridi_profile_dir(home: Optional[Path] = None) -> Path:
    """Return the dedicated RIDI Chrome profile path without creating it."""
    base = Path.home() if home is None else Path(home)
    return base.expanduser() / RIDI_PROFILE_RELATIVE_PATH



def _ridi_chrome_executable() -> Path:
    """Return the real Google Chrome executable used for the RIDI session."""
    override = os.environ.get("RIDI_CHROME_EXECUTABLE")
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return candidate
        raise RidiProviderError(f"RIDI_CHROME_EXECUTABLE does not exist: {candidate}")

    if sys.platform == "darwin" and RIDI_CHROME_MAC_PATH.is_file():
        return RIDI_CHROME_MAC_PATH

    for name in ("google-chrome", "google-chrome-stable", "chrome"):
        resolved = shutil.which(name)
        if resolved:
            return Path(resolved)

    raise RidiProviderError(
        "Google Chrome was not found. Install real Google Chrome or set "
        "RIDI_CHROME_EXECUTABLE."
    )


def get_ridi_session_status(*, cdp_url: str = RIDI_CDP_URL) -> dict:
    """Inspect the externally owned Chrome session without exposing cookie values."""
    try:
        with ridi_cdp_browser_page(cdp_url=cdp_url) as page:
            context = page.context
            cookies = context.cookies([RIDI_HOME_URL])
            authenticated = any(
                cookie.get("name") == "ridi_auth" and cookie.get("domain", "").endswith("ridibooks.com")
                for cookie in cookies
            )
            return {
                "chrome_running": True,
                "authenticated": authenticated,
                "message": "RIDI conectado." if authenticated else "Chrome RIDI aberto. Faça login no RIDI.",
            }
    except Exception:
        return {
            "chrome_running": False,
            "authenticated": False,
            "message": "Chrome RIDI não iniciado.",
        }


def start_ridi_chrome(
    *,
    cdp_url: str = RIDI_CDP_URL,
    user_data_dir: Optional[Path] = None,
) -> dict:
    """Start the dedicated real Chrome session used by RIDI, without owning its lifecycle."""
    current = get_ridi_session_status(cdp_url=cdp_url)
    if current["chrome_running"]:
        current["started"] = False
        return current

    profile = get_ridi_profile_dir() if user_data_dir is None else Path(user_data_dir).expanduser()
    executable = _ridi_chrome_executable()
    command = [
        str(executable),
        f"--user-data-dir={profile}",
        "--remote-debugging-port=9222",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        RIDI_HOME_URL,
    ]
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        status = get_ridi_session_status(cdp_url=cdp_url)
        if status["chrome_running"]:
            status["started"] = True
            return status
        time.sleep(0.25)

    return {
        "chrome_running": False,
        "authenticated": False,
        "started": True,
        "message": "Chrome RIDI iniciado; aguardando a porta CDP 9222 ficar disponível.",
    }


def require_usable_ridi_session(
    page: Page,
    *,
    session_probe: Optional[SessionProbe] = None,
) -> None:
    """Require an externally supplied, verified RIDI session probe."""
    if session_probe is None:
        raise RidiSessionVerificationPendingError(
            "A stable RIDI authentication indicator has not been established yet. "
            "Open real Chrome with the dedicated RIDI profile and complete login "
            "manually; automated session verification remains pending."
        )

    if not session_probe(page):
        raise RidiSessionRequiredError(
            "The RIDI session is not usable. Open real Chrome with the dedicated "
            "RIDI profile and complete login manually."
        )


@contextmanager
def ridi_browser_page(
    *,
    user_data_dir: Optional[Path] = None,
) -> Iterator[Page]:
    """Own one headed Chrome persistent context and yield one of its pages.

    This lifecycle remains available for dedicated-profile bootstrap/diagnostics.
    RIDI authentication uses a session cookie, so authenticated collection should
    attach to an already-open manually authenticated Chrome via
    :func:`ridi_cdp_browser_page` instead of closing and reopening this context.
    """
    profile = get_ridi_profile_dir() if user_data_dir is None else Path(user_data_dir).expanduser()
    playwright = sync_playwright().start()
    context = None
    active_error: Optional[BaseException] = None

    try:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            channel="chrome",
            headless=False,
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            yield page
        except BaseException as exc:
            active_error = exc
            raise
    except BaseException as exc:
        active_error = active_error or exc
        raise
    finally:
        cleanup_error: Optional[BaseException] = None
        if context is not None:
            try:
                context.close()
            except BaseException as exc:
                cleanup_error = exc
        try:
            playwright.stop()
        except BaseException as exc:
            if cleanup_error is None:
                cleanup_error = exc
        if active_error is None and cleanup_error is not None:
            raise cleanup_error


@contextmanager
def ridi_cdp_browser_page(
    *,
    cdp_url: str = RIDI_CDP_URL,
) -> Iterator[Page]:
    """Attach to an already-open real Chrome and yield a page from its session.

    The Chrome process and browser context are externally owned. This context
    manager only owns the Playwright driver connection and therefore never closes
    the browser or its context on exit. Manual RIDI login must already be active
    in that Chrome session.
    """
    if not cdp_url or not isinstance(cdp_url, str):
        raise ValueError("RIDI CDP URL must be a non-empty string")

    playwright = sync_playwright().start()
    active_error: Optional[BaseException] = None

    try:
        browser = playwright.chromium.connect_over_cdp(cdp_url)
        if not browser.contexts:
            raise RidiProviderError("Connected Chrome did not expose a browser context")

        context = browser.contexts[0]
        page = next((candidate for candidate in context.pages if _is_ridi_host_url(candidate.url)), None)
        if page is None:
            page = context.new_page()

        try:
            yield page
        except BaseException as exc:
            active_error = exc
            raise
    except BaseException as exc:
        active_error = active_error or exc
        raise
    finally:
        try:
            playwright.stop()
        except BaseException:
            if active_error is None:
                raise


def _is_ridi_host_url(url: Optional[str]) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme.lower() in {"http", "https"}
        and parsed.username is None
        and parsed.password is None
        and port is None
        and parsed.netloc.lower() in RIDI_HOSTS
    )


def _is_ridi_login_url(url: Optional[str]) -> bool:
    if not _is_ridi_host_url(url):
        return False
    parsed = urlparse(url)
    return parsed.path.rstrip("/") == "/account/login"


def discover_ridi_chapters(page: Page, work_url: str) -> RidiDiscoveryResult:
    """Discover only chapters with an explicit /books/<id>/view link on a RIDI work page.

    Paid/unavailable rows without a viewer link are intentionally ignored. Chapter
    identity comes from the same ``.table_wrapper`` that owns the viewer link; link
    order is never used to infer a chapter number.
    """
    if not is_ridi_title_url(work_url):
        raise ValueError(f"Unsupported RIDI work URL: {work_url!r}")

    page.goto(work_url, wait_until="domcontentloaded", timeout=30_000)
    if _is_ridi_login_url(page.url):
        raise RidiSessionRequiredError(
            "The RIDI work page redirected to login. Keep the authenticated Chrome "
            "session open and attach through ridi_cdp_browser_page()."
        )

    payload = page.evaluate(r"""
    () => {
      const title = (document.querySelector('h1')?.innerText || '').trim();
      const chapters = [];
      for (const link of document.querySelectorAll('a[href*="/books/"][href*="/view"]')) {
        const row = link.closest('.table_wrapper');
        if (!row) continue;
        const text = (row.innerText || row.textContent || '').replace(/\s+/g, ' ').trim();
        const match = text.match(/(\d+)화/);
        if (!match) continue;
        chapters.push({number: Number(match[1]), title: `${match[1]}화`, viewerUrl: link.href});
      }
      return {title, chapters};
    }
    """)
    if not isinstance(payload, dict):
        raise RidiProviderError("RIDI work discovery returned an unexpected payload")
    title = str(payload.get("title") or "").strip()
    if not title:
        raise RidiProviderError("RIDI work page did not expose a title in h1")

    by_number: Dict[int, RidiDiscoveredChapter] = {}
    by_url: Dict[str, int] = {}
    raw_chapters = payload.get("chapters") or []
    if not isinstance(raw_chapters, list):
        raise RidiProviderError("RIDI work discovery returned an invalid chapter list")
    for item in raw_chapters:
        if not isinstance(item, dict):
            raise RidiProviderError("RIDI work discovery returned an invalid chapter entry")
        try:
            number = int(item["number"])
            viewer_url = str(item["viewerUrl"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RidiProviderError("RIDI work discovery returned an invalid chapter entry") from exc
        if number <= 0 or not is_ridi_chapter_url(viewer_url):
            raise RidiProviderError("RIDI work discovery returned an invalid chapter identity")
        chapter = RidiDiscoveredChapter(number, str(item.get("title") or f"{number}화"), viewer_url)
        existing = by_number.get(number)
        if existing and existing.viewer_url != viewer_url:
            raise RidiProviderError(f"RIDI chapter {number} has conflicting viewer URLs")
        other_number = by_url.get(viewer_url)
        if other_number is not None and other_number != number:
            raise RidiProviderError(f"RIDI viewer URL is shared by chapters {other_number} and {number}")
        by_number[number] = chapter
        by_url[viewer_url] = number

    return RidiDiscoveryResult(title, work_url, tuple(by_number[n] for n in sorted(by_number)))


def install_ridi_blob_capture(page: Page) -> None:
    """Install pre-navigation Blob capture instrumentation for the next document."""
    page.add_init_script(_RIDI_BLOB_CAPTURE_INIT_SCRIPT)


def _read_expected_data_indexes(page: Page) -> Tuple[int, ...]:
    raw = page.locator("img[data-index]").evaluate_all(
        "elements => elements.map(el => el.getAttribute('data-index'))"
    )
    indexes = []
    for value in raw:
        if value is None or not str(value).isdigit():
            continue
        indexes.append(int(value))
    unique = tuple(sorted(set(indexes)))
    if not unique:
        raise RidiViewerStructureError("RIDI viewer did not expose any img[data-index] elements")
    expected = tuple(range(unique[-1] + 1))
    if unique != expected:
        missing = sorted(set(expected) - set(unique))
        raise RidiViewerStructureError(
            "RIDI viewer data-index sequence is not contiguous from zero; "
            f"missing values: {missing}"
        )
    return unique


def _drain_ridi_capture_events(page: Page, store: _CaptureStore) -> None:
    payloads = page.evaluate(
        "() => window.__ridiCaptureDrain ? window.__ridiCaptureDrain() : []"
    )
    if payloads is None:
        return
    if not isinstance(payloads, list):
        raise RidiViewerCaptureError("RIDI capture drain returned an unexpected value")
    for payload in payloads:
        if not isinstance(payload, dict):
            raise RidiViewerCaptureError(f"Invalid RIDI capture event: {payload!r}")
        store.add_payload(payload)


def collect_ridi_viewer_pages(
    page: Page,
    viewer_url: str,
    *,
    navigation_timeout_ms: int = 30_000,
    structure_timeout_ms: int = 15_000,
    per_page_timeout_ms: int = 5_000,
    poll_interval_ms: int = 50,
    page_advance_delay_ms: int = RIDI_PAGE_ADVANCE_DELAY_MS,
) -> RidiCaptureResult:
    """Capture every original image Blob in one RIDI viewer using data-index as identity.

    The caller must use a fresh page/document for this collection. Instrumentation is
    installed before navigation so short-lived Blob URLs do not need to be fetched.
    ``poll_interval_ms`` controls capture detection only. ``page_advance_delay_ms``
    independently enforces a fixed minimum pause between materialization attempts; it
    is deterministic rate limiting, not randomized human-behavior emulation.
    """
    if not is_ridi_chapter_url(viewer_url):
        raise ValueError(f"Unsupported RIDI viewer URL: {viewer_url!r}")
    if min(navigation_timeout_ms, structure_timeout_ms, per_page_timeout_ms, poll_interval_ms) <= 0:
        raise ValueError("RIDI capture timeouts and poll interval must be positive")
    if page_advance_delay_ms < 0:
        raise ValueError("RIDI page advance delay must be zero or positive")

    store = _CaptureStore()
    install_ridi_blob_capture(page)
    page.goto(viewer_url, wait_until="domcontentloaded", timeout=navigation_timeout_ms)
    if _is_ridi_login_url(page.url):
        raise RidiSessionRequiredError(
            "The RIDI viewer redirected to the login page. Open real Chrome with "
            "remote debugging enabled, complete RIDI login manually, keep Chrome "
            "open, and attach through ridi_cdp_browser_page()."
        )

    try:
        page.wait_for_selector("img[data-index]", timeout=structure_timeout_ms)
    except PlaywrightTimeoutError as exc:
        raise RidiViewerStructureError(
            "RIDI viewer did not expose img[data-index] before the structure timeout"
        ) from exc

    expected_indexes = _read_expected_data_indexes(page)
    _drain_ridi_capture_events(page, store)

    materialization_attempted = False
    for data_index in expected_indexes:
        if store.get(data_index) is not None:
            continue

        if materialization_attempted and page_advance_delay_ms:
            page.wait_for_timeout(page_advance_delay_ms)

        locator = page.locator(f'img[data-index="{data_index}"]').first
        locator.scroll_into_view_if_needed(timeout=per_page_timeout_ms)
        try:
            locator.evaluate(
                "el => el.scrollIntoView({block: 'center', inline: 'nearest', behavior: 'auto'})"
            )
        except Exception:
            # scroll_into_view_if_needed already performed the required materialization attempt.
            pass
        materialization_attempted = True

        deadline = time.monotonic() + (per_page_timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            _drain_ridi_capture_events(page, store)
            if store.get(data_index) is not None:
                break
            page.wait_for_timeout(poll_interval_ms)

    _drain_ridi_capture_events(page, store)
    try:
        page.evaluate("() => window.__ridiCaptureStop && window.__ridiCaptureStop()")
    except Exception:
        pass

    captured_indexes = store.indexes
    if captured_indexes != expected_indexes:
        raise RidiCaptureIncompleteError(expected_indexes, captured_indexes)

    return RidiCaptureResult(
        expected_indexes=expected_indexes,
        pages=store.ordered_pages(expected_indexes),
    )


def _extension_for_capture(page: RidiCapturedPage) -> str:
    extension = _SUPPORTED_IMAGE_EXTENSIONS.get(page.mime_type.lower())
    if extension:
        return extension
    content = page.content
    if content.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "webp"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    raise RidiViewerCaptureError(
        f"Unsupported RIDI image format for data-index {page.data_index}: {page.mime_type!r}"
    )


def save_ridi_captured_pages(result: RidiCaptureResult, output_dir: Path) -> Tuple[Path, ...]:
    """Persist a complete RIDI capture as page-001.* while preserving Blob bytes."""
    if len(result.pages) != len(result.expected_indexes):
        raise RidiCaptureIncompleteError(
            result.expected_indexes,
            tuple(page.data_index for page in result.pages),
        )

    by_index = {page.data_index: page for page in result.pages}
    if tuple(sorted(by_index)) != result.expected_indexes:
        raise RidiCaptureIncompleteError(result.expected_indexes, tuple(sorted(by_index)))

    destination = Path(output_dir).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    saved = []
    for data_index in result.expected_indexes:
        capture = by_index[data_index]
        extension = _extension_for_capture(capture)
        target = destination / f"page-{capture.page_number:03d}.{extension}"
        temporary = target.with_name(target.name + ".part")
        temporary.write_bytes(capture.content)
        temporary.replace(target)
        saved.append(target)
    return tuple(saved)


def download_ridi_chapter(downloader, manga, chapter, progress_callback=None):
    """Capture one RIDI viewer chapter through CDP and use shared save/validation."""
    if not is_ridi_chapter_url(getattr(chapter, "url", None)):
        raise RidiViewerCaptureError("RIDI chapter download requires a confirmed /books/<id>/view URL.")

    from .chapter_validation import remove_download_complete_marker, write_download_in_progress_marker
    from .models import DownloadResult
    from .output_paths import chapter_image_dir
    from .utils import create_directory, sanitize_filename

    chapter_dir = str(chapter_image_dir(
        downloader.download_dir, "ridi", sanitize_filename(manga.title),
        sanitize_filename(f"Ch. {chapter.number:g}"),
    ))
    create_directory(chapter_dir)
    remove_download_complete_marker(chapter_dir)
    callback = progress_callback or getattr(downloader, "progress_callback", None)

    try:
        with ridi_cdp_browser_page() as page:
            capture = collect_ridi_viewer_pages(page, chapter.url)
        expected = capture.expected_pages
        write_download_in_progress_marker(chapter_dir, expected_pages=expected)
        originals_dir = str(Path(chapter_dir) / "originais")
        if downloader.keep_originals and downloader.image_format == "png":
            create_directory(originals_dir)
        for done, captured_page in enumerate(capture.pages, start=1):
            downloader._save_image_bytes(
                captured_page.content, captured_page.mime_type, chapter_dir,
                originals_dir, captured_page.page_number,
            )
            if callback:
                callback(chapter, done, expected)
        result = DownloadResult(
            chapter=chapter, success=True, file_path=chapter_dir,
            images_downloaded=expected, expected_pages=expected,
        )
        return downloader._finalize_download_result(result, expected_pages=expected)
    except Exception as exc:
        return DownloadResult(
            chapter=chapter, success=False, file_path=chapter_dir, error_message=str(exc)
        )

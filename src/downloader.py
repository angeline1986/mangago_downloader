"""Chapter discovery, image location and validated image downloading."""
from __future__ import annotations

import io
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Union
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from PIL import Image, UnidentifiedImageError

from .browser import browser_page
from .comix_provider import download_comix_chapter, is_comix_chapter_url
from .models import Chapter, Manga, DownloadResult
from .chapter_validation import (
    remove_download_complete_marker,
    validate_chapter_images,
    write_download_complete_marker,
    write_download_in_progress_marker,
)
from .output_paths import chapter_image_dir
from .utils import SessionManager, ParsingError, DownloadError, create_directory, sanitize_filename

IMAGE_HOST_HINTS = ("mangapicgallery.com", "mangago", "youhim")
SUPPORTED_IMAGE_MODES = {"original", "png"}

logger = logging.getLogger("mangago.engine")


def _chapter_dir_name(chapter: Chapter) -> str:
    return sanitize_filename(f"Ch. {chapter.number:g}")


def _page_number_from_url(url: str) -> Optional[int]:
    match = re.search(r"/pg-(\d+)/?", url)
    return int(match.group(1)) if match else None


def _chapter_identity(url: str) -> str:
    """Return the path portion that identifies a chapter independently of /pg-N/."""
    path = urlparse(url).path
    return re.sub(r"/pg-\d+/?$", "", path.rstrip("/"))


def _is_image_url(url: Optional[str]) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    host = urlparse(url).netloc.lower()
    return any(hint in host for hint in IMAGE_HOST_HINTS) or bool(
        re.search(r"\.(?:jpe?g|png|webp|gif)(?:\?|$)", url, re.I)
    )


def _is_reader_page_url(url: Optional[str]) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.netloc.lower().endswith("mangago.me") and _page_number_from_url(url) is not None


def _extract_current_mangago_image(page, page_number: Optional[int]) -> Optional[str]:
    """Playwright equivalent of the proven console locator strategy."""
    candidates: List[str] = []
    if page_number is not None:
        candidates.extend([
            f"#pic_container img#page{page_number}",
            f"#pic_container img.page{page_number}",
        ])
    candidates.extend([
        "#pic_container img:visible",
        '#pic_container img[src*="mangapicgallery.com"]',
    ])

    for selector in candidates:
        locator = page.locator(selector)
        count = locator.count()
        for idx in range(count):
            src = locator.nth(idx).get_attribute("src") or locator.nth(idx).get_attribute("data-src")
            if _is_image_url(src):
                return src
    return None


def _collect_longstrip_images(page) -> List[str]:
    """Scroll a long-strip reader and collect unique content image URLs in DOM order."""
    previous = -1
    stable = 0
    for _ in range(120):
        page.evaluate("window.scrollBy(0, Math.max(window.innerHeight * 0.85, 700))")
        page.wait_for_timeout(180)
        count = page.locator("#pic_container img, img[id^='page'], img[src*='mangapicgallery.com']").count()
        if count == previous:
            stable += 1
            if stable >= 4:
                break
        else:
            stable = 0
            previous = count
    page.evaluate("window.scrollTo(0, 0)")

    urls: List[str] = []
    seen = set()
    locator = page.locator("#pic_container img, img[id^='page'], img[src*='mangapicgallery.com']")
    for idx in range(locator.count()):
        src = locator.nth(idx).get_attribute("src") or locator.nth(idx).get_attribute("data-src")
        if _is_image_url(src) and src not in seen:
            seen.add(src)
            urls.append(src)
    return urls


def _extract_reader_page_links(html: str, base_url: str) -> List[str]:
    """Return the ordered page URLs exposed by Mangago's page dropdown."""
    soup = BeautifulSoup(html, "html.parser")
    menu = soup.select_one("#dropdown-menu-page")
    if not menu:
        return []

    found = []
    seen = set()
    for link in menu.select("a[href]"):
        href = link.get("href")
        if not isinstance(href, str):
            continue
        url = urljoin(base_url, href)
        if _page_number_from_url(url) is None or url in seen:
            continue
        seen.add(url)
        found.append(url)
    return sorted(found, key=lambda url: _page_number_from_url(url) or 0)


def _extract_reader_chapter_label(html: str) -> Optional[str]:
    """Read the visible chapter label from #navi when available (for diagnostics)."""
    soup = BeautifulSoup(html, "html.parser")
    navi = soup.select_one("#navi h3")
    if not navi:
        return None
    for span in reversed(navi.select("span")):
        text = span.get_text(" ", strip=True)
        if re.search(r"\bCh\.?\s*\d", text, re.I):
            return text
    return None


def _extract_image_from_reader_html(html: str, page_url: str) -> Optional[str]:
    """Extract the content image URL from server-rendered Mangago reader HTML."""
    soup = BeautifulSoup(html, "html.parser")
    number = _page_number_from_url(page_url)
    selectors = []
    if number is not None:
        selectors.extend([f"#pic_container img#page{number}", f"#pic_container img.page{number}"])
    selectors.extend(["#pic_container img", "img[id^='page']"])
    for selector in selectors:
        for image in soup.select(selector):
            src = image.get("src") or image.get("data-src")
            if isinstance(src, str):
                src = urljoin(page_url, src)
                if _is_image_url(src):
                    return src
    return None


def _cookie_header_from_context(context) -> str:
    cookies = []
    try:
        cookies = context.cookies()
    except Exception:
        return ""
    return "; ".join(
        f"{cookie.get('name')}={cookie.get('value')}"
        for cookie in cookies
        if cookie.get("name") and cookie.get("value") is not None
    )


def _discover_chapter_reader_pages(chapter_url: str, timeout: int = 30) -> tuple[List[str], str]:
    """Open a chapter once and return ordered reader page URLs plus cookies."""
    if not chapter_url:
        raise ParsingError("Chapter URL is invalid.")

    discovery_started = time.monotonic()
    logger.info("[DISCOVERY] capítulo iniciado: %s", chapter_url)

    with browser_page(headless=True) as page:
        page.goto(chapter_url, wait_until="domcontentloaded", timeout=max(1, int(timeout)) * 1000)
        page.locator("body").wait_for(state="attached")

        domain = urlparse(page.url).netloc.lower()
        if domain.endswith("mangago.me") and "/pg-" in page.url:
            initial_url = page.url
            original_identity = _chapter_identity(initial_url)
            initial_html = page.content()
            page_urls = _extract_reader_page_links(initial_html, initial_url)

            if not page_urls:
                src = _extract_current_mangago_image(page, _page_number_from_url(initial_url))
                if not src:
                    raise ParsingError("No chapter images found in Mangago reader.")
                logger.info("[DISCOVERY] 1 página encontrada sem dropdown")
                return [src], _cookie_header_from_context(page.context)

            page_urls = [url for url in page_urls if _chapter_identity(url) == original_identity]
            if not page_urls:
                raise ParsingError("Mangago page selector did not contain pages from the current chapter.")

            cookie_header = _cookie_header_from_context(page.context)
            if cookie_header:
                logger.info("[DISCOVERY] cookies do BrowserContext transferidos para HTTP")
            logger.info("[DISCOVERY] %s páginas encontradas em %.2fs", len(page_urls), time.monotonic() - discovery_started)
            return page_urls, cookie_header

        urls = _collect_longstrip_images(page)
        if not urls:
            raise ParsingError("No chapter images found.")
        logger.info("[DISCOVERY] %s imagem(ns) encontradas em leitor alternativo", len(urls))
        return urls, _cookie_header_from_context(page.context)


def discover_chapter_reader_pages(chapter_url: str, timeout: int = 30) -> List[str]:
    """Open a chapter once and return the ordered reader page URLs."""
    page_urls, _cookie_header = _discover_chapter_reader_pages(chapter_url, timeout)
    return page_urls


def discover_chapter_reader_pages_with_cookies(chapter_url: str, timeout: int = 30) -> tuple[List[str], str]:
    """Open a chapter once and return reader page URLs with BrowserContext cookies."""
    return _discover_chapter_reader_pages(chapter_url, timeout)


def fetch_chapter_image_urls(chapter_url: str, max_workers: int = 3, timeout: int = 30) -> List[str]:
    """Compatibility wrapper: return reader page URLs without resolving images."""
    if is_comix_chapter_url(chapter_url):
        return [chapter_url]
    return discover_chapter_reader_pages(chapter_url, timeout=timeout)

def _parse_chapters_from_html(html: str, base_url: str) -> List[Chapter]:
    soup = BeautifulSoup(html, "html.parser")
    chapters: List[Chapter] = []

    table = soup.find("table", class_="listing")
    if isinstance(table, Tag):
        links = table.select("a.chico")
    else:
        links = soup.find_all("a", href=re.compile(r"/(?:read-manga|chapter)/"))

    seen = set()
    for link in links:
        title = link.get_text(" ", strip=True)
        href = link.get("href")
        if not isinstance(href, str) or not title:
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        match = re.search(r"(?:Ch\.?|Chapter\s*)(\d+(?:\.\d+)?)", title, re.I)
        if not match:
            continue
        number = float(match.group(1))
        chapters.append(Chapter(number=number, title=title, url=url))
    return sorted(chapters, key=lambda ch: ch.number)


def get_chapter_list(source: Union[str, object]) -> List[Chapter]:
    """Fetch chapter list. Accepts a manga URL; legacy caller handles remain tolerated."""
    manga_url = source if isinstance(source, str) else getattr(source, "current_url", None)
    if not manga_url:
        raise DownloadError("Could not determine manga URL for chapter listing.")

    with browser_page(headless=True) as page:
        page.goto(manga_url, wait_until="domcontentloaded", timeout=30_000)
        page.locator("body").wait_for(state="attached")

        # Some Mangago pages hide older chapters behind a JS button.
        show_all = page.locator("a[onclick*='showAllChapters']")
        if show_all.count():
            try:
                show_all.first.click(timeout=4_000)
                page.wait_for_timeout(500)
            except Exception:
                pass
        return _parse_chapters_from_html(page.content(), page.url)


class ChapterDownloader:
    """Download chapter images with validation and optional lossless PNG conversion."""


    def _finalize_download_result(
        self,
        result: DownloadResult,
        expected_pages: int | None = None,
    ) -> DownloadResult:
        """Validate the saved chapter before treating the download as complete."""
        expected = (
            int(expected_pages)
            if expected_pages is not None
            else int(result.expected_pages or 0)
        )

        result.expected_pages = expected

        if not result.file_path or expected <= 0:
            return result

        validation = validate_chapter_images(
            result.file_path,
            expected_pages=expected,
        )
        result.validation = validation

        if not validation.valid:
            result.success = False

            details = []

            if validation.missing_pages:
                details.append(
                    "missing pages: "
                    + ", ".join(map(str, validation.missing_pages))
                )

            if validation.invalid_pages:
                details.append(
                    "invalid pages: "
                    + ", ".join(map(str, validation.invalid_pages))
                )

            if validation.duplicate_pages:
                details.append(
                    "duplicate pages: "
                    + ", ".join(map(str, validation.duplicate_pages))
                )

            if validation.found_pages != validation.expected_pages:
                details.append(
                    f"found {validation.found_pages}/"
                    f"{validation.expected_pages} pages"
                )

            message = "Chapter structural validation failed"
            if details:
                message += ": " + "; ".join(details)

            if result.error_message:
                result.error_message += f" | {message}"
            else:
                result.error_message = message

        if validation.valid and result.success:
            write_download_complete_marker(
                result.file_path,
                validation.expected_pages,
            )

        return result

    def __init__(
        self,
        max_workers: int = 5,
        download_dir: str = "downloads",
        image_format: str = "original",
        keep_originals: bool = False,
        page_delay: float = 2.0,
        retry_count: int = 3,
        timeout: int = 30,
        progress_callback=None,
    ):
        self.max_workers = max(1, min(3, int(max_workers)))
        self.download_dir = download_dir
        self.image_format = image_format if image_format in SUPPORTED_IMAGE_MODES else "original"
        self.keep_originals = bool(keep_originals)
        self.page_delay = max(0.0, float(page_delay))
        self.retry_count = max(0, int(retry_count))
        self.timeout = max(1, int(timeout))
        self.progress_callback = progress_callback
        self.session = SessionManager(timeout=self.timeout)
        # Guard the original SessionManager.get implementation. Tests and callers
        # may intentionally replace ``session`` or monkeypatch ``session.get``.
        # In that case the injected session must remain authoritative even when
        # page downloads run in executor threads.
        self._session_get_func = getattr(self.session.get, "__func__", None)
        self._session_owner_thread = threading.get_ident()
        self._thread_local = threading.local()
        self._sessions = []
        self._sessions_lock = threading.Lock()
        self._rate_lock = threading.Lock()
        self._last_request_at = 0.0


    # DOWNLOAD_ENGINE_V4_PLAYWRIGHT_READER
    def _download_reader_chapter_playwright(self, manga: Manga, chapter: Chapter, progress_callback=None) -> DownloadResult:
        """Resolve Mangago reader pages in a real browser, then download image bytes over HTTP.

        V4 intentionally keeps reader-page rendering in Playwright because Mangago returns
        HTTP 403 to direct reader-page requests even when browser cookies are forwarded.
        A single Chromium BrowserContext is reused with at most three Playwright pages.
        """
        import asyncio

        return asyncio.run(
            self._download_reader_chapter_playwright_async(
                manga,
                chapter,
                progress_callback=progress_callback,
            )
        )

    async def _download_reader_chapter_playwright_async(
        self,
        manga: Manga,
        chapter: Chapter,
        progress_callback=None,
    ) -> DownloadResult:
        import asyncio
        import logging

        from playwright.async_api import async_playwright
        from .browser import DEFAULT_USER_AGENT

        logger = logging.getLogger("mangago.engine")
        page_urls = list(chapter.image_urls or [])
        if not page_urls:
            return DownloadResult(chapter=chapter, success=False, error_message="No reader pages found.")

        chapter_dir = str(
            chapter_image_dir(
                self.download_dir,
                "mangago",
                sanitize_filename(manga.title),
                _chapter_dir_name(chapter),
            )
        )
        create_directory(chapter_dir)
        remove_download_complete_marker(chapter_dir)
        write_download_in_progress_marker(
            chapter_dir,
            expected_pages=len(page_urls),
        )
        originals_dir = os.path.join(chapter_dir, "originais")
        if self.keep_originals and self.image_format == "png":
            create_directory(originals_dir)

        worker_count = max(1, min(3, int(getattr(self, "max_workers", 3))))
        timeout_seconds = max(1, int(getattr(self, "timeout", 30)))
        timeout_ms = timeout_seconds * 1000
        retry_count = max(0, int(getattr(self, "retry_count", 3)))
        callback = progress_callback or getattr(self, "progress_callback", None)
        failures: List[str] = []
        downloaded = 0
        queue: asyncio.Queue = asyncio.Queue()
        rate_lock = asyncio.Lock()
        last_page_start: Optional[float] = None
        for index, reader_url in enumerate(page_urls, start=1):
            queue.put_nowait((index, reader_url))

        async def wait_for_page_slot(page_number: int) -> None:
            nonlocal last_page_start
            if self.page_delay <= 0:
                return
            async with rate_lock:
                now = time.monotonic()
                if last_page_start is not None:
                    elapsed = now - last_page_start
                    wait_time = self.page_delay - elapsed
                    if wait_time > 0:
                        await asyncio.sleep(wait_time)
                        now = time.monotonic()
                interval = None if last_page_start is None else now - last_page_start
                last_page_start = now
                if interval is None:
                    print(f"[V4.1][RATE][PAGE {page_number:03d}] liberada | monotonic={now:.3f}", flush=True)
                else:
                    print(f"[V4.1][RATE][PAGE {page_number:03d}] liberada | intervalo={interval:.3f}s", flush=True)

        async def locate_image(page, reader_url: str, index: int) -> str:
            page_number = _page_number_from_url(reader_url) or index
            candidates = [
                f"#pic_container img#page{page_number}",
                f"#pic_container img.page{page_number}",
                "#pic_container img:visible",
                '#pic_container img[src*="mangapicgallery.com"]',
                "#pic_container img",
                "img[id^='page']",
            ]
            await page.locator("#pic_container").wait_for(state="attached", timeout=timeout_ms)
            for selector in candidates:
                locator = page.locator(selector)
                count = await locator.count()
                for item_index in range(count):
                    item = locator.nth(item_index)
                    src = (
                        await item.get_attribute("src")
                        or await item.get_attribute("data-src")
                        or await item.get_attribute("lazy-src")
                    )
                    if not _is_image_url(src):
                        try:
                            src = await item.evaluate("(img) => img.currentSrc || ''")
                        except Exception:
                            src = None
                    if _is_image_url(src):
                        return str(src)
            raise ParsingError(f"reader page {page_number} did not expose an image URL in Playwright DOM")

        # DOWNLOAD_ENGINE_V4_1_DIAGNOSTIC
        print("[V4.1] async_playwright: iniciando", flush=True)
        async with async_playwright() as playwright:
            print("[V4.1] Chromium: iniciando", flush=True)
            browser = await playwright.chromium.launch(headless=True)
            print("[V4.1] Chromium: iniciado", flush=True)
            context = await browser.new_context(
                user_agent=DEFAULT_USER_AGENT,
                viewport={"width": 1280, "height": 1800},
                ignore_https_errors=False,
            )
            print(f"[V4.1] BrowserContext: criado | workers={worker_count} | páginas={len(page_urls)}", flush=True)
            try:
                async def worker(worker_id: int) -> None:
                    nonlocal downloaded
                    print(f"[V4.1][W{worker_id}] criando Page", flush=True)
                    page = await context.new_page()
                    print(f"[V4.1][W{worker_id}] Page criada", flush=True)
                    page.set_default_timeout(timeout_ms)
                    try:
                        while True:
                            try:
                                index, reader_url = queue.get_nowait()
                            except asyncio.QueueEmpty:
                                return

                            page_number = _page_number_from_url(reader_url) or index
                            await wait_for_page_slot(page_number)
                            logger.info("[PAGE %03d] iniciando via Playwright", page_number)
                            print(f"[V4.1][PAGE {page_number:03d}] iniciando | {reader_url}", flush=True)
                            try:
                                image_url = None
                                last_error = None
                                for attempt in range(retry_count + 1):
                                    try:
                                        print(f"[V4.1][PAGE {page_number:03d}] goto: iniciando", flush=True)
                                        response = await page.goto(
                                            reader_url,
                                            wait_until="domcontentloaded",
                                            timeout=timeout_ms,
                                        )
                                        status = response.status if response is not None else None
                                        print(f"[V4.1][PAGE {page_number:03d}] goto: concluído | status={status} | url={page.url}", flush=True)
                                        print(f"[V4.1][PAGE {page_number:03d}] locate_image: iniciando", flush=True)
                                        image_url = await locate_image(page, reader_url, index)
                                        logger.info("[PAGE %03d] imagem localizada", page_number)
                                        print(f"[V4.1][PAGE {page_number:03d}] imagem localizada | {image_url}", flush=True)
                                        break
                                    except Exception as exc:
                                        last_error = exc
                                        if attempt >= retry_count:
                                            raise
                                        delay = min(4.0, 0.5 * (2 ** attempt))
                                        logger.warning(
                                            "[PAGE %03d] retry Playwright %d/%d: %s",
                                            page_number,
                                            attempt + 1,
                                            retry_count,
                                            exc,
                                        )
                                        await asyncio.sleep(delay)

                                if not image_url:
                                    raise last_error or ParsingError("Image URL was not resolved.")

                                print(f"[V4.1][PAGE {page_number:03d}] imagem request: iniciando", flush=True)
                                image_response = await context.request.get(
                                    image_url,
                                    headers={
                                        "Referer": f"{urlparse(reader_url).scheme}://{urlparse(reader_url).netloc}/",
                                        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                                    },
                                    timeout=timeout_ms,
                                )
                                print(f"[V4.1][PAGE {page_number:03d}] imagem request: status={image_response.status}", flush=True)
                                if not image_response.ok:
                                    raise DownloadError(f"image request returned HTTP {image_response.status}")
                                raw = await image_response.body()
                                print(f"[V4.1][PAGE {page_number:03d}] bytes recebidos | {len(raw)} bytes", flush=True)
                                await asyncio.to_thread(
                                    self._save_image_bytes,
                                    raw,
                                    image_response.headers.get("content-type", ""),
                                    chapter_dir,
                                    originals_dir,
                                    index,
                                )
                                print(f"[V4.1][PAGE {page_number:03d}] arquivo salvo", flush=True)
                                downloaded += 1
                                if callback:
                                    callback(chapter, downloaded, len(page_urls))
                                logger.info("[PAGE %03d] concluída (%d/%d)", page_number, downloaded, len(page_urls))
                                print(f"[V4.1][PAGE {page_number:03d}] concluída", flush=True)
                            except Exception as exc:
                                failures.append(f"page {index}: {exc}")
                                print(f"[V4.1][PAGE {page_number:03d}] ERRO {type(exc).__name__}: {exc}", flush=True)
                                logger.exception("[PAGE %03d] erro: %s", page_number, exc)
                            finally:
                                queue.task_done()
                    finally:
                        await page.close()

                print(f"[V4.1] fila: iniciando {worker_count} worker(s)", flush=True)
                workers = [asyncio.create_task(worker(i + 1)) for i in range(worker_count)]
                await queue.join()
                print("[V4.1] fila: queue.join concluído", flush=True)
                await asyncio.gather(*workers)
                print("[V4.1] workers: gather concluído", flush=True)
            finally:
                await context.close()
                await browser.close()

        success = downloaded == len(page_urls)
        result = DownloadResult(
            chapter=chapter,
            success=success,
            file_path=chapter_dir,
            images_downloaded=downloaded,
            expected_pages=len(page_urls),
            error_message=None if success else "; ".join(failures[:5]),
        )
        return self._finalize_download_result(
            result,
            expected_pages=len(page_urls),
        )

    def download_chapter(self, manga: Manga, chapter: Chapter, progress_callback=None) -> DownloadResult:
        """Download a chapter with a bounded page queue.

        The queue accepts either direct image URLs or Mangago reader page URLs. Reader
        pages are resolved inside the page worker so progress starts as soon as the
        dropdown has been discovered.
        """
        if is_comix_chapter_url(chapter.url):
            return download_comix_chapter(
                self, manga, chapter, progress_callback=progress_callback
            )
        # V4: Mangago reader pages must be rendered by a real browser; direct HTTP returns 403.
        if chapter.image_urls and all(_is_reader_page_url(url) for url in chapter.image_urls):
            return self._download_reader_chapter_playwright(
                manga, chapter, progress_callback=progress_callback
            )
        if not chapter.image_urls:
            return DownloadResult(chapter=chapter, success=False, error_message="No image URLs found.")

        chapter_dir = str(
            chapter_image_dir(
                self.download_dir,
                "mangago",
                sanitize_filename(manga.title),
                _chapter_dir_name(chapter),
            )
        )
        create_directory(chapter_dir)
        remove_download_complete_marker(chapter_dir)
        write_download_in_progress_marker(
            chapter_dir,
            expected_pages=len(chapter.image_urls),
        )
        originals_dir = os.path.join(chapter_dir, "originais")
        if self.keep_originals and self.image_format == "png":
            create_directory(originals_dir)

        total = len(chapter.image_urls)
        completed = 0
        failures: List[str] = []
        progress_lock = threading.Lock()
        callback = progress_callback or self.progress_callback
        cookie_header = getattr(chapter, "reader_cookie_header", "")

        def download_one(index: int, page_or_image_url: str) -> None:
            nonlocal completed
            page_label = f"{index:03d}"
            logger.info("[PAGE %s] iniciando", page_label)
            image_url = page_or_image_url
            if _is_reader_page_url(page_or_image_url):
                image_url = self._resolve_reader_page_image(page_or_image_url, cookie_header, page_label)
                logger.info("[PAGE %s] imagem localizada", page_label)
            self._download_image(image_url, chapter.url, chapter_dir, originals_dir, index)
            with progress_lock:
                completed += 1
                done = completed
            if callback:
                callback(chapter, done, total)
            logger.info("[PAGE %s] concluída", page_label)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_map = {
                executor.submit(download_one, index, image_url): index
                for index, image_url in enumerate(chapter.image_urls, start=1)
            }
            for future in as_completed(future_map):
                index = future_map[future]
                try:
                    future.result()
                except Exception as exc:
                    failures.append(f"page {index}: {exc}")

        downloaded = total - len(failures)
        success = downloaded == total
        result = DownloadResult(
            chapter=chapter,
            success=success,
            file_path=chapter_dir,
            images_downloaded=downloaded,
            expected_pages=total,
            error_message=None if success else "; ".join(failures[:5]),
        )
        return self._finalize_download_result(
            result,
            expected_pages=total,
        )

    def download_chapters(self, manga: Manga, chapters: List[Chapter], result_callback=None) -> List[DownloadResult]:
        """Download chapters in order; each chapter has its own bounded page worker queue."""
        results: List[DownloadResult] = []
        for chapter in chapters:
            try:
                result = self.download_chapter(manga, chapter)
            except Exception as exc:
                result = DownloadResult(chapter=chapter, success=False, error_message=str(exc))
            results.append(result)
            if result_callback:
                result_callback(result)
        return results

    def _resolve_reader_page_image(self, reader_url: str, cookie_header: str = "", page_label: str = "?") -> str:
        headers = {"Referer": f"{urlparse(reader_url).scheme}://{urlparse(reader_url).netloc}/"}
        if cookie_header:
            headers["Cookie"] = cookie_header

        last_error = None
        for attempt in range(self.retry_count + 1):
            try:
                self._wait_for_request_slot()
                response = self._get_session().get(reader_url, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                image_url = _extract_image_from_reader_html(response.text, reader_url)
                if not image_url:
                    raise ParsingError("reader HTML did not expose the image URL")
                return image_url
            except Exception as exc:
                last_error = exc
                if attempt >= self.retry_count:
                    logger.warning("[PAGE %s] erro: %s", page_label, exc)
                    raise
                logger.info("[PAGE %s] retry %s/%s: %s", page_label, attempt + 1, self.retry_count, exc)
                time.sleep(min(0.5 * (2 ** attempt), 4.0))
        raise DownloadError(str(last_error or "reader page resolution failed"))

    def _download_image(
        self,
        image_url: str,
        chapter_referer: str,
        chapter_dir: str,
        originals_dir: str,
        index: int,
    ) -> None:
        headers = {
            "Referer": f"{urlparse(chapter_referer).scheme}://{urlparse(chapter_referer).netloc}/",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        response = None
        last_error = None
        for attempt in range(self.retry_count + 1):
            try:
                self._wait_for_request_slot()
                response = self._get_session().get(image_url, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                break
            except Exception as exc:
                last_error = exc
                if attempt >= self.retry_count:
                    raise
                time.sleep(min(0.5 * (2 ** attempt), 4.0))
        if response is None:
            raise DownloadError(str(last_error or "request failed"))

        self._save_image_bytes(
            response.content,
            response.headers.get("content-type", ""),
            chapter_dir,
            originals_dir,
            index,
        )

    def _save_image_bytes(
        self,
        raw: bytes,
        content_type_header: str,
        chapter_dir: str,
        originals_dir: str,
        index: int,
    ) -> None:
        content_type = content_type_header.split(";", 1)[0].lower()
        if not content_type.startswith("image/"):
            raise DownloadError(f"server returned {content_type or 'non-image content'}")
        try:
            with Image.open(io.BytesIO(raw)) as probe:
                probe.verify()
            with Image.open(io.BytesIO(raw)) as image:
                detected_format = (image.format or "").upper()
                width, height = image.size
                if width <= 0 or height <= 0:
                    raise DownloadError("invalid image dimensions")
                image.load()
                converted = image.copy()
        except (UnidentifiedImageError, OSError) as exc:
            raise DownloadError("downloaded content is not a valid image") from exc

        ext_map = {"JPEG": ".jpg", "JPG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}
        original_ext = ext_map.get(detected_format, ".img")
        stem = f"page-{index:03d}"

        if self.keep_originals and self.image_format == "png":
            original_path = os.path.join(originals_dir, stem + original_ext)
            if not os.path.exists(original_path):
                Path(original_path).write_bytes(raw)

        if self.image_format == "original":
            output_path = os.path.join(chapter_dir, stem + original_ext)
            if not os.path.exists(output_path):
                Path(output_path).write_bytes(raw)
            return

        output_path = os.path.join(chapter_dir, stem + ".png")
        if os.path.exists(output_path):
            return
        # PNG is lossless. It cannot restore detail already lost in a source JPEG/WebP.
        if converted.mode == "P":
            converted = converted.convert("RGBA")
        elif converted.mode not in ("RGB", "RGBA", "L", "LA"):
            converted = converted.convert("RGB")
        converted.save(output_path, format="PNG", optimize=False)

    def _get_session(self) -> SessionManager:
        # Respect explicit session injection/monkeypatching. This keeps the downloader
        # testable and preserves backwards compatibility with callers that replace
        # ``self.session`` or ``self.session.get``.
        current_get_func = getattr(getattr(self.session, "get", None), "__func__", None)
        if not isinstance(self.session, SessionManager) or current_get_func is not self._session_get_func:
            return self.session

        # Production executor workers still receive isolated clients so mutable HTTP
        # session state is not shared between concurrent page downloads.
        if threading.get_ident() == self._session_owner_thread:
            return self.session
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = SessionManager(timeout=self.timeout)
            self._thread_local.session = session
            with self._sessions_lock:
                self._sessions.append(session)
        return session

    def _wait_for_request_slot(self) -> None:
        """Enforce a global minimum interval between image requests."""
        if self.page_delay <= 0:
            return
        with self._rate_lock:
            if self._last_request_at:
                time.sleep(self.page_delay)
            self._last_request_at = time.monotonic()

    def close(self):
        with self._sessions_lock:
            sessions = [self.session, *self._sessions]
            self._sessions.clear()
        for session in sessions:
            try:
                session.close()
            except Exception:
                pass


# Compatibility names retained so existing CLI/GUI imports keep working.
def init_driver():
    raise RuntimeError("Selenium/ChromeDriver was removed. Browser automation now uses Playwright internally.")


def close_driver(_driver):
    return None

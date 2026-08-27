"""Chapter discovery, image location and validated image downloading."""
from __future__ import annotations

import io
import time
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Union
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from PIL import Image, UnidentifiedImageError

from .browser import browser_page
from .models import Chapter, Manga, DownloadResult
from .utils import SessionManager, ParsingError, DownloadError, create_directory, sanitize_filename

IMAGE_HOST_HINTS = ("mangapicgallery.com", "mangago", "youhim")
SUPPORTED_IMAGE_MODES = {"original", "png"}


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


def fetch_chapter_image_urls(chapter_url: str) -> List[str]:
    """Collect chapter image URLs with Playwright, using reader-aware selectors."""
    if not chapter_url:
        raise ParsingError("Chapter URL is invalid.")

    with browser_page(headless=True) as page:
        page.goto(chapter_url, wait_until="domcontentloaded", timeout=30_000)
        page.locator("body").wait_for(state="attached")

        domain = urlparse(page.url).netloc.lower()
        if domain.endswith("mangago.me") and "/pg-" in page.url:
            urls: List[str] = []
            seen_urls = set()
            original_identity = _chapter_identity(page.url)

            # Prefer the chapter's own total_pages JS variable, then visible counter.
            try:
                total_pages = page.evaluate("() => Number(window.total_pages || 0)") or 0
            except Exception:
                total_pages = 0
            if not total_pages:
                try:
                    text = page.locator(".multi_pg_tip.left").first.inner_text()
                    match = re.search(r"/(\d+)\)?", text)
                    total_pages = int(match.group(1)) if match else 0
                except Exception:
                    total_pages = 0

            visited = set()
            while True:
                current = page.url
                if current in visited:
                    break
                visited.add(current)
                number = _page_number_from_url(current)

                src = _extract_current_mangago_image(page, number)
                if src and src not in seen_urls:
                    seen_urls.add(src)
                    urls.append(src)

                if total_pages and len(urls) >= total_pages:
                    break

                next_link = page.locator("a.next_page").first
                if not next_link.count():
                    break
                href = next_link.get_attribute("href")
                if not href:
                    break
                next_url = urljoin(current, href)
                if _chapter_identity(next_url) != original_identity:
                    break

                page.goto(next_url, wait_until="domcontentloaded", timeout=30_000)
                page.locator("#pic_container").wait_for(state="attached", timeout=15_000)

            if not urls:
                raise ParsingError("No chapter images found in Mangago reader.")
            return urls

        # Long-strip or alternate readers: one rendered page can hold many images.
        urls = _collect_longstrip_images(page)
        if not urls:
            raise ParsingError("No chapter images found.")
        return urls


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

    def __init__(
        self,
        max_workers: int = 5,
        download_dir: str = "downloads",
        image_format: str = "png",
        keep_originals: bool = True,
        page_delay: float = 2.0,
        progress_callback=None,
    ):
        self.max_workers = max_workers
        self.download_dir = download_dir
        self.image_format = image_format if image_format in SUPPORTED_IMAGE_MODES else "png"
        self.keep_originals = keep_originals
        self.page_delay = max(0.0, float(page_delay))
        self.progress_callback = progress_callback
        self.session = SessionManager()

    def download_chapter(self, manga: Manga, chapter: Chapter) -> DownloadResult:
        if not chapter.image_urls:
            return DownloadResult(chapter=chapter, success=False, error_message="No image URLs found.")

        manga_dir = os.path.join(self.download_dir, sanitize_filename(manga.title))
        chapter_dir = os.path.join(manga_dir, f"Chapter_{chapter.number}")
        create_directory(chapter_dir)
        originals_dir = os.path.join(chapter_dir, "originais")
        if self.keep_originals and self.image_format == "png":
            create_directory(originals_dir)

        downloaded = 0
        failures: List[str] = []
        for index, image_url in enumerate(chapter.image_urls, start=1):
            try:
                self._download_image(image_url, chapter.url, chapter_dir, originals_dir, index)
                downloaded += 1
                if self.progress_callback:
                    self.progress_callback(chapter, index, len(chapter.image_urls))
                if self.page_delay > 0 and index < len(chapter.image_urls):
                    time.sleep(self.page_delay)
            except Exception as exc:
                failures.append(f"page {index}: {exc}")

        success = downloaded == len(chapter.image_urls)
        return DownloadResult(
            chapter=chapter,
            success=success,
            file_path=chapter_dir,
            images_downloaded=downloaded,
            error_message=None if success else "; ".join(failures[:5]),
        )

    def download_chapters(self, manga: Manga, chapters: List[Chapter]) -> List[DownloadResult]:
        results: List[DownloadResult] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_map = {executor.submit(self.download_chapter, manga, ch): ch for ch in chapters}
            for future in as_completed(future_map):
                results.append(future.result())
        return results

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
        response = self.session.get(image_url, headers=headers, timeout=30)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if not content_type.startswith("image/"):
            raise DownloadError(f"server returned {content_type or 'non-image content'}")

        raw = response.content
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

    def close(self):
        self.session.close()


# Compatibility names retained so existing CLI/GUI imports keep working.
def init_driver():
    raise RuntimeError("Selenium/ChromeDriver was removed. Browser automation now uses Playwright internally.")


def close_driver(_driver):
    return None

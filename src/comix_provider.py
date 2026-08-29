"""Comix rendered-reader provider.

This module is intentionally isolated from the Mangago V4 engine.  It uses the
Comix reader's own rendered behaviour to obtain normal images and to rebuild
tile-scrambled canvas pages.
"""
from __future__ import annotations

import asyncio
import io
import re
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence
from urllib.parse import urljoin, urlparse

from PIL import Image

from .models import DownloadResult, Manga, Chapter
from .output_paths import chapter_image_dir
from .utils import DownloadError, ParsingError, create_directory, sanitize_filename
from .browser import DEFAULT_USER_AGENT


COMIX_HOSTS = ("comix.to", "www.comix.to")
COMIX_PAGE_SELECTOR = ".rpage-page[data-page]"
COMIX_MEDIA_SELECTOR = ".rpage-page__img"

# Minimal browser compatibility adjustments proven during the investigation.
COMIX_INIT_SCRIPT = r"""
(() => {
  try {
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
  } catch (_) {}
  try {
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
  } catch (_) {}
  try {
    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
  } catch (_) {}
  window.chrome = window.chrome || {};
  window.chrome.runtime = window.chrome.runtime || {};

  window.__comixDraws = [];
  window.__comixSnapshotCanvas = null;

  const install = (proto, label) => {
    if (!proto || proto.__comixOriginalDrawImage) return;
    const original = proto.drawImage;
    Object.defineProperty(proto, '__comixOriginalDrawImage', {
      value: original,
      configurable: true
    });

    proto.drawImage = function(...args) {
      /*
       * Let Comix render first.  The snapshot below must reflect the canvas
       * exactly as the browser sees it after the current tile was painted.
       */
      const result = original.apply(this, args);

      if (args.length === 9) {
        const [source, sx, sy, sw, sh, dx, dy, dw, dh] = args;

        window.__comixDraws.push({
          context: label,
          sx, sy, sw, sh, dx, dy, dw, dh,
          canvasWidth: this.canvas?.width ?? null,
          canvasHeight: this.canvas?.height ?? null,
          sourceWidth: source?.naturalWidth ?? source?.width ?? null,
          sourceHeight: source?.naturalHeight ?? source?.height ?? null,
          sourceSrc: source?.currentSrc ?? source?.src ?? null,
          time: Math.round(performance.now())
        });

        /*
         * Comix virtualizes its reader and may remove/zero the original
         * canvas immediately after rendering.  Preserve an independent
         * pixel copy after every observed tile.  When the Python side later
         * confirms a coherent grid, the most recent snapshot is the completed
         * browser-rendered page.
         *
         * Use the unpatched original drawImage to avoid recursively recording
         * this internal copy as another Comix tile.
         */
        if (
          label === 'canvas' &&
          this.canvas &&
          this.canvas.width > 0 &&
          this.canvas.height > 0
        ) {
          try {
            const snapshot = document.createElement('canvas');
            snapshot.width = this.canvas.width;
            snapshot.height = this.canvas.height;

            const snapshotContext = snapshot.getContext('2d');
            if (snapshotContext) {
              original.call(snapshotContext, this.canvas, 0, 0);
              window.__comixSnapshotCanvas = snapshot;
            }
          } catch (_) {
            // Snapshot is an optimization. The existing wowpic rebuild remains
            // available as a fallback on the Python side.
          }
        }
      }

      return result;
    };
  };

  install(window.CanvasRenderingContext2D?.prototype, 'canvas');
  install(window.OffscreenCanvasRenderingContext2D?.prototype, 'offscreen');
})();
"""


@dataclass(frozen=True)
class DrawTile:
    sx: int
    sy: int
    sw: int
    sh: int
    dx: int
    dy: int
    dw: int
    dh: int


def is_comix_title_url(url: Optional[str]) -> bool:
    """Return True for a Comix title page, excluding direct chapter URLs."""
    if not url:
        return False

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    host = parsed.netloc.lower().split(":", 1)[0]
    if host not in COMIX_HOSTS:
        return False

    path = parsed.path.lower().rstrip("/")
    if "/title/" not in path or "chapter-" in path:
        return False

    parts = [part for part in path.split("/") if part]
    return len(parts) >= 2 and parts[0] == "title"


def is_comix_chapter_url(url: Optional[str]) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = parsed.netloc.lower().split(":", 1)[0]
    if host not in COMIX_HOSTS:
        return False
    path = parsed.path.lower()
    return "/title/" in path and "chapter-" in path


def _parse_comix_chapter_rows(rows: Sequence[dict], base_url: str) -> List[dict]:
    """Normalize rendered Comix chapter rows and deduplicate them by URL."""
    chapters: List[dict] = []
    seen_urls = set()

    for row in rows:
        raw_url = str(row.get("url") or "").strip()
        if not raw_url:
            continue

        url = urljoin(base_url, raw_url)
        if url in seen_urls:
            continue

        match = re.search(r"chapter-([0-9]+(?:\.[0-9]+)?)(?:[/?#]|$)", url, re.I)
        if not match:
            continue

        number = float(match.group(1))
        source = str(row.get("source") or "").strip() or "Comix"
        title = str(row.get("title") or "").strip() or f"Chapter {number:g}"

        chapters.append(
            {
                "number": number,
                "url": url,
                "title": title,
                "source": source,
            }
        )
        seen_urls.add(url)

    chapters.sort(key=lambda item: (item["number"], item["source"].lower(), item["url"]))
    return chapters


def discover_comix_chapters(title_url: str, timeout: int = 30) -> List[dict]:
    """Discover all rendered chapters exposed by a Comix title page."""
    return asyncio.run(_discover_comix_chapters_async(title_url, timeout=timeout))


async def _discover_comix_chapters_async(title_url: str, timeout: int = 30) -> List[dict]:
    from playwright.async_api import async_playwright

    if not is_comix_title_url(title_url):
        raise ParsingError("URL is not a supported Comix title URL.")

    timeout_ms = max(1, int(timeout)) * 1000
    parsed_title = urlparse(title_url)
    base_title_url = f"{parsed_title.scheme}://{parsed_title.netloc}{parsed_title.path.rstrip('/')}"

    collected: List[dict] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            viewport={"width": 1280, "height": 1800},
            ignore_https_errors=False,
        )
        await context.add_init_script(COMIX_INIT_SCRIPT)
        page = await context.new_page()
        page.set_default_timeout(timeout_ms)

        try:
            response = await page.goto(
                base_title_url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            if response is not None and response.status >= 400:
                raise DownloadError(f"Comix title returned HTTP {response.status}.")

            await page.locator(".mchap-item").first.wait_for(
                state="attached",
                timeout=timeout_ms,
            )

            raw_groups = await page.locator('a[href^="/groups/"]').evaluate_all(
                """els => els.map(el => ({
                    name: (el.textContent || '').trim(),
                    href: el.getAttribute('href') || '',
                    className: el.className || ''
                }))"""
            )

            groups = {}

            for item in raw_groups:
                match = re.search(r"/groups/(\d+)", item.get("href") or "")
                if not match:
                    continue

                group_id = match.group(1)

                groups[group_id] = {
                    "id": group_id,
                    "name": str(item.get("name") or "").strip() or f"Group {group_id}",
                    "official": "is-official" in str(item.get("className") or ""),
                }

            if not groups:
                raise ParsingError("Comix title page exposed no chapter groups.")

            for group in groups.values():
                page_number = 1

                while True:
                    page_url = (
                        f"{base_title_url}"
                        f"?group_id={group['id']}&page={page_number}"
                    )

                    response = await page.goto(
                        page_url,
                        wait_until="domcontentloaded",
                        timeout=timeout_ms,
                    )

                    if response is not None and response.status >= 400:
                        raise DownloadError(
                            f"Comix chapter list returned HTTP {response.status}."
                        )

                    try:
                        await page.locator(".mchap-item").first.wait_for(
                            state="attached",
                            timeout=min(timeout_ms, 10000),
                        )
                    except Exception:
                        pass

                    rows = await page.locator(".mchap-item").evaluate_all(
                        """els => els.map(el => {
                          const primary = el.querySelector('a.mchap-row__primary');
                          const chapter = el.querySelector('.mchap-row__ch');
                          return {
                            url: primary ? primary.getAttribute('href') : '',
                            title: chapter ? chapter.textContent.trim() : ''
                          };
                        })"""
                    )

                    if not rows:
                        break

                    for row in rows:
                        row["source"] = group["name"]
                        row["group_id"] = group["id"]
                        row["official"] = group["official"]

                    collected.extend(rows)

                    page_number += 1
        finally:
            await page.close()
            await context.close()
            await browser.close()

    chapters = _parse_comix_chapter_rows(collected, base_title_url)

    if not chapters:
        raise ParsingError("Comix title page exposed no supported chapters.")

    return chapters


def _validate_draw_tiles(draws: Sequence[DrawTile]) -> tuple[int, int]:
    if not draws:
        raise DownloadError("Comix canvas reconstruction did not capture drawImage tiles.")

    first = draws[0]
    if min(first.sw, first.sh, first.dw, first.dh) <= 0:
        raise DownloadError("Comix captured invalid tile dimensions.")

    src_x = sorted({d.sx for d in draws})
    src_y = sorted({d.sy for d in draws})
    cols = len(src_x)
    rows = len(src_y)
    expected = cols * rows
    if expected != len(draws):
        raise DownloadError(
            f"Comix tile capture is incomplete: {len(draws)} draws for {cols}x{rows} grid."
        )

    src_cells = {(d.sx // d.sw, d.sy // d.sh) for d in draws}
    dst_cells = {(d.dx // d.dw, d.dy // d.dh) for d in draws}
    if len(src_cells) != expected or len(dst_cells) != expected:
        raise DownloadError("Comix tile mapping contains duplicated source/destination cells.")

    return cols, rows


def rebuild_scrambled_image(raw: bytes, draw_records: Sequence[dict]) -> bytes:
    """Rebuild a Comix scrambled image using captured drawImage geometry."""
    draws = [
        DrawTile(
            sx=int(item["sx"]), sy=int(item["sy"]),
            sw=int(item["sw"]), sh=int(item["sh"]),
            dx=int(item["dx"]), dy=int(item["dy"]),
            dw=int(item["dw"]), dh=int(item["dh"]),
        )
        for item in draw_records
    ]
    _validate_draw_tiles(draws)

    try:
        with Image.open(io.BytesIO(raw)) as source:
            source.load()
            src = source.convert("RGBA") if source.mode not in ("RGB", "RGBA") else source.copy()
    except Exception as exc:
        raise DownloadError("Comix scrambled response is not a valid image.") from exc

    result = Image.new(src.mode, src.size)
    width, height = src.size

    for d in draws:
        if d.sw != d.dw or d.sh != d.dh:
            raise DownloadError("Comix tile scaling changed; provider refuses ambiguous reconstruction.")
        sx, sy = d.sx, d.sy
        dx, dy = d.dx, d.dy
        sw = min(d.sw, max(0, width - sx))
        sh = min(d.sh, max(0, height - sy))
        if sw <= 0 or sh <= 0:
            continue
        tile = src.crop((sx, sy, sx + sw, sy + sh))
        result.paste(tile, (dx, dy))

    buf = io.BytesIO()
    result.save(buf, "PNG")
    return buf.getvalue()


def _select_special_fetch_url(entries: Sequence[dict]) -> str:
    candidates: List[tuple[float, str]] = []
    for item in entries:
        url = str(item.get("name") or "")
        kind = str(item.get("initiatorType") or "").lower()
        if kind != "fetch":
            continue
        if "wowpic" not in url.lower():
            continue
        # The protected Comix fetch observed in the reader carries a query suffix.
        if "?" not in url:
            continue
        candidates.append((float(item.get("startTime") or 0), url))
    if not candidates:
        raise DownloadError("Comix special page fetch URL was not observed.")
    candidates.sort()
    return candidates[-1][1]


async def _wait_media_kind(wrapper, timeout_ms: int) -> str:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        kind = await wrapper.evaluate(
            """el => {
              const media = el.querySelector('.rpage-page__img');
              return media ? media.tagName.toLowerCase() : '';
            }"""
        )
        if kind in ("img", "canvas"):
            return kind
        await asyncio.sleep(0.05)
    raise DownloadError("Comix page did not materialize an img/canvas element in time.")


async def _materialize(wrapper) -> None:
    await wrapper.evaluate(
        "el => el.scrollIntoView({behavior:'instant', block:'center'})"
    )


async def _normal_image_url(wrapper, timeout_ms: int) -> str:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        data = await wrapper.evaluate(
            """el => {
              const img = el.querySelector('img.rpage-page__img');
              if (!img) return null;
              return {
                src: img.currentSrc || img.src || '',
                complete: !!img.complete,
                width: img.naturalWidth || 0,
                height: img.naturalHeight || 0
              };
            }"""
        )
        if (
            data
            and data.get("src")
            and data.get("complete")
            and data.get("width", 0) > 0
            and data.get("height", 0) > 0
        ):
            return str(data["src"])
        await asyncio.sleep(0.05)
    raise DownloadError("Comix normal image did not become ready in time.")


async def _parking_wrapper(page, page_number: int, total: int):
    # Move far enough to make the virtualized page leave the active viewport.
    candidate = page_number + 15
    if candidate > total:
        candidate = max(1, page_number - 15)
    return page.locator(f'{COMIX_PAGE_SELECTOR}[data-page="{candidate}"]').first


async def _capture_special_snapshot(page) -> Optional[bytes]:
    """Capture the browser-rendered Comix canvas preserved by COMIX_INIT_SCRIPT.

    The source canvas may already have been removed or zeroed by Comix
    virtualization.  __comixSnapshotCanvas is an independent copy created
    immediately after drawImage calls, so it can still be attached temporarily
    and captured by Chromium.

    Returns None when no usable snapshot is available; callers must then use
    the existing wowpic reconstruction fallback.
    """
    snapshot_id = "__comix_snapshot_capture"

    info = await page.evaluate(
        """(snapshotId) => {
          const snapshot = window.__comixSnapshotCanvas;

          if (
            !snapshot ||
            !snapshot.width ||
            !snapshot.height
          ) {
            return null;
          }

          const previous = document.getElementById(snapshotId);
          if (previous) previous.remove();

          snapshot.id = snapshotId;

          Object.assign(snapshot.style, {
            position: 'absolute',
            left: '0px',
            top: '0px',
            zIndex: '2147483647',
            display: 'block',
            visibility: 'visible',
            opacity: '1',
            width: snapshot.width + 'px',
            height: snapshot.height + 'px'
          });

          document.documentElement.appendChild(snapshot);

          return {
            width: snapshot.width,
            height: snapshot.height
          };
        }""",
        snapshot_id,
    )

    if not info:
        return None

    try:
        locator = page.locator(f"#{snapshot_id}")
        return await locator.screenshot(
            type="png",
            animations="disabled",
            timeout=5000,
        )
    except Exception:
        return None
    finally:
        try:
            await page.evaluate(
                """(snapshotId) => {
                  const snapshot = document.getElementById(snapshotId);
                  if (snapshot) snapshot.remove();
                }""",
                snapshot_id,
            )
        except Exception:
            pass


async def _capture_special(page, wrapper, page_number: int, total: int, timeout_ms: int):
    parking = await _parking_wrapper(page, page_number, total)
    if await parking.count():
        await _materialize(parking)
        await page.wait_for_timeout(450)

    await page.evaluate(
        """() => {
          window.__comixDraws = [];
          window.__comixSnapshotCanvas = null;
          try { performance.clearResourceTimings(); } catch (_) {}
        }"""
    )

    await _materialize(wrapper)

    deadline = time.monotonic() + timeout_ms / 1000
    records: List[dict] = []
    while time.monotonic() < deadline:
        records = await page.evaluate("() => (window.__comixDraws || []).slice()")
        if len(records) >= 25:
            # A complete observed grid is selected dynamically below.
            # Keep the most recent geometrically coherent group.
            break
        await asyncio.sleep(0.05)

    if not records:
        raise DownloadError(f"Comix page {page_number} produced no captured drawImage calls.")

    # Find a coherent tail group.  We intentionally do not hardcode page numbers.
    chosen: Optional[List[dict]] = None
    for size in range(min(100, len(records)), 0, -1):
        tail = records[-size:]
        try:
            _validate_draw_tiles([
                DrawTile(
                    int(x["sx"]), int(x["sy"]), int(x["sw"]), int(x["sh"]),
                    int(x["dx"]), int(x["dy"]), int(x["dw"]), int(x["dh"])
                )
                for x in tail
            ])
            chosen = tail
            break
        except Exception:
            continue
    if not chosen:
        # Most observed special pages use a 5x5 grid; try exact consecutive windows
        # without assuming that every special page must be 5x5.
        for start in range(len(records)):
            for end in range(start + 1, min(len(records), start + 100) + 1):
                group = records[start:end]
                try:
                    _validate_draw_tiles([
                        DrawTile(
                            int(x["sx"]), int(x["sy"]), int(x["sw"]), int(x["sh"]),
                            int(x["dx"]), int(x["dy"]), int(x["dw"]), int(x["dh"])
                        )
                        for x in group
                    ])
                    chosen = group
                    break
                except Exception:
                    pass
            if chosen:
                break
    if not chosen:
        raise DownloadError(f"Comix page {page_number} drawImage capture was not a coherent grid.")

    # Prefer the page already reconstructed by Comix itself.  This avoids
    # having to guess which of several concurrent wowpic resources belongs to
    # the captured drawImage grid.
    snapshot_png = await _capture_special_snapshot(page)
    if snapshot_png:
        return chosen, None, snapshot_png

    # Fallback retained for environments where Chromium cannot capture the
    # preserved canvas.
    entries = await page.evaluate(
        """() => performance.getEntriesByType('resource').map(e => ({
          name: e.name,
          initiatorType: e.initiatorType,
          startTime: e.startTime
        }))"""
    )
    fetch_url = _select_special_fetch_url(entries)
    return chosen, fetch_url, None


def download_comix_chapter(downloader, manga: Manga, chapter: Chapter, progress_callback=None) -> DownloadResult:
    """Synchronous facade matching ChapterDownloader.download_chapter()."""
    return asyncio.run(
        _download_comix_chapter_async(
            downloader,
            manga,
            chapter,
            progress_callback=progress_callback,
        )
    )


async def _download_comix_chapter_async(
    downloader,
    manga: Manga,
    chapter: Chapter,
    progress_callback=None,
) -> DownloadResult:
    from playwright.async_api import async_playwright

    if not is_comix_chapter_url(chapter.url):
        return DownloadResult(
            chapter=chapter,
            success=False,
            error_message="URL is not a supported Comix chapter URL.",
        )

    timeout_seconds = max(1, int(getattr(downloader, "timeout", 30)))
    timeout_ms = timeout_seconds * 1000
    page_delay = max(0.0, float(getattr(downloader, "page_delay", 0.0)))
    callback = progress_callback or getattr(downloader, "progress_callback", None)


    pattern = (getattr(chapter, "folder_pattern", None) or "Ch. 01").strip()
    number = chapter.number
    number_text = f"{number:g}"

    import re
    match = re.search(r"(0*1)", pattern)
    if match:
        width = len(match.group(1))
        if float(number).is_integer():
            formatted_number = str(int(number)).zfill(width)
        else:
            formatted_number = number_text
        folder_name = pattern[:match.start()] + formatted_number + pattern[match.end():]
    else:
        folder_name = f"Ch.{number_text}"

    chapter_dir = str(
        chapter_image_dir(
            downloader.download_dir,
            "comix",
            sanitize_filename(manga.title),
            sanitize_filename(folder_name),
        )
    )
    create_directory(chapter_dir)
    originals_dir = f"{chapter_dir}/originais"
    if getattr(downloader, "keep_originals", False) and getattr(downloader, "image_format", "original") == "png":
        create_directory(originals_dir)

    downloaded = 0
    failures: List[str] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            viewport={"width": 1280, "height": 1800},
            ignore_https_errors=False,
        )
        await context.add_init_script(COMIX_INIT_SCRIPT)
        page = await context.new_page()
        page.set_default_timeout(timeout_ms)

        try:
            response = await page.goto(
                chapter.url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            if response is not None and response.status >= 400:
                raise DownloadError(f"Comix chapter returned HTTP {response.status}.")

            await page.locator(COMIX_PAGE_SELECTOR).first.wait_for(
                state="attached",
                timeout=timeout_ms,
            )

            numbers = await page.locator(COMIX_PAGE_SELECTOR).evaluate_all(
                """els => els.map(el => Number(el.dataset.page || 0)).filter(Boolean)"""
            )
            numbers = [int(n) for n in numbers]
            if not numbers:
                raise ParsingError("Comix reader exposed no structural page wrappers.")
            if len(numbers) != len(set(numbers)):
                raise ParsingError("Comix reader exposed duplicate data-page values.")
            ordered = sorted(numbers)
            if ordered != list(range(ordered[0], ordered[-1] + 1)):
                raise ParsingError("Comix reader data-page sequence has gaps.")
            total = len(ordered)

            for position, page_number in enumerate(ordered, start=1):
                wrapper = page.locator(
                    f'{COMIX_PAGE_SELECTOR}[data-page="{page_number}"]'
                ).first
                try:
                    await _materialize(wrapper)
                    media_kind = await _wait_media_kind(wrapper, timeout_ms)

                    if media_kind == "img":
                        image_url = await _normal_image_url(wrapper, timeout_ms)
                        image_response = await context.request.get(
                            image_url,
                            headers={
                                "Referer": "https://comix.to/",
                                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                            },
                            timeout=timeout_ms,
                        )
                        if not image_response.ok:
                            raise DownloadError(
                                f"Comix image request returned HTTP {image_response.status}"
                            )
                        raw = await image_response.body()
                        content_type = image_response.headers.get("content-type", "")
                    elif media_kind == "canvas":
                        draws, special_url, snapshot_png = await _capture_special(
                            page, wrapper, page_number, total, timeout_ms
                        )

                        if snapshot_png:
                            # Preferred path: Chromium captures the exact canvas
                            # already reconstructed by the Comix reader.
                            raw = snapshot_png
                            content_type = "image/png"
                        else:
                            # Compatibility fallback: preserve the previous
                            # wowpic + captured drawImage reconstruction.
                            if not special_url:
                                raise DownloadError(
                                    f"Comix page {page_number} produced neither "
                                    "a canvas snapshot nor a scrambled image URL."
                                )

                            image_response = await context.request.get(
                                special_url,
                                headers={
                                    "Referer": "https://comix.to/",
                                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                                },
                                timeout=timeout_ms,
                            )
                            if not image_response.ok:
                                raise DownloadError(
                                    f"Comix scrambled image returned HTTP "
                                    f"{image_response.status}"
                                )

                            scrambled = await image_response.body()
                            raw = await asyncio.to_thread(
                                rebuild_scrambled_image, scrambled, draws
                            )
                            content_type = "image/png"
                    else:
                        raise DownloadError(
                            f"Unsupported Comix media element: {media_kind!r}"
                        )

                    await asyncio.to_thread(
                        downloader._save_image_bytes,
                        raw,
                        content_type,
                        chapter_dir,
                        originals_dir,
                        position,
                    )
                    downloaded += 1
                    if callback:
                        callback(chapter, downloaded, total)
                except Exception as exc:
                    failures.append(f"page {page_number}: {exc}")

                if page_delay > 0 and position < total:
                    await asyncio.sleep(page_delay)
        finally:
            await page.close()
            await context.close()
            await browser.close()

    success = downloaded == len(ordered)
    result = DownloadResult(
        chapter=chapter,
        success=success,
        file_path=chapter_dir,
        images_downloaded=downloaded,
        expected_pages=len(ordered),
        error_message=None if success else "; ".join(failures[:5]),
    )
    return downloader._finalize_download_result(
        result,
        expected_pages=len(ordered),
    )

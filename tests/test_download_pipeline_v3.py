import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src import downloader as engine
from src.downloader import ChapterDownloader, discover_chapter_reader_pages
from src.models import Chapter, Manga


def image_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (6, 7), "white").save(buf, "JPEG")
    return buf.getvalue()


class FakeLocator:
    def wait_for(self, *args, **kwargs):
        return None


class FakeContext:
    def cookies(self):
        return [{"name": "sid", "value": "abc"}]


class FakePage:
    def __init__(self, html: str, url: str):
        self._html = html
        self.url = url
        self.context = FakeContext()

    def goto(self, url, *args, **kwargs):
        self.url = url

    def locator(self, *args, **kwargs):
        return FakeLocator()

    def content(self):
        return self._html


class FakeBrowserPage:
    def __init__(self, page):
        self.page = page

    def __enter__(self):
        return self.page

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeResponse:
    def __init__(self, body, content_type="text/html"):
        self.content = body if isinstance(body, bytes) else body.encode("utf-8")
        self.text = body if isinstance(body, str) else body.decode("utf-8", errors="ignore")
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        return None


class RoutingSession:
    def __init__(self, routes, failures=None, calls=None, timeouts=None):
        self.routes = routes
        self.failures = failures or {}
        self.calls = calls if calls is not None else {}
        self.timeouts = timeouts if timeouts is not None else []

    def get(self, url, **kwargs):
        self.timeouts.append(kwargs.get("timeout"))
        self.calls[url] = self.calls.get(url, 0) + 1
        if self.failures.get(url, 0) >= self.calls[url]:
            raise TimeoutError("temporary")
        response = self.routes[url]
        return response() if callable(response) else response

    def close(self):
        pass


class DownloadPipelineV3Tests(unittest.TestCase):
    def test_discovery_returns_reader_pages_without_resolving_images(self):
        html = """
        <ul id="dropdown-menu-page" class="dropdown-menu page">
          <li><a href="/read-manga/demo/uu/br_chapter-1/pg-1/">page 1 of 3</a></li>
          <li><a href="/read-manga/demo/uu/br_chapter-1/pg-2/">page 2 of 3</a></li>
          <li><a href="/read-manga/demo/uu/br_chapter-1/pg-3/">page 3 of 3</a></li>
        </ul>
        """
        page = FakePage(html, "https://www.mangago.me/read-manga/demo/uu/br_chapter-1/pg-1/")
        with patch.object(engine, "browser_page", return_value=FakeBrowserPage(page)):
            urls = discover_chapter_reader_pages(page.url)
        self.assertEqual(3, len(urls))
        self.assertTrue(all("/pg-" in url for url in urls))
        self.assertFalse(any("mangapicgallery.com" in url for url in urls))

    def test_page_queue_downloads_ordered_files_and_reports_progress(self):
        img = image_bytes()
        routes = {
            "https://cdn.mangapicgallery.com/1.jpg": FakeResponse(img, "image/jpeg"),
            "https://cdn.mangapicgallery.com/2.jpg": FakeResponse(img, "image/jpeg"),
            "https://cdn.mangapicgallery.com/3.jpg": FakeResponse(img, "image/jpeg"),
        }
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            d = ChapterDownloader(max_workers=3, download_dir=tmp, image_format="original", page_delay=0, progress_callback=lambda ch, cur, total: events.append((cur, total)))
            d.session = RoutingSession(routes)
            chapter = Chapter(1, "https://www.mangago.me/read-manga/demo/uu/br_chapter-1/pg-1/", image_urls=list(routes))
            result = d.download_chapter(Manga("Demo", "https://www.mangago.me/read-manga/demo/"), chapter)
            d.close()
            self.assertTrue(result.success)
            names = sorted(path.name for path in Path(result.file_path).glob("page-*"))
        self.assertEqual(["page-001.jpg", "page-002.jpg", "page-003.jpg"], names)
        self.assertEqual((3, 3), events[-1])

    def test_max_workers_is_limited_to_three(self):
        self.assertEqual(3, ChapterDownloader(max_workers=20).max_workers)
        self.assertEqual(1, ChapterDownloader(max_workers=0).max_workers)

    def test_failed_page_finishes_without_waiting_forever(self):
        routes = {
            "https://cdn.mangapicgallery.com/1.jpg": FakeResponse("<html></html>", "text/html"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            d = ChapterDownloader(max_workers=1, download_dir=tmp, page_delay=0, retry_count=0, timeout=1)
            d.session = RoutingSession(routes)
            chapter = Chapter(1, "https://www.mangago.me/read-manga/demo/uu/br_chapter-1/pg-1/", image_urls=list(routes))
            started = time.monotonic()
            result = d.download_chapter(Manga("Demo", "https://www.mangago.me/read-manga/demo/"), chapter)
            d.close()
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertFalse(result.success)

    def test_retry_count_and_timeout_are_used_for_reader_page_resolution(self):
        reader_url = "https://www.mangago.me/read-manga/demo/uu/br_chapter-1/pg-1/"
        image_url = "https://cdn.mangapicgallery.com/1.jpg"
        calls = {}
        timeouts = []
        routes = {
            reader_url: FakeResponse(f'<div id="pic_container"><img id="page1" src="{image_url}"></div>'),
        }
        d = ChapterDownloader(max_workers=1, page_delay=0, retry_count=2, timeout=7)
        d.session = RoutingSession(routes, failures={reader_url: 1}, calls=calls, timeouts=timeouts)
        try:
            result = d._resolve_reader_page_image(reader_url)
        finally:
            d.close()
        self.assertEqual(image_url, result)
        self.assertEqual(2, calls[reader_url])
        self.assertIn(7, timeouts)


if __name__ == "__main__":
    unittest.main()

import io
import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image

from src.downloader import ChapterDownloader
from src.models import Chapter, DownloadResult, Manga


def jpeg_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (5, 6), "white").save(buf, "JPEG")
    return buf.getvalue()


class FakeGotoResponse:
    status = 200


class FakeImageResponse:
    def __init__(self, body=None, status=200):
        self.status = status
        self.ok = status < 400
        self.headers = {"content-type": "image/jpeg"}
        self._body = body or jpeg_bytes()

    async def body(self):
        return self._body


class FakeRequest:
    def __init__(self, response):
        self.response = response
        self.urls = []

    async def get(self, url, **kwargs):
        self.urls.append((url, kwargs))
        return self.response


class FakeImageItem:
    def __init__(self, image_url):
        self.image_url = image_url

    async def get_attribute(self, name):
        return self.image_url if name == "src" else None


class FakeLocator:
    def __init__(self, image_url, count):
        self.image_url = image_url
        self._count = count

    async def wait_for(self, **kwargs):
        return None

    async def count(self):
        return self._count

    def nth(self, index):
        return FakeImageItem(self.image_url)


class FakePage:
    def __init__(self, image_url):
        self.image_url = image_url
        self.url = ""

    def set_default_timeout(self, timeout):
        self.timeout = timeout

    async def goto(self, url, **kwargs):
        self.url = url
        return FakeGotoResponse()

    def locator(self, selector):
        if selector == "#pic_container":
            return FakeLocator(self.image_url, 1)
        if "img" in selector:
            return FakeLocator(self.image_url, 1)
        return FakeLocator(self.image_url, 0)

    async def close(self):
        return None


class FakeContext:
    def __init__(self, request, image_url):
        self.request = request
        self.image_url = image_url

    async def new_page(self):
        return FakePage(self.image_url)

    async def close(self):
        return None


class FakeBrowser:
    def __init__(self, context):
        self.context = context

    async def new_context(self, **kwargs):
        return self.context

    async def close(self):
        return None


class FakeChromium:
    def __init__(self, browser):
        self.browser = browser

    async def launch(self, **kwargs):
        return self.browser


class FakePlaywright:
    def __init__(self, browser):
        self.chromium = FakeChromium(browser)


class FakePlaywrightContext:
    def __init__(self, browser):
        self.browser = browser

    async def __aenter__(self):
        return FakePlaywright(self.browser)

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DownloadEngineV4Tests(unittest.TestCase):
    def test_reader_urls_use_playwright_pipeline(self):
        downloader = ChapterDownloader(max_workers=3)
        manga = Manga(title="Teste", url="https://www.mangago.me/read-manga/teste/")
        chapter = Chapter(
            number=1.0,
            url="https://www.mangago.me/read-manga/teste/uu/br_chapter-1/pg-1/",
            image_urls=[
                "https://www.mangago.me/read-manga/teste/uu/br_chapter-1/pg-1/",
                "https://www.mangago.me/read-manga/teste/uu/br_chapter-1/pg-2/",
            ],
        )
        expected = DownloadResult(chapter=chapter, success=True, images_downloaded=2)
        try:
            with patch.object(
                downloader,
                "_download_reader_chapter_playwright",
                return_value=expected,
            ) as mocked:
                result = downloader.download_chapter(manga, chapter)
            self.assertIs(result, expected)
            mocked.assert_called_once()
            self.assertLessEqual(downloader.max_workers, 3)
        finally:
            downloader.close()

    def test_v4_uses_playwright_request_context_for_image_bytes(self):
        reader_url = "https://www.mangago.me/read-manga/teste/uu/br_chapter-1/pg-1/"
        image_url = "https://iweb_7.mangapicgallery.com/teste/page1.jpg"
        request = FakeRequest(FakeImageResponse())
        context = FakeContext(request, image_url)
        browser = FakeBrowser(context)
        events = []

        with tempfile.TemporaryDirectory() as tmp:
            downloader = ChapterDownloader(
                max_workers=1,
                download_dir=tmp,
                image_format="original",
                page_delay=0,
                progress_callback=lambda chapter, current, total: events.append((current, total)),
            )
            manga = Manga(title="Teste", url="https://www.mangago.me/read-manga/teste/")
            chapter = Chapter(number=1.0, url=reader_url, image_urls=[reader_url])
            try:
                with patch("playwright.async_api.async_playwright", return_value=FakePlaywrightContext(browser)):
                    result = downloader.download_chapter(manga, chapter)
            finally:
                downloader.close()

            self.assertTrue(result.success)
            self.assertEqual([(1, 1)], events)
            self.assertTrue((Path(result.file_path) / "page-001.jpg").exists())
            self.assertEqual(image_url, request.urls[0][0])

    def test_v4_image_http_error_returns_without_waiting_forever(self):
        reader_url = "https://www.mangago.me/read-manga/teste/uu/br_chapter-1/pg-1/"
        image_url = "https://iweb_7.mangapicgallery.com/teste/page1.jpg"
        request = FakeRequest(FakeImageResponse(status=403))
        context = FakeContext(request, image_url)
        browser = FakeBrowser(context)

        with tempfile.TemporaryDirectory() as tmp:
            downloader = ChapterDownloader(max_workers=1, download_dir=tmp, page_delay=0, retry_count=0, timeout=1)
            manga = Manga(title="Teste", url="https://www.mangago.me/read-manga/teste/")
            chapter = Chapter(number=1.0, url=reader_url, image_urls=[reader_url])
            started = time.monotonic()
            try:
                with patch("playwright.async_api.async_playwright", return_value=FakePlaywrightContext(browser)):
                    result = downloader.download_chapter(manga, chapter)
            finally:
                downloader.close()

        self.assertLess(time.monotonic() - started, 1.0)
        self.assertFalse(result.success)
        self.assertIn("HTTP 403", result.error_message)


if __name__ == "__main__":
    unittest.main()

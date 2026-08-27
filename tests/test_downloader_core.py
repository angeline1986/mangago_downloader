import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.downloader import (
    ChapterDownloader,
    _chapter_identity,
    _page_number_from_url,
    _parse_chapters_from_html,
)
from src.models import Chapter, Manga


class FakeResponse:
    def __init__(self, body: bytes, content_type: str = "image/jpeg"):
        self.content = body
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, response):
        self.response = response

    def get(self, *args, **kwargs):
        return self.response

    def close(self):
        pass


class DownloaderCoreTests(unittest.TestCase):
    def test_page_number_and_identity(self):
        url = "https://www.mangago.me/read-manga/x/uu/to_chapter-1/pg-139/"
        self.assertEqual(_page_number_from_url(url), 139)
        self.assertEqual(_chapter_identity(url), "/read-manga/x/uu/to_chapter-1")

    def test_parse_chapters(self):
        html = '''<table class="listing">
        <tr><td><a class="chico" href="/read-manga/x/uu/to_chapter-1/pg-1/">Ch.1</a></td></tr>
        <tr><td><a class="chico" href="/read-manga/x/uu/to_chapter-2/pg-1/">Ch.2</a></td></tr>
        </table>'''
        chapters = _parse_chapters_from_html(html, "https://www.mangago.me/read-manga/x/")
        self.assertEqual([c.number for c in chapters], [1.0, 2.0])

    def test_valid_jpeg_becomes_png_and_original_is_preserved(self):
        image = Image.new("RGB", (8, 9), "white")
        buf = io.BytesIO()
        image.save(buf, "JPEG")

        with tempfile.TemporaryDirectory() as tmp:
            downloader = ChapterDownloader(download_dir=tmp, image_format="png", keep_originals=True)
            downloader.session = FakeSession(FakeResponse(buf.getvalue()))
            manga = Manga(title="Example", url="https://www.mangago.me/read-manga/example/")
            chapter = Chapter(number=1, url="https://www.mangago.me/read-manga/example/uu/to_chapter-1/pg-1/", image_urls=["https://iweb_1.mangapicgallery.com/a.jpg"])
            result = downloader.download_chapter(manga, chapter)
            self.assertTrue(result.success)
            chapter_dir = Path(result.file_path)
            self.assertTrue((chapter_dir / "page-001.png").exists())
            self.assertTrue((chapter_dir / "originais" / "page-001.jpg").exists())
            with Image.open(chapter_dir / "page-001.png") as converted:
                self.assertEqual(converted.size, (8, 9))

    def test_html_disguised_as_image_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloader = ChapterDownloader(download_dir=tmp)
            downloader.session = FakeSession(FakeResponse(b"<!DOCTYPE html>", "text/html"))
            manga = Manga(title="Example", url="https://www.mangago.me/read-manga/example/")
            chapter = Chapter(number=1, url="https://www.mangago.me/read-manga/example/uu/to_chapter-1/pg-1/", image_urls=["https://iweb_1.mangapicgallery.com/a.jpg"])
            result = downloader.download_chapter(manga, chapter)
            self.assertFalse(result.success)
            self.assertEqual(result.images_downloaded, 0)


if __name__ == "__main__":
    unittest.main()

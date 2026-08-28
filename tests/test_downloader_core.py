import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from gui.config import ConfigManager, DEFAULT_OUTPUT_DIR
from src.downloader import (
    ChapterDownloader,
    _chapter_dir_name,
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

    def test_default_download_location_points_to_project_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = ConfigManager(str(Path(tmp) / "gui_config.json"))
            self.assertEqual(config.get("download_location"), str(DEFAULT_OUTPUT_DIR))

    def test_manual_download_location_remains_sovereign(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom_dir = str(Path(tmp) / "custom")
            config_path = Path(tmp) / "gui_config.json"
            config_path.write_text(json.dumps({"download_location": custom_dir}), encoding="utf-8")
            config = ConfigManager(str(config_path))
            self.assertEqual(config.get("download_location"), custom_dir)

    def test_manga_and_chapter_directories_are_created_under_download_location(self):
        image = Image.new("RGB", (8, 9), "white")
        buf = io.BytesIO()
        image.save(buf, "JPEG")

        with tempfile.TemporaryDirectory() as tmp:
            downloader = ChapterDownloader(download_dir=tmp, image_format="original")
            downloader.session = FakeSession(FakeResponse(buf.getvalue()))
            manga = Manga(title="Emergency Youth Record Book", url="https://www.mangago.me/read-manga/example/")
            chapter = Chapter(number=1, url="https://www.mangago.me/read-manga/example/uu/to_chapter-1/pg-1/", image_urls=["https://iweb_1.mangapicgallery.com/a.jpg"])
            result = downloader.download_chapter(manga, chapter)
            self.assertTrue(result.success)
            chapter_dir = Path(tmp) / "Emergency Youth Record Book" / "Ch. 1"
            self.assertEqual(Path(result.file_path), chapter_dir)
            self.assertTrue(chapter_dir.is_dir())
            self.assertTrue((chapter_dir / "page-001.jpg").exists())

    def test_invalid_manga_and_chapter_names_are_sanitized(self):
        self.assertEqual(_chapter_dir_name(Chapter(number=2, url="https://example.test")), "Ch. 2")
        image = Image.new("RGB", (8, 9), "white")
        buf = io.BytesIO()
        image.save(buf, "JPEG")

        with tempfile.TemporaryDirectory() as tmp:
            downloader = ChapterDownloader(download_dir=tmp, image_format="original")
            downloader.session = FakeSession(FakeResponse(buf.getvalue()))
            manga = Manga(title='Bad:/Name?*|"', url="https://www.mangago.me/read-manga/example/")
            chapter = Chapter(number=2, url="https://www.mangago.me/read-manga/example/uu/to_chapter-2/pg-1/", image_urls=["https://iweb_1.mangapicgallery.com/a.jpg"])
            result = downloader.download_chapter(manga, chapter)
            self.assertTrue(result.success)
            self.assertTrue((Path(tmp) / "Bad__Name____" / "Ch. 2").is_dir())


if __name__ == "__main__":
    unittest.main()

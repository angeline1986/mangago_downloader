import unittest
from unittest.mock import patch
from src.downloader import ChapterDownloader
from src.models import Chapter, DownloadResult, Manga

class RidiDownloaderRoutingTests(unittest.TestCase):
    def test_ridi_routes_before_generic_flow(self):
        manga = Manga(title="RIDI Test", url="https://ridibooks.com/books/4895003169")
        chapter = Chapter(number=1, url="https://ridibooks.com/books/4895003169/view")
        expected = DownloadResult(chapter=chapter, success=True, expected_pages=3, images_downloaded=3)
        downloader = ChapterDownloader(download_dir="/tmp/ridi-routing-test")
        try:
            with patch("src.downloader.download_ridi_chapter", return_value=expected) as routed:
                result = downloader.download_chapter(manga, chapter)
        finally:
            downloader.close()
        self.assertIs(result, expected)
        routed.assert_called_once_with(downloader, manga, chapter, progress_callback=None)

    def test_non_ridi_empty_chapter_keeps_existing_failure(self):
        manga = Manga(title="Mangago Test", url="https://www.mangago.me/read-manga/example/")
        chapter = Chapter(number=1, url="https://www.mangago.me/read-manga/example/chapter-1/")
        downloader = ChapterDownloader(download_dir="/tmp/non-ridi-routing-test")
        try:
            result = downloader.download_chapter(manga, chapter)
        finally:
            downloader.close()
        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "No image URLs found.")

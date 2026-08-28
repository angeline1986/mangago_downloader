from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class DownloadEngineV3Contract(unittest.TestCase):
    def test_dropdown_reader_strategy_is_present(self):
        py = (ROOT / "src" / "downloader.py").read_text(encoding="utf-8")
        self.assertIn("#dropdown-menu-page", py)
        self.assertIn("_extract_reader_page_links", py)
        self.assertNotIn('next_link = page.locator("a.next_page")', py)

    def test_page_queue_resolves_reader_pages_inside_workers(self):
        py = (ROOT / "src" / "downloader.py").read_text(encoding="utf-8")
        self.assertIn("executor.submit(download_one, index, image_url)", py)
        self.assertIn("_resolve_reader_page_image", py)
        self.assertIn("for chapter in chapters:", py)
        self.assertIn("callback(chapter, done, total)", py)

    def test_web_discovers_reader_pages_before_download_queue(self):
        server = (ROOT / "webapp" / "server.py").read_text(encoding="utf-8")
        html = (ROOT / "webapp" / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn("discover_chapter_reader_pages_with_cookies(", server)
        self.assertIn("chapter.url,", server)
        self.assertIn("chapter.image_urls = page_urls", server)
        self.assertIn("Páginas simultâneas", html)
        self.assertIn("downloads simultâneos", server)

if __name__ == "__main__":
    unittest.main()

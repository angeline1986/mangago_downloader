"""Progress events and the Downloads page stay in sync."""
import asyncio
import tempfile
import threading
import unittest
from unittest.mock import patch

from playwright.async_api import async_playwright

from src.downloader import ChapterDownloader
from src.models import Chapter, DownloadResult, Manga
from webapp import server


class DownloadProgressTests(unittest.TestCase):
    def test_chapter_start_is_reported_before_download(self):
        chapter = Chapter(1, "https://example.test/chapter-1")
        events = []
        with tempfile.TemporaryDirectory() as directory:
            downloader = ChapterDownloader(download_dir=directory)
            downloader.chapter_start_callback = lambda item: events.append(("start", item.number))

            def download(_manga, item):
                events.append(("download", item.number))
                return DownloadResult(chapter=item, success=True)

            with patch.object(downloader, "download_chapter", side_effect=download):
                downloader.download_chapters(Manga("Demo", "https://example.test"), [chapter])
            downloader.close()
        self.assertEqual(events, [("start", 1), ("download", 1)])

    def test_failed_chapter_preserves_page_progress(self):
        job_id = "progress-failed"
        with server._jobs_lock:
            server._jobs[job_id] = {
                "chapters": [
                    {"status": "failed", "progress": 25},
                    {"status": "queued", "progress": 0},
                ],
            }
        try:
            server._refresh_job_progress(job_id)
            self.assertEqual(server._jobs[job_id]["progress"], 50)
            self.assertEqual(server._jobs[job_id]["chapters"][0]["progress"], 25)
        finally:
            with server._jobs_lock:
                server._jobs.pop(job_id, None)

    def test_page_updates_chapter_bar_when_page_finishes(self):
        job_id = "progress-ui"
        chapter_url = "https://example.test/chapter-1"
        with server._jobs_lock:
            server._jobs[job_id] = {
                "id": job_id, "state": "running", "phase": "downloading",
                "message": "Baixando capítulo 1…", "manga": {"title": "Demo"},
                "total": 1, "completed": 0, "progress": 0,
                "chapters": [{
                    "number": 1, "title": "Ch.1", "url": chapter_url,
                    "status": "downloading", "progress": 0,
                    "current_page": 0, "total_pages": 0,
                    "message": "Preparando leitor…", "pdf_status": "pending",
                }],
            }
        httpd = server.create_server("127.0.0.1", 0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        async def inspect():
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                try:
                    page = await browser.new_page()
                    await page.goto(f"http://127.0.0.1:{httpd.server_address[1]}")
                    await page.locator('[data-page="downloads"]').click()
                    bar = page.locator(".chapter-progress-track")
                    await bar.wait_for()
                    self.assertEqual(await bar.get_attribute("aria-valuenow"), "0")
                    self.assertEqual(await page.locator(".job-progress-track")
                                     .get_attribute("aria-valuenow"), "0")
                    self.assertEqual(await page.locator(".chapter-progress-fill")
                                     .get_attribute("style"), "width:0%")
                    self.assertEqual(await page.locator(".chapter-progress-fill")
                                     .evaluate("el => getComputedStyle(el).animationName"), "none")
                    server._update_chapter_row(
                        job_id, chapter_url, current_page=2, total_pages=5,
                        progress=40, message="Baixando · 2/5 páginas",
                    )
                    server._refresh_job_progress(job_id)
                    await page.wait_for_function(
                        "() => document.querySelector('.chapter-progress-track')"
                        ".getAttribute('aria-valuenow') === '40'"
                    )
                    self.assertEqual(await page.locator(".job-progress-track")
                                     .get_attribute("aria-valuenow"), "40")
                    self.assertIn("2/5 páginas", await page.locator(".queue-chapter").inner_text())
                finally:
                    await browser.close()

        try:
            asyncio.run(inspect())
        finally:
            httpd.shutdown()
            httpd.server_close()
            with server._jobs_lock:
                server._jobs.pop(job_id, None)

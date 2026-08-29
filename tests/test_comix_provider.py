import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.comix_provider import (
    DrawTile,
    _select_special_fetch_url,
    _validate_draw_tiles,
    is_comix_chapter_url,
    is_comix_title_url,
    rebuild_scrambled_image,
    download_comix_chapter,
)


class ComixProviderTests(unittest.TestCase):
    def test_comix_chapter_url_detection(self):
        self.assertTrue(
            is_comix_chapter_url(
                "https://comix.to/title/0kgln-emergency-youth-record-book/11256940-chapter-2"
            )
        )
        self.assertFalse(is_comix_chapter_url("https://comix.to/title/0kgln-emergency-youth-record-book"))
        self.assertFalse(is_comix_chapter_url("https://www.mangago.me/read-manga/test/"))

    def test_parse_comix_chapter_rows_deduplicates_and_sorts_by_url(self):
        from src.comix_provider import _parse_comix_chapter_rows

        rows = [
            {
                "url": "/title/test/111-chapter-2",
                "title": "Ch.2",
                "source": "TappyToon",
            },
            {
                "url": "/title/test/110-chapter-1",
                "title": "Ch.1",
                "source": "TappyToon",
            },
            {
                "url": "/title/test/111-chapter-2",
                "title": "Duplicado",
                "source": "TappyToon",
            },
        ]

        chapters = _parse_comix_chapter_rows(
            rows,
            "https://comix.to/title/test",
        )

        self.assertEqual([item["number"] for item in chapters], [1.0, 2.0])
        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0]["source"], "TappyToon")
        self.assertEqual(
            chapters[0]["url"],
            "https://comix.to/title/test/110-chapter-1",
        )

    def test_comix_title_url_detection(self):
        self.assertTrue(
            is_comix_title_url(
                "https://comix.to/title/0kgln-emergency-youth-record-book"
            )
        )
        self.assertTrue(
            is_comix_title_url(
                "https://www.comix.to/title/0kgln-emergency-youth-record-book/"
            )
        )
        self.assertFalse(
            is_comix_title_url(
                "https://comix.to/title/0kgln-emergency-youth-record-book/11256940-chapter-2"
            )
        )
        self.assertFalse(
            is_comix_title_url("https://www.mangago.me/read-manga/test/")
        )

    def test_grid_validation_is_dynamic(self):
        draws = []
        for i in range(6):
            col, row = i % 3, i // 3
            draws.append(DrawTile(col * 10, row * 10, 10, 10, col * 10, row * 10, 10, 10))
        self.assertEqual((3, 2), _validate_draw_tiles(draws))

    def test_rebuild_uses_captured_source_to_destination_geometry(self):
        # 2x2 tiles: red, green, blue, yellow.
        src = Image.new("RGB", (20, 20))
        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
        positions = [(0, 0), (10, 0), (0, 10), (10, 10)]
        for color, (x, y) in zip(colors, positions):
            tile = Image.new("RGB", (10, 10), color)
            src.paste(tile, (x, y))
        buf = io.BytesIO()
        src.save(buf, "PNG")

        # source 0->3, 1->2, 2->1, 3->0
        records = [
            dict(sx=0, sy=0, sw=10, sh=10, dx=10, dy=10, dw=10, dh=10),
            dict(sx=10, sy=0, sw=10, sh=10, dx=0, dy=10, dw=10, dh=10),
            dict(sx=0, sy=10, sw=10, sh=10, dx=10, dy=0, dw=10, dh=10),
            dict(sx=10, sy=10, sw=10, sh=10, dx=0, dy=0, dw=10, dh=10),
        ]
        rebuilt = rebuild_scrambled_image(buf.getvalue(), records)
        with Image.open(io.BytesIO(rebuilt)) as out:
            self.assertEqual((255, 255, 0), out.getpixel((5, 5)))
            self.assertEqual((0, 0, 255), out.getpixel((15, 5)))
            self.assertEqual((0, 255, 0), out.getpixel((5, 15)))
            self.assertEqual((255, 0, 0), out.getpixel((15, 15)))

    def test_comix_download_uses_comix_provider_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloader = SimpleNamespace(download_dir=tmp)

            manga = SimpleNamespace(title="Emergency Youth Record Book")
            chapter = SimpleNamespace(
                number=2,
                url="https://comix.to/title/test/123-chapter-2",
                image_urls=[],
            )

            import src.comix_provider as provider

            expected = Path(tmp) / "comix" / "Emergency Youth Record Book" / "Ch. 2"

            original_async = provider._download_comix_chapter_async
            try:
                async def fake_download(*args, **kwargs):
                    return provider.DownloadResult(
                        success=True,
                        chapter=chapter,
                        file_path=str(expected),
                        error_message=None,
                    )

                provider._download_comix_chapter_async = fake_download
                result = download_comix_chapter(downloader, manga, chapter)
            finally:
                provider._download_comix_chapter_async = original_async

            self.assertEqual(Path(result.file_path), expected)

    def test_special_fetch_selection_uses_latest_fetch_wowpic_with_query(self):
        entries = [
            {"name": "https://x.wowpic.store/a", "initiatorType": "img", "startTime": 10},
            {"name": "https://x.wowpic.store/a?8", "initiatorType": "fetch", "startTime": 20},
            {"name": "https://x.wowpic.store/b?8", "initiatorType": "fetch", "startTime": 30},
        ]
        self.assertEqual(
            "https://x.wowpic.store/b?8",
            _select_special_fetch_url(entries),
        )



class ComixSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_capture_special_snapshot_returns_png_from_preserved_canvas(self):
        from src.comix_provider import _capture_special_snapshot

        png_bytes = io.BytesIO()
        Image.new("RGB", (20, 30), (255, 0, 0)).save(png_bytes, "PNG")
        expected = png_bytes.getvalue()

        class FakeLocator:
            async def screenshot(self, **kwargs):
                self.kwargs = kwargs
                return expected

        class FakePage:
            def __init__(self):
                self.locator_value = FakeLocator()
                self.evaluate_calls = 0

            async def evaluate(self, script, *args):
                self.evaluate_calls += 1

                if self.evaluate_calls == 1:
                    return {"width": 20, "height": 30}

                return None

            def locator(self, selector):
                self.selector = selector
                return self.locator_value

        page = FakePage()

        result = await _capture_special_snapshot(page)

        self.assertEqual(result, expected)
        self.assertEqual(
            page.selector,
            "#__comix_snapshot_capture",
        )

        with Image.open(io.BytesIO(result)) as image:
            self.assertEqual(image.size, (20, 30))
            self.assertEqual(image.format, "PNG")

    async def test_capture_special_snapshot_returns_none_without_canvas(self):
        from src.comix_provider import _capture_special_snapshot

        class FakePage:
            async def evaluate(self, script, *args):
                return None

        result = await _capture_special_snapshot(FakePage())

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

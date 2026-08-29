import io
import unittest

from PIL import Image

from src.comix_provider import (
    DrawTile,
    _select_special_fetch_url,
    _validate_draw_tiles,
    is_comix_chapter_url,
    rebuild_scrambled_image,
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


if __name__ == "__main__":
    unittest.main()

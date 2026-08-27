import unittest
from pathlib import Path
from unittest.mock import patch
from tempfile import TemporaryDirectory
from PIL import Image
import io

from src.models import Manga, Chapter
from src.downloader import ChapterDownloader


class FakeResponse:
    headers = {"content-type": "image/jpeg"}
    def __init__(self, content): self.content = content
    def raise_for_status(self): return None


class GuiV2ContractTests(unittest.TestCase):
    def test_styles_do_not_use_unsupported_transform_property(self):
        text = Path("gui/styles.py").read_text(encoding="utf-8")
        self.assertNotIn("transform:", text)

    def test_default_delay_is_two_seconds_and_progress_callback_runs(self):
        image = Image.new("RGB", (4, 4), "white")
        buff = io.BytesIO(); image.save(buff, format="JPEG")
        events = []
        with TemporaryDirectory() as tmp:
            d = ChapterDownloader(download_dir=tmp, page_delay=2.0, progress_callback=lambda ch, cur, total: events.append((cur,total)))
            d.session.get = lambda *a, **k: FakeResponse(buff.getvalue())
            ch = Chapter(number=1.0, url="https://www.mangago.me/read-manga/x/pg-1/", image_urls=["https://cdn/x.jpg", "https://cdn/y.jpg"])
            with patch("src.downloader.time.sleep") as sleeper:
                result = d.download_chapter(Manga(title="X", url="https://www.mangago.me/x"), ch)
            d.close()
        self.assertTrue(result.success)
        self.assertEqual(events, [(1,2),(2,2)])
        sleeper.assert_called_once_with(2.0)


if __name__ == "__main__": unittest.main()

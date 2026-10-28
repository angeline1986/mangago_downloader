"""Normal Comix pages use the rendered reader response, not a second GET."""
import unittest

from src.comix_media import RenderedImageResponses
from src.utils import DownloadError


class FakePage:
    def on(self, event, callback):
        assert event == "response"
        self.receive = callback


class FakeResponse:
    def __init__(self, url, status=200, content_type="image/webp", kind="image"):
        self.url = url
        self.status = status
        self.headers = {"content-type": content_type}
        self.request = type("Request", (), {"resource_type": kind})()

    async def body(self):
        return b"rendered image"


class ComixMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_original_bytes_from_browser_response(self):
        page = FakePage()
        images = RenderedImageResponses(page)
        page.receive(FakeResponse("https://cdn.example/image.webp"))
        self.assertEqual(
            await images.read("https://cdn.example/image.webp"),
            (b"rendered image", "image/webp"),
        )

    async def test_rejects_unavailable_or_denied_response(self):
        page = FakePage()
        images = RenderedImageResponses(page)
        page.receive(FakeResponse("https://cdn.example/other", kind="document"))
        with self.assertRaisesRegex(DownloadError, "not observed"):
            await images.read("https://cdn.example/other")
        page.receive(FakeResponse("https://cdn.example/image", status=403))
        with self.assertRaisesRegex(DownloadError, "HTTP 403"):
            await images.read("https://cdn.example/image")

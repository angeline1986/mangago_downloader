"""Read image bytes already delivered to the rendered Comix reader."""
from __future__ import annotations

from .utils import DownloadError


class RenderedImageResponses:
    """Keep browser image responses until their page is saved."""

    def __init__(self, page):
        self._responses = {}
        page.on("response", self._remember)

    def _remember(self, response) -> None:
        if response.request.resource_type == "image":
            self._responses[response.url] = response

    async def read(self, image_url: str) -> tuple[bytes, str]:
        response = self._responses.pop(image_url, None)
        if response is None:
            raise DownloadError("Comix reader image response was not observed.")
        if response.status != 200:
            raise DownloadError(f"Comix reader image returned HTTP {response.status}.")
        content_type = response.headers.get("content-type", "")
        if not content_type.lower().startswith("image/"):
            raise DownloadError("Comix reader response is not an image.")
        raw = await response.body()
        if not raw:
            raise DownloadError("Comix reader image response is empty.")
        return raw, content_type

"""DOM inspection and controlled scroll helpers for Lezhin's indexed reader."""
from __future__ import annotations

import time

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .errors import LezhinReaderError
from .urls import is_lezhin_episode_url


_CUTS_JS = """() => Array.from(document.querySelectorAll('[data-cut-index]')).map(el => {
  const value = el.getAttribute('data-cut-index');
  const image = el.matches('img') ? el : el.querySelector('img');
  return {index: value, src: image ? (image.currentSrc || image.src || '') : '',
          loaded: !!image && image.complete && image.naturalWidth > 0};
})"""


def require_episode_access(url: str) -> None:
    """Reject a login redirect before waiting for reader selectors."""
    if not is_lezhin_episode_url(url):
        raise LezhinReaderError(
            "Episode redirected away from the reader; verify manual login and access"
        )


def read_cut_indexes(page: Page) -> tuple[int, ...]:
    """Read and validate the episode's complete, zero-based cut index set."""
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('[data-cut-index]').length > 0",
            timeout=15_000,
        )
    except PlaywrightTimeoutError as exc:
        raise LezhinReaderError("Episode reader did not expose indexed cuts") from exc
    rows = page.evaluate(_CUTS_JS)
    indexes: list[int] = []
    for row in rows:
        try:
            indexes.append(int(row["index"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise LezhinReaderError("Reader contains a cut without a numeric index") from exc
    indexes.sort()
    expected = list(range(len(indexes)))
    if not indexes or indexes != expected:
        raise LezhinReaderError("Reader cut indexes are empty, duplicated, or non-contiguous")
    return tuple(indexes)


def read_cut_image(page: Page, index: int) -> dict:
    """Read the currently materialized image URL for one indexed cut."""
    selector = f'[data-cut-index="{index}"]'
    rows = page.locator(selector).evaluate_all("""nodes => nodes.map(el => {
      const image = el.matches('img') ? el : el.querySelector('img');
      return image ? {src: image.currentSrc || image.src || '',
                      loaded: image.complete && image.naturalWidth > 0,
                      width: image.naturalWidth, height: image.naturalHeight} : null;
    }).filter(Boolean)""")
    if len(rows) != 1:
        return {"src": "", "loaded": False, "width": 0, "height": 0}
    return rows[0]


def scroll_to_cut(page: Page, index: int, timeout_ms: int) -> None:
    """Materialize a virtualized cut, then wait for its image to decode."""
    locator = page.locator(f'[data-cut-index="{index}"]').first
    try:
        locator.scroll_into_view_if_needed(timeout=timeout_ms)
        locator.evaluate("el => el.scrollIntoView({block:'center', behavior:'auto'})")
        page.wait_for_function("""index => {
          const el = document.querySelector(`[data-cut-index="${index}"]`);
          const image = el && (el.matches('img') ? el : el.querySelector('img'));
          return !!image && image.complete && image.naturalWidth > 0;
        }""", arg=index, timeout=timeout_ms)
    except PlaywrightTimeoutError as exc:
        raise LezhinReaderError(f"Cut {index} did not load before timeout") from exc


def wait_for_response(page: Page, responses: dict, image_url: str,
                      timeout_ms: int, index: int):
    """Wait for the Playwright response already produced by the authorized page."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        candidates = responses.get(image_url)
        if candidates:
            response = candidates.pop(0)
            if not candidates:
                responses.pop(image_url, None)
            return response
        page.wait_for_timeout(100)
    raise LezhinReaderError(f"No image response was observed for cut {index}")


def read_blob_cut_png(page: Page, index: int) -> bytes:
    """Export an authorized, already decoded blob image without HTTP refetch."""
    import base64

    result = page.locator(f'[data-cut-index="{index}"]').first.evaluate(r"""async el => {
      const image = el.matches('img') ? el : el.querySelector('img');
      if (!image || !image.currentSrc.startsWith('blob:') ||
          !image.complete || !image.naturalWidth || !image.naturalHeight)
        throw new Error('Blob image not ready');
      const canvas = document.createElement('canvas');
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      const context = canvas.getContext('2d');
      if (!context) throw new Error('2D canvas unavailable');
      context.drawImage(image, 0, 0);
      const blob = await new Promise((resolve, reject) =>
        canvas.toBlob(b => b ? resolve(b) : reject(new Error('PNG encoding failed')), 'image/png'));
      const array = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let i = 0; i < array.length; i += 32768)
        binary += String.fromCharCode(...array.subarray(i, i + 32768));
      return {data: btoa(binary), width: canvas.width, height: canvas.height};
    }""")
    if not isinstance(result, dict) or not result.get('data'):
        raise LezhinReaderError(f'Blob capture failed for cut {index}')
    try:
        return base64.b64decode(result['data'], validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise LezhinReaderError(f'Invalid blob PNG for cut {index}') from exc

"""Incremental capture pipeline for authorized Lezhin episode images."""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from playwright.sync_api import Page

from .errors import LezhinCaptureError, LezhinIncompleteError, LezhinReaderError
from .persistence import PersistedCut, persist_cut
from .reader import (read_cut_image, read_cut_indexes, require_episode_access,
                     scroll_to_cut, wait_for_response)
from .session import lezhin_cdp_session
from .urls import validate_episode_url
from .validation import CaptureValidation, validate_capture


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CaptureResult:
    episode_url: str
    cuts: tuple[PersistedCut, ...]
    validation: CaptureValidation


def _observe_image_responses(page: Page) -> tuple[dict, object]:
    """Buffer image responses briefly by URL; never log or expose signed URLs."""
    responses: dict = defaultdict(list)

    def observe(response) -> None:
        try:
            if (response.request.resource_type != "image"
                    or urlsplit(response.url).scheme != "https"):
                return
            queue = responses[response.url]
            queue.append(response)
            if len(queue) > 2:
                del queue[:-2]
            if len(responses) > 300:
                responses.pop(next(iter(responses)))
        except Exception:
            return

    page.on("response", observe)
    return responses, observe


def _capture_page(page: Page, episode_url: str, destination: Path,
                  progress_callback, expected_callback, chapter,
                  timeout_ms: int) -> CaptureResult:
    page.on("close", lambda: LOGGER.info("[LEZHIN][SESSION] página encerrada"))
    responses, observer = _observe_image_responses(page)
    try:
        return _capture_observed_page(page, episode_url, destination, progress_callback,
                                      expected_callback, chapter, timeout_ms, responses)
    finally:
        page.remove_listener("response", observer)


def _capture_observed_page(page: Page, episode_url: str, destination: Path,
                           progress_callback, expected_callback, chapter, timeout_ms: int,
                           responses: dict) -> CaptureResult:
    navigation = page.goto(episode_url, wait_until="domcontentloaded", timeout=timeout_ms)
    if navigation is not None and navigation.status >= 400:
        raise LezhinReaderError(f"Episode navigation returned HTTP {navigation.status}")
    require_episode_access(page.url)
    indexes = read_cut_indexes(page)
    if expected_callback:
        expected_callback(len(indexes))
    LOGGER.info("[LEZHIN][READER] Cortes esperados: %d", len(indexes))
    saved: list[PersistedCut] = []
    for index in indexes:
        scroll_to_cut(page, index, timeout_ms)
        image = read_cut_image(page, index)
        if not image["loaded"] or not image["src"]:
            raise LezhinCaptureError(f"Cut {index} has no decoded image")
        response = wait_for_response(page, responses, image["src"], timeout_ms, index)
        if response.status != 200:
            raise LezhinCaptureError(f"Image response for cut {index} returned HTTP {response.status}")
        mime = response.headers.get("content-type", "")
        if not mime.lower().startswith("image/"):
            raise LezhinCaptureError(f"Cut {index} response did not declare an image MIME type")
        try:
            content = response.body()
        except Exception as exc:
            raise LezhinCaptureError(f"Could not read image response body for cut {index}") from exc
        try:
            item = persist_cut(destination, index, content, mime)
        finally:
            del content
        saved.append(item)
        LOGGER.info("[LEZHIN][SAVE] Corte %d validado", index)
        if progress_callback:
            progress_callback(chapter, len(saved), len(indexes))
        LOGGER.info("[LEZHIN][PROGRESS] %d/%d", len(saved), len(indexes))
    validation = validate_capture(destination, indexes)
    if not validation.valid:
        raise LezhinIncompleteError(
            f"Episode is incomplete: missing={validation.missing_indexes}, "
            f"duplicates={validation.duplicate_indexes}, invalid={validation.invalid_indexes}"
        )
    return CaptureResult(page.url.split("?", 1)[0].split("#", 1)[0], tuple(saved), validation)


def capture_episode(episode_url: str, output_dir: str | Path, progress_callback=None,
                    *, chapter=None, cdp_url: str | None = None,
                    timeout_ms: int = 20_000,
                    expected_callback: Callable[[int], None] | None = None) -> CaptureResult:
    """Capture one authorized episode by attaching to the dedicated CDP browser.

    Progress follows the existing downloader callback shape: ``(chapter, done, total)``.
    The browser process remains externally owned and no HTTP is made outside its page.
    """
    url = validate_episode_url(episode_url)
    if timeout_ms < 1000:
        raise ValueError("timeout_ms must be at least 1000")
    destination = Path(output_dir).expanduser()
    try:
        with lezhin_cdp_session(cdp_url) as session:
            return _capture_page(session.page, url, destination,
                                 progress_callback, expected_callback,
                                 chapter, timeout_ms)
    except LezhinReaderError:
        raise
    except LezhinCaptureError:
        raise
    except Exception as exc:
        raise LezhinReaderError("Episode capture stopped because browser/session access failed") from exc

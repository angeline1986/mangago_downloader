"""Adapt the Lezhin capture core to the shared chapter download contracts."""
from __future__ import annotations

from pathlib import Path

from ..chapter_validation import (
    remove_download_complete_marker,
    write_download_in_progress_marker,
)
from ..models import DownloadResult
from ..output_paths import chapter_image_dir
from ..utils import sanitize_filename
from .capture import capture_episode
from .urls import LEZHIN_PROVIDER_ID, is_lezhin_episode_url


def _chapter_folder(chapter) -> str:
    """Keep the existing downloader's numeric chapter directory convention."""
    return sanitize_filename(f"{float(chapter.number):g}")


def download_lezhin_chapter(downloader, manga, chapter, progress_callback=None) -> DownloadResult:
    """Capture one episode, finalize through shared validation, and report failures."""
    if not is_lezhin_episode_url(getattr(chapter, "url", None)):
        return DownloadResult(chapter, False, error_message="Invalid Lezhin episode URL")
    chapter_dir = str(chapter_image_dir(
        downloader.download_dir, LEZHIN_PROVIDER_ID, sanitize_filename(manga.title),
        _chapter_folder(chapter),
    ))
    remove_download_complete_marker(chapter_dir)
    write_download_in_progress_marker(chapter_dir, expected_pages=0)
    callback = progress_callback or getattr(downloader, "progress_callback", None)
    state = {"expected": 0, "done": 0}

    def expected(total: int) -> None:
        state["expected"] = total
        write_download_in_progress_marker(chapter_dir, expected_pages=total)

    def progress(_chapter, done: int, total: int) -> None:
        state["done"] = done
        if callback:
            callback(chapter, done, total)

    try:
        capture = capture_episode(
            chapter.url, Path(chapter_dir), progress_callback=progress,
            chapter=chapter, expected_callback=expected,
        )
        total = len(capture.cuts)
        result = DownloadResult(
            chapter, capture.validation.valid, file_path=chapter_dir,
            images_downloaded=state["done"], expected_pages=total,
        )
    except Exception as exc:
        result = DownloadResult(
            chapter, False, file_path=chapter_dir,
            error_message=str(exc), images_downloaded=state["done"],
            expected_pages=state["expected"],
        )
    return downloader._finalize_download_result(
        result, expected_pages=result.expected_pages,
    )

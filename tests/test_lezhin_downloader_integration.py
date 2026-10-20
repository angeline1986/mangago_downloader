import io
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.chapter_validation import DOWNLOAD_COMPLETE_FILE, DOWNLOAD_IN_PROGRESS_FILE
from src.downloader import ChapterDownloader
from src.lezhin.capture import CaptureResult
from src.lezhin.downloader import download_lezhin_chapter
from src.lezhin.persistence import persist_cut
from src.lezhin.validation import CaptureValidation
from src.models import Chapter, DownloadResult, Manga


URL = "https://www.lezhinus.com/en/comic/presidentlonglegs/1"


def webp(color):
    output = io.BytesIO()
    Image.new("RGB", (8, 10), color).save(output, "WEBP")
    return output.getvalue()


def make_chapter():
    return Chapter(number=1, url=URL, title="Episode 1")


def test_downloader_routes_lezhin_before_generic_flow(tmp_path):
    manga, chapter = Manga("Long Legs", URL), make_chapter()
    downloader = ChapterDownloader(download_dir=str(tmp_path))
    expected = DownloadResult(chapter, True, expected_pages=2, images_downloaded=2)
    try:
        with patch("src.downloader.download_lezhin_chapter", return_value=expected) as route:
            result = downloader.download_chapter(manga, chapter)
    finally:
        downloader.close()
    assert result is expected
    route.assert_called_once_with(downloader, manga, chapter, progress_callback=None)


def test_download_result_path_progress_and_shared_completion(tmp_path):
    manga, chapter = Manga("Long Legs", URL), make_chapter()
    downloader = ChapterDownloader(download_dir=str(tmp_path))
    folder = tmp_path / "lezhinus" / "Long Legs" / "IMG" / "1"
    progress = []

    def capture(_url, output_dir, progress_callback, chapter, expected_callback):
        assert output_dir == folder
        expected_callback(2)
        pages = []
        for index, color in enumerate(("red", "blue")):
            saved = persist_cut(output_dir, index, webp(color), "image/webp")
            pages.append(saved)
            progress_callback(chapter, index + 1, 2)
        validation = CaptureValidation(True, (0, 1), (0, 1))
        return CaptureResult(URL, tuple(pages), validation)

    def callback(_chapter, done, total):
        assert (folder / f"page-{done:03d}.webp").is_file()
        progress.append((done, total))

    try:
        with patch("src.lezhin.downloader.capture_episode", side_effect=capture):
            result = download_lezhin_chapter(downloader, manga, chapter, callback)
    finally:
        downloader.close()
    assert isinstance(result, DownloadResult)
    assert result.success and result.validation.valid
    assert (result.expected_pages, result.images_downloaded) == (2, 2)
    assert result.file_path == str(folder)
    assert progress == [(1, 2), (2, 2)]
    assert (folder / DOWNLOAD_COMPLETE_FILE).is_file()
    assert not (folder / DOWNLOAD_IN_PROGRESS_FILE).exists()


def test_partial_capture_is_incomplete_then_resumes_idempotently(tmp_path):
    manga, chapter = Manga("Long Legs", URL), make_chapter()
    downloader = ChapterDownloader(download_dir=str(tmp_path))
    folder = tmp_path / "lezhinus" / "Long Legs" / "IMG" / "1"
    first = persist_cut(folder, 0, webp("red"), "image/webp")

    def interrupted(_url, output_dir, progress_callback, chapter, expected_callback):
        expected_callback(2)
        saved = persist_cut(output_dir, 0, webp("red"), "image/webp")
        assert saved.sha256 == first.sha256
        progress_callback(chapter, 1, 2)
        raise RuntimeError("CDP connection lost")

    def resumed(_url, output_dir, progress_callback, chapter, expected_callback):
        expected_callback(2)
        first_saved = persist_cut(output_dir, 0, webp("red"), "image/webp")
        second_saved = persist_cut(output_dir, 1, webp("blue"), "image/webp")
        assert first_saved.sha256 == first.sha256
        progress_callback(chapter, 1, 2)
        progress_callback(chapter, 2, 2)
        return CaptureResult(
            URL, (first_saved, second_saved),
            CaptureValidation(True, (0, 1), (0, 1)),
        )

    try:
        with patch("src.lezhin.downloader.capture_episode") as capture:
            capture.side_effect = interrupted
            partial = download_lezhin_chapter(downloader, manga, chapter)
            progress_marker_remains = (folder / DOWNLOAD_IN_PROGRESS_FILE).is_file()
            capture.side_effect = resumed
            result = download_lezhin_chapter(downloader, manga, chapter)
    finally:
        downloader.close()
    assert not partial.success
    assert partial.images_downloaded == 1 and partial.expected_pages == 2
    assert partial.validation.missing_pages == [2]
    assert progress_marker_remains
    assert result.success and result.validation.valid
    assert (result.images_downloaded, result.expected_pages) == (2, 2)
    assert (folder / DOWNLOAD_COMPLETE_FILE).is_file()
    assert not (folder / DOWNLOAD_IN_PROGRESS_FILE).exists()


def test_invalid_url_and_session_loss_return_failed_download_results(tmp_path):
    manga = Manga("Long Legs", URL)
    bad = Chapter(1, "https://example.test/chapter/1")
    downloader = ChapterDownloader(download_dir=str(tmp_path))
    try:
        invalid = download_lezhin_chapter(downloader, manga, bad)
        chapter = make_chapter()
        with patch("src.lezhin.downloader.capture_episode", side_effect=RuntimeError("CDP down")):
            disconnected = download_lezhin_chapter(downloader, manga, chapter)
    finally:
        downloader.close()
    assert not invalid.success and "URL" in invalid.error_message
    assert not disconnected.success and disconnected.expected_pages == 0
    assert "CDP down" in disconnected.error_message

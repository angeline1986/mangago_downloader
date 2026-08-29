import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.chapter_validation import validate_chapter_images


def create_image(path: Path, size=(20, 30), image_format="PNG"):
    Image.new("RGB", size, (255, 255, 255)).save(path, image_format)


class ChapterValidationTests(unittest.TestCase):
    def test_complete_chapter_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp)

            for number in range(1, 4):
                create_image(chapter_dir / f"page-{number:03d}.png")

            result = validate_chapter_images(chapter_dir, expected_pages=3)

            self.assertTrue(result.valid)
            self.assertEqual(result.found_pages, 3)
            self.assertEqual(result.valid_pages, 3)
            self.assertEqual(result.missing_pages, [])
            self.assertEqual(result.invalid_pages, [])
            self.assertEqual(result.duplicate_pages, [])

    def test_missing_page_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp)

            create_image(chapter_dir / "page-001.png")
            create_image(chapter_dir / "page-003.png")

            result = validate_chapter_images(chapter_dir, expected_pages=3)

            self.assertFalse(result.valid)
            self.assertEqual(result.missing_pages, [2])

    def test_corrupted_page_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp)

            create_image(chapter_dir / "page-001.png")
            (chapter_dir / "page-002.png").write_bytes(b"not-an-image")

            result = validate_chapter_images(chapter_dir, expected_pages=2)

            self.assertFalse(result.valid)
            self.assertEqual(result.invalid_pages, [2])

    def test_duplicate_page_number_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp)

            create_image(chapter_dir / "page-001.png")
            create_image(
                chapter_dir / "page-001.jpg",
                image_format="JPEG",
            )

            result = validate_chapter_images(chapter_dir, expected_pages=1)

            self.assertFalse(result.valid)
            self.assertEqual(result.duplicate_pages, [1])

    def test_unrelated_files_and_subdirectories_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp)

            create_image(chapter_dir / "page-001.png")
            (chapter_dir / "chapter.pdf").write_bytes(b"%PDF-test")
            (chapter_dir / "notes.txt").write_text("ignore me")

            originals = chapter_dir / "originais"
            originals.mkdir()
            create_image(originals / "page-999.png")

            result = validate_chapter_images(chapter_dir, expected_pages=1)

            self.assertTrue(result.valid)
            self.assertEqual(result.found_pages, 1)

    def test_extra_page_makes_chapter_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp)

            create_image(chapter_dir / "page-001.png")
            create_image(chapter_dir / "page-002.png")

            result = validate_chapter_images(chapter_dir, expected_pages=1)

            self.assertFalse(result.valid)
            self.assertEqual(result.found_pages, 2)


if __name__ == "__main__":
    unittest.main()


class DownloadFinalizerTests(unittest.TestCase):
    def test_finalize_keeps_success_for_valid_chapter(self):
        from src.downloader import ChapterDownloader
        from src.models import Chapter, DownloadResult

        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp)

            create_image(chapter_dir / "page-001.png")
            create_image(chapter_dir / "page-002.png")

            downloader = object.__new__(ChapterDownloader)

            result = DownloadResult(
                chapter=Chapter(number=1, url="https://example.com/chapter-1"),
                success=True,
                file_path=str(chapter_dir),
                images_downloaded=2,
            )

            finalized = downloader._finalize_download_result(
                result,
                expected_pages=2,
            )

            self.assertTrue(finalized.success)
            self.assertEqual(finalized.expected_pages, 2)
            self.assertIsNotNone(finalized.validation)
            self.assertTrue(finalized.validation.valid)
            self.assertIsNone(finalized.error_message)

    def test_finalize_marks_failure_when_page_is_missing(self):
        from src.downloader import ChapterDownloader
        from src.models import Chapter, DownloadResult

        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp)

            create_image(chapter_dir / "page-001.png")
            create_image(chapter_dir / "page-003.png")

            downloader = object.__new__(ChapterDownloader)

            result = DownloadResult(
                chapter=Chapter(number=1, url="https://example.com/chapter-1"),
                success=True,
                file_path=str(chapter_dir),
                images_downloaded=2,
            )

            finalized = downloader._finalize_download_result(
                result,
                expected_pages=3,
            )

            self.assertFalse(finalized.success)
            self.assertEqual(finalized.expected_pages, 3)
            self.assertIsNotNone(finalized.validation)
            self.assertEqual(finalized.validation.missing_pages, [2])
            self.assertIn("missing pages: 2", finalized.error_message)
            self.assertIn("found 2/3 pages", finalized.error_message)

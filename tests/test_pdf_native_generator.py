import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.converter import _get_image_files, convert_manga_chapters, convert_to_pdf
from src.pdf.analyzer import analyze_directory
from src.pdf.image_normalizer import fix_exif_orientation, normalize_for_pdf


def write_image(path: Path, mode: str = "RGB", size=(8, 9), color="white", exif=None) -> None:
    image = Image.new(mode, size, color)
    if exif is None:
        image.save(path)
    else:
        image.save(path, exif=exif)


class NativePdfGeneratorTests(unittest.TestCase):
    def test_normalize_for_pdf_keeps_same_canvas_and_center_image(self):
        img = Image.new("RGB", (100, 200), (10, 20, 30))
        result = normalize_for_pdf(img, target_size=(140, 240), padding=20)

        self.assertEqual(result.size, (140, 240))
        self.assertEqual(result.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(result.getpixel((70, 120)), (10, 20, 30))

    def test_page_files_use_natural_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("page-010.jpg", "page-001.jpg", "page-002.jpg"):
                write_image(root / name)

            ordered = [Path(path).name for path in _get_image_files(tmp)]

        self.assertEqual(ordered, ["page-001.jpg", "page-002.jpg", "page-010.jpg"])

    def test_pdf_is_created_inside_chapter_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp) / "Emergency Youth Record Book" / "Ch. 1"
            chapter_dir.mkdir(parents=True)
            write_image(chapter_dir / "page-001.jpg")

            with patch("src.pdf.generator.img2pdf.convert", return_value=b"%PDF-1.4\n"):
                output = convert_to_pdf(str(chapter_dir))

            self.assertEqual(Path(output), chapter_dir / "Ch. 1.pdf")
            self.assertEqual((chapter_dir / "Ch. 1.pdf").read_bytes(), b"%PDF-1.4\n")

    def test_img2pdf_remains_primary_path_for_compatible_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp) / "Ch. 1"
            chapter_dir.mkdir()
            write_image(chapter_dir / "page-001.jpg")

            with patch("src.pdf.generator.img2pdf.convert", return_value=b"%PDF-primary\n") as convert:
                output = convert_to_pdf(str(chapter_dir))

            self.assertTrue(Path(output).exists())
            convert.assert_called_once()

    def test_alpha_image_uses_normalization_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapter_dir = Path(tmp) / "Ch. 1"
            chapter_dir.mkdir()
            write_image(chapter_dir / "page-001.png", mode="RGBA", color=(255, 0, 0, 128))

            with patch("src.pdf.generator.img2pdf.convert") as convert:
                output = convert_to_pdf(str(chapter_dir))

            convert.assert_not_called()
            self.assertTrue(Path(output).exists())
            self.assertTrue(Path(output).read_bytes().startswith(b"%PDF"))

    def test_exif_orientation_is_applied(self):
        img = Image.new("RGB", (4, 8), "white")
        exif = Image.Exif()
        exif[274] = 6
        buf = io.BytesIO()
        img.save(buf, "JPEG", exif=exif)

        with Image.open(io.BytesIO(buf.getvalue())) as loaded:
            fixed = fix_exif_orientation(loaded)

        self.assertEqual(fixed.size, (8, 4))

    def test_empty_chapter_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(convert_to_pdf(tmp))

    def test_convert_manga_chapters_generates_one_pdf_per_chapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            manga_dir = Path(tmp) / "Manga"
            for chapter in ("Ch. 1", "Ch. 2"):
                chapter_dir = manga_dir / chapter
                chapter_dir.mkdir(parents=True)
                write_image(chapter_dir / "page-001.jpg")

            with patch("src.pdf.generator.img2pdf.convert", return_value=b"%PDF-1.4\n"):
                created = convert_manga_chapters(str(manga_dir), format="pdf")

            self.assertEqual([Path(path).name for path in created], ["Ch. 1.pdf", "Ch. 2.pdf"])
            self.assertTrue((manga_dir / "Ch. 1" / "Ch. 1.pdf").exists())
            self.assertTrue((manga_dir / "Ch. 2" / "Ch. 2.pdf").exists())

    def test_pdf_modules_do_not_depend_on_gera_pdf_input_or_output(self):
        root = Path(__file__).resolve().parents[1] / "src" / "pdf"
        text = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
        self.assertNotIn("Gera_pdf", text)
        self.assertNotIn("input/", text)
        self.assertNotIn("output/pdfs", text)

    def test_analyzer_reports_alpha_without_printing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_image(root / "page-001.png", mode="RGBA", color=(0, 0, 0, 0))
            report = analyze_directory(root)

        self.assertEqual(report["total"], 1)
        self.assertEqual(report["alpha_count"], 1)
        self.assertTrue(report["needs_normalization"])


if __name__ == "__main__":
    unittest.main()

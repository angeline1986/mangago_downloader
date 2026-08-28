import json
import tempfile
import unittest
from pathlib import Path

from gui.config import ConfigManager

ROOT = Path(__file__).resolve().parents[1]

class OriginalQualityContractTests(unittest.TestCase):
    def test_original_is_default_everywhere(self):
        downloader = (ROOT / "src/downloader.py").read_text(encoding="utf-8")
        config = (ROOT / "gui/config.py").read_text(encoding="utf-8")
        server = (ROOT / "webapp/server.py").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            current = ConfigManager(str(Path(tmp) / "gui_config.json")).get_all()
        self.assertIn('image_format: str = "original"', downloader)
        self.assertIn('keep_originals: bool = False', downloader)
        self.assertIn('"image_format": "original"', config)
        self.assertIn('"keep_originals": False', config)
        self.assertIn('settings.get("image_format", "original")', server)
        self.assertEqual(current["image_format"], "original")
        self.assertFalse(current["keep_originals"])

    def test_persisted_user_image_format_is_not_overwritten_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "gui_config.json"
            config_path.write_text(json.dumps({"image_format": "png"}), encoding="utf-8")
            current = ConfigManager(str(config_path)).get_all()
        self.assertEqual(current["image_format"], "png")
        self.assertFalse(current["keep_originals"])

    def test_original_mode_writes_raw_bytes(self):
        downloader = (ROOT / "src/downloader.py").read_text(encoding="utf-8")
        self.assertIn('if self.image_format == "original":', downloader)
        self.assertIn('Path(output_path).write_bytes(raw)', downloader)

    def test_web_ui_explains_original_mode(self):
        html = (ROOT / "webapp/templates/index.html").read_text(encoding="utf-8")
        js = (ROOT / "webapp/static/app.js").read_text(encoding="utf-8")
        self.assertIn("Original — sem perda de qualidade", html)
        self.assertIn("sem conversão ou recompressão", html)
        self.assertIn("keepOriginalsRow", html)
        self.assertIn("syncImageFormatUi", js)
        self.assertIn("$('#imageFormat').value==='png'", js)

    def test_cbz_preserves_source_images(self):
        converter = (ROOT / "src/converter.py").read_text(encoding="utf-8")
        self.assertIn("zipf.write(image_file, arcname)", converter)

    def test_pdf_uses_img2pdf(self):
        converter = (ROOT / "src/converter.py").read_text(encoding="utf-8")
        self.assertIn("img2pdf.convert", converter)

if __name__ == "__main__":
    unittest.main()

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class SettingsV2ContractTests(unittest.TestCase):
    def test_settings_page_is_preferences_only_and_autosaves(self):
        text = (ROOT / "gui" / "download_widget.py").read_text(encoding="utf-8")
        self.assertIn("Alterações salvas automaticamente", text)
        self.assertIn("Formato do download", text)
        self.assertIn("Intervalo entre páginas", text)
        self.assertNotIn('QPushButton("Iniciar download")', text)
        self.assertIn("page_delay", text)
        self.assertIn("2.0", text)

    def test_download_starts_from_manga_selection(self):
        text = (ROOT / "gui" / "main_window.py").read_text(encoding="utf-8")
        self.assertIn("self._download(self.download_widget.get_download_config())", text)
        self.assertNotIn("self.download_widget.download_requested.connect(self._download)", text)

    def test_styles_have_settings_components_without_transform(self):
        text = (ROOT / "gui" / "styles.py").read_text(encoding="utf-8")
        self.assertIn("QFrame#settingsCard", text)
        self.assertIn("QPushButton.segment", text)
        self.assertIn("QCheckBox#switch", text)
        self.assertNotIn("transform:", text)


if __name__ == "__main__":
    unittest.main()

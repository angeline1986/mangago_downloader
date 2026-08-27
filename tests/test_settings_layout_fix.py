import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class SettingsLayoutFixTests(unittest.TestCase):
    def test_settings_content_is_centered_and_bounded(self):
        text = (ROOT / "gui" / "download_widget.py").read_text(encoding="utf-8")
        self.assertIn('content.setMaximumWidth(1040)', text)
        self.assertIn('AlignHCenter', text)
        self.assertIn('control_host.setMinimumWidth(360)', text)
        self.assertIn('compact=True', text)

    def test_controls_have_readable_widths(self):
        text = (ROOT / "gui" / "download_widget.py").read_text(encoding="utf-8")
        self.assertIn('self.image_format.setMinimumWidth(300)', text)
        self.assertGreaterEqual(text.count('setFixedWidth(150)'), 4)

    def test_spinbox_buttons_are_styled(self):
        text = (ROOT / "gui" / "styles.py").read_text(encoding="utf-8")
        self.assertIn('QSpinBox::up-button', text)
        self.assertIn('QDoubleSpinBox::down-button', text)
        self.assertNotIn('transform:', text)

if __name__ == "__main__":
    unittest.main()

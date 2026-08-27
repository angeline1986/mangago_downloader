import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class ChapterTypeFilterContractTests(unittest.TestCase):
    def test_filter_assets_are_present(self):
        js = (ROOT / "webapp/static/app.js").read_text(encoding="utf-8")
        css = (ROOT / "webapp/static/styles.css").read_text(encoding="utf-8")
        self.assertIn("CHAPTER_TYPE_FILTER_V1", js)
        self.assertIn('data-version="official"', js)
        self.assertIn('data-version="regular"', js)
        self.assertIn('includes("official")', js)
        self.assertIn("CHAPTER_TYPE_FILTER_V1", css)
        self.assertIn("tr[hidden]", css)

    def test_filter_has_three_modes(self):
        js = (ROOT / "webapp/static/app.js").read_text(encoding="utf-8")
        for mode in ("all", "official", "regular"):
            self.assertIn(f'data-version="{mode}"', js)

if __name__ == "__main__":
    unittest.main()

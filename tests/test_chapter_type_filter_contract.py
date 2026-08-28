import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class ChapterTypeFilterContractTests(unittest.TestCase):
    def test_filter_is_integrated_without_mutation_observer(self):
        js = (ROOT / "webapp/static/app.js").read_text(encoding="utf-8")
        html = (ROOT / "webapp/templates/index.html").read_text(encoding="utf-8")
        self.assertNotIn("MutationObserver", js)
        self.assertIn("chapterTypeSegment", html)
        self.assertIn("visibleChapterIndexes", js)
        self.assertIn("chapterType(ch)", js)

    def test_filter_has_three_modes(self):
        html = (ROOT / "webapp/templates/index.html").read_text(encoding="utf-8")
        for mode in ("all", "official", "regular"):
            self.assertIn(f'data-value="{mode}"', html)

if __name__ == "__main__":
    unittest.main()

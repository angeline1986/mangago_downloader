import unittest
from src.downloader import _extract_reader_chapter_label, _extract_reader_page_links

HTML = """
<div class="btn-group">
  <ul id="dropdown-menu-page" class="dropdown-menu page">
    <li><a href="/read-manga/demo/uu/br_chapter-367002/pg-1/">page 1 of 3</a></li>
    <li><a href="/read-manga/demo/uu/br_chapter-367002/pg-2/">page 2 of 3</a></li>
    <li><a href="/read-manga/demo/uu/br_chapter-367002/pg-3/">page 3 of 3</a></li>
  </ul>
</div>
<div id="navi"><h3><span><a id="series">Demo</a></span><span>&gt;</span><span>Ch.2</span></h3></div>
"""

class MangagoDropdownParserTests(unittest.TestCase):
    def test_extracts_all_pages_in_order(self):
        urls = _extract_reader_page_links(HTML, "https://www.mangago.me/read-manga/demo/uu/br_chapter-367002/pg-1/")
        self.assertEqual(3, len(urls))
        self.assertTrue(urls[0].endswith("/pg-1/"))
        self.assertTrue(urls[-1].endswith("/pg-3/"))

    def test_extracts_chapter_label(self):
        self.assertEqual("Ch.2", _extract_reader_chapter_label(HTML))

if __name__ == "__main__":
    unittest.main()

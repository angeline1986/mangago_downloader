"""Regression tests for groups appearing after the first title page."""
import unittest

from playwright.async_api import async_playwright

from src.comix_catalog import collect_chapter_groups


BASE = "https://comix.to/title/test"


def catalog_html(group: str, official: bool, page: int) -> str:
    group_class = "is-official" if official else ""
    return f"""
      <div class="mchap-item">
        <a href="/groups/{group}" class="mchap-row__group {group_class}">
          {"Lezhin" if official else "Fan Scan"}
        </a>
      </div>
      <nav class="npager">
        <button class="npager__num">1</button>
        <button class="npager__num">2</button>
      </nav>
      <span data-page="{page}"></span>
    """


class ComixCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_finds_official_group_on_second_catalog_page(self):
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page()

                async def respond(route):
                    second = "page=2" in route.request.url
                    await route.fulfill(
                        body=catalog_html("10485" if second else "226", second,
                                          2 if second else 1),
                        content_type="text/html",
                    )

                await page.route(f"{BASE}*", respond)
                await page.goto(BASE)
                groups = await collect_chapter_groups(page, BASE, 5000)
                self.assertEqual([group["name"] for group in groups],
                                 ["Lezhin", "Fan Scan"])
                self.assertEqual([group["official"] for group in groups],
                                 [True, False])
            finally:
                await browser.close()

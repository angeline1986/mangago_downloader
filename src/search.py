"""Search and manga metadata extraction using Playwright."""
from __future__ import annotations

import re
import urllib.parse
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .browser import browser_page
from .models import Manga, SearchResult
from .utils import ParsingError

BASE_URL = "https://www.mangago.me/"
SEARCH_URL = "https://www.mangago.me/r/l_search/"


def search_manga(query: str, page: int = 1) -> List[SearchResult]:
    """Search manga titles while allowing the browser to render dynamic content."""
    encoded_query = urllib.parse.quote_plus(query)
    search_url = f"{SEARCH_URL}?name={encoded_query}&page={page}"
    with browser_page(headless=True) as browser:
        browser.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
        browser.locator("#search_list").wait_for(state="attached", timeout=15_000)
        soup = BeautifulSoup(browser.content(), "html.parser")
    return _parse_search_results(soup)


def _parse_search_results(soup: BeautifulSoup) -> List[SearchResult]:
    results: List[SearchResult] = []
    for index, li in enumerate(soup.select("#search_list li"), start=1):
        try:
            manga = _parse_manga_item(li)
            if manga:
                results.append(SearchResult(index=index, manga=manga))
        except Exception as exc:
            print(f"Warning: Failed to parse a search result item: {exc}")
    return results


def _parse_manga_item(item: Tag) -> Optional[Manga]:
    title_tag = item.select_one("h2 a")
    if not title_tag:
        return None
    title = title_tag.get_text(strip=True)
    url = title_tag.get("href")
    if not title or not isinstance(url, str):
        return None
    url = urljoin(BASE_URL, url)
    manga = Manga(title=title, url=url)

    author = item.select_one(".row-3.gray")
    manga.author = author.get_text(strip=True).replace("Author:", "").strip() if author else ""

    genres = item.select_one(".row-4.blue .gray")
    genres_text = genres.get_text(strip=True) if genres else ""
    manga.genres = [g.strip() for g in genres_text.split(",") if g.strip()]

    latest = item.select_one(".row-5.gray a.chico")
    if latest:
        match = re.search(r"(\d+(?:\.\d+)?)", latest.get_text(strip=True))
        manga.total_chapters = int(float(match.group(1))) if match else 0
    else:
        manga.total_chapters = 0

    cover = item.select_one("img.loaded") or item.select_one("img")
    if cover:
        src = cover.get("src") or cover.get("data-src")
        if isinstance(src, str):
            manga.cover_image_url = src
    return manga


def get_manga_details(manga_url: str) -> Tuple[Manga, str]:
    """Return manga metadata and its URL as a lightweight chapter-list handle."""
    try:
        with browser_page(headless=True) as browser:
            browser.goto(manga_url, wait_until="domcontentloaded", timeout=30_000)
            browser.locator("body").wait_for(state="attached")
            soup = BeautifulSoup(browser.content(), "html.parser")
        return _parse_manga_details(soup, manga_url), manga_url
    except Exception as exc:
        raise ParsingError(f"Failed to get manga details for {manga_url}: {exc}") from exc


def _parse_manga_details(soup: BeautifulSoup, manga_url: str) -> Manga:
    title_elem = soup.find("h1")
    manga = Manga(title=title_elem.get_text(strip=True) if title_elem else "Unknown Title", url=manga_url)

    cover_div = soup.select_one("div.left.cover")
    if isinstance(cover_div, Tag):
        cover = cover_div.find("img")
        if isinstance(cover, Tag):
            src = cover.get("src")
            if isinstance(src, str):
                manga.cover_image_url = src

    details_table = soup.select_one("div.manga_right table")
    if isinstance(details_table, Tag):
        for row in details_table.find_all("tr"):
            label = row.find("label")
            if not isinstance(label, Tag):
                continue
            label_text = label.get_text(strip=True)
            if "Author:" in label_text:
                author = row.find("a")
                if isinstance(author, Tag):
                    manga.author = author.get_text(strip=True)
            elif "Genre(s):" in label_text:
                manga.genres = [a.get_text(strip=True) for a in row.find_all("a")]

    summary = soup.select_one("div.manga_summary")
    if isinstance(summary, Tag):
        expand = summary.find("div", class_="expand")
        if isinstance(expand, Tag):
            expand.decompose()
        manga.summary = summary.get_text(" ", strip=True)
    return manga

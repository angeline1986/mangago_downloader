"""Lezhin work and episode catalog models parsed independently of capture."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any
from urllib.parse import urlsplit

from ..models import Chapter, Manga
from .urls import LEZHIN_PROVIDER_ID, is_lezhin_episode_url, validate_work_url


class EpisodeAvailability(str, Enum):
    LISTED = "listed_unverified"
    FREE = "free"
    PAID = "paid_access_unverified"
    UNLOCKED = "unlocked"
    ACCESSIBLE = "accessible_verified"
    UNAVAILABLE = "unavailable"
    AUTH_REQUIRED = "authentication_required"


@dataclass(frozen=True)
class LezhinEpisode:
    title: str
    url: str
    number: int | float | None
    availability: EpisodeAvailability
    listed_order: int

    @property
    def chapter(self) -> Chapter | None:
        if self.number is None:
            return None
        return Chapter(number=self.number, url=self.url, title=self.title)


@dataclass(frozen=True)
class LezhinCatalog:
    manga: Manga
    episodes: tuple[LezhinEpisode, ...]
    provider_id: str = LEZHIN_PROVIDER_ID


_NUMBER_PATTERNS = (
    re.compile(r"\b(?:episode|ep\.?|chapter|ch\.?)\s*#?\s*(\d+(?:\.\d+)?)\b", re.I),
    re.compile(r"(?:^|\s)#(\d+(?:\.\d+)?)(?:\s|$)"),
    re.compile(r"(\d+(?:\.\d+)?)\s*(?:화|話)"),
)
_SITE_TITLE_SUFFIX = re.compile(
    r"\s+-\s+[^-]+?\s+-\s+Webtoons\s+-\s+Lezhin Comics.*$", re.I
)


def normalize_work_title(value: str) -> str:
    """Remove the observed author/site suffix when only document.title is present."""
    title = " ".join(str(value or "").split())
    return _SITE_TITLE_SUFFIX.sub("", title).strip() or title


def _episode_number(title: str, row_text: str) -> int | float | None:
    for value in (title, row_text):
        for pattern in _NUMBER_PATTERNS:
            match = pattern.search(value)
            if match:
                number = float(match.group(1))
                if number > 0:
                    return int(number) if number.is_integer() else number
    return None


def _availability(markers: str) -> EpisodeAvailability:
    value = markers.casefold()
    if re.search(r"\b(locked|unavailable|not available)\b", value):
        return EpisodeAvailability.UNAVAILABLE
    if re.search(r"\b(unlocked|purchased|owned|read)\b", value):
        return EpisodeAvailability.UNLOCKED
    if re.search(r"\bfree\b", value):
        return EpisodeAvailability.FREE
    if re.search(r"\b(buy|purchase|coins?)\b", value):
        return EpisodeAvailability.PAID
    return EpisodeAvailability.LISTED


def _episode_title(value: str) -> str:
    clean = " ".join(value.split())
    match = re.search(r"\bEpisode\s+\d+(?:\.\d+)?(?:\s*\([^)]*\))?", clean, re.I)
    if match:
        return match.group(0)
    match = re.search(r"\b(?:Chapter|Ch\.?)\s*#?\s*\d+(?:\.\d+)?(?:\s*\([^)]*\))?", clean, re.I)
    return match.group(0) if match else clean


def build_catalog(work_url: str, title: str, rows: list[dict[str, Any]]) -> LezhinCatalog:
    """Validate, deduplicate, and order DOM episode rows without inferring access."""
    canonical = validate_work_url(work_url)
    episode_prefix = urlsplit(canonical).path.rstrip("/") + "/"
    work_title = str(title or "").strip()
    if not work_title:
        raise ValueError("Lezhin work page did not expose a title")
    episodes: list[LezhinEpisode] = []
    seen_urls: set[str] = set()
    seen_numbers: dict[int | float, str] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not is_lezhin_episode_url(url):
            continue
        parsed = urlsplit(url)
        if not parsed.path.startswith(episode_prefix):
            continue
        normalized_url = f"https://www.lezhinus.com{parsed.path.rstrip('/')}"
        if normalized_url in seen_urls:
            continue
        title_text = " ".join(str(row.get("title") or "").split())
        row_text = " ".join(str(row.get("row_text") or "").split())
        label = _episode_title(title_text or row_text)
        number = _episode_number(label, row_text)
        if number is not None and number in seen_numbers:
            if seen_numbers[number] != normalized_url:
                raise ValueError(f"Conflicting Lezhin episode URLs for number {number:g}")
            continue
        episode = LezhinEpisode(
            title=label or "Episode",
            url=normalized_url,
            number=number,
            availability=_availability(str(row.get("markers") or "") + " " + row_text),
            listed_order=index,
        )
        episodes.append(episode)
        seen_urls.add(normalized_url)
        if number is not None:
            seen_numbers[number] = normalized_url

    numbered = [episode.number for episode in episodes if episode.number is not None]
    if len(numbered) > 1 and numbered[0] > numbered[-1]:
        episodes.reverse()
    manga = Manga(title=work_title, url=canonical, total_chapters=len(episodes))
    return LezhinCatalog(manga=manga, episodes=tuple(episodes))

import pytest

from src.lezhin.catalog import EpisodeAvailability, build_catalog, normalize_work_title
from src.lezhin.discovery import discover_lezhin_catalog, verify_lezhin_episode_access
from src.lezhin.urls import (
    LEZHIN_PROVIDER_ID,
    is_lezhin_episode_url,
    is_lezhin_work_url,
    validate_work_url,
)
from src.models import Chapter, Manga
from src.saved_works import list_saved_works


WORK = "https://www.lezhinus.com/en/comic/presidentlonglegs"


def test_work_url_validation_and_canonicalization():
    assert is_lezhin_work_url(WORK)
    assert validate_work_url("https://lezhinus.com/en/comic/title/?ref=x") == (
        "https://www.lezhinus.com/en/comic/title"
    )
    assert not is_lezhin_work_url(WORK + "/1")
    assert not is_lezhin_work_url("https://www.lezhinus.com:444/en/comic/title")
    for invalid in (
        "http://www.lezhinus.com/en/comic/title",
        "https://www.lezhinus.com/en/comic/title/1",
        "https://www.lezhinus.com.evil.test/en/comic/title",
        "https://user:pass@www.lezhinus.com/en/comic/title",
    ):
        assert not is_lezhin_work_url(invalid)
        with pytest.raises(ValueError):
            validate_work_url(invalid)


def test_work_title_removes_observed_site_suffix():
    assert normalize_work_title(
        "President Long-Legs - CHOI MeeAe - Webtoons - Lezhin Comics"
    ) == "President Long-Legs"


def test_catalog_orders_deduplicates_and_preserves_untrusted_special_number():
    rows = [
        {"url": WORK + "/3", "title": "Episode 3", "row_text": "Free", "markers": ""},
        {"url": WORK + "/2", "title": "Side Story", "row_text": "Special", "markers": "locked"},
        {"url": WORK + "/1", "title": "Episode 1", "row_text": "Read", "markers": ""},
        {"url": WORK + "/1", "title": "Episode 1 duplicate", "row_text": "Free", "markers": ""},
        {"url": "https://evil.test/en/comic/title/4", "title": "Episode 4"},
        {"url": "https://www.lezhinus.com/en/comic/otherwork/4", "title": "Episode 4"},
    ]
    catalog = build_catalog(WORK, "President Longlegs", rows)
    assert isinstance(catalog.manga, Manga)
    assert catalog.manga.url == WORK
    assert catalog.provider_id == LEZHIN_PROVIDER_ID
    assert [episode.number for episode in catalog.episodes] == [1, None, 3]
    assert [episode.availability for episode in catalog.episodes] == [
        EpisodeAvailability.UNLOCKED,
        EpisodeAvailability.UNAVAILABLE,
        EpisodeAvailability.FREE,
    ]
    assert catalog.episodes[1].chapter is None
    assert isinstance(catalog.episodes[0].chapter, Chapter)
    assert is_lezhin_episode_url(catalog.episodes[0].chapter.url)


def test_catalog_keeps_unmarked_listing_unverified_and_rejects_conflicting_numbers():
    listed = build_catalog(WORK, "Title", [{"url": WORK + "/8", "title": "Episode 8"}])
    assert listed.episodes[0].availability is EpisodeAvailability.LISTED
    with pytest.raises(ValueError, match="Conflicting"):
        build_catalog(WORK, "Title", [
            {"url": WORK + "/1", "title": "Episode 1"},
            {"url": WORK + "/2", "title": "Episode 1"},
        ])


def test_paid_episode_and_site_row_title_are_not_misclassified_or_polluted():
    catalog = build_catalog(WORK, "Title", [
        {"url": WORK + "/1", "title": "01 Episode 1 26.10.17 Free",
         "row_text": "01 Episode 1 26.10.17 Free"},
        {"url": WORK + "/2", "title": "02 Episode 2 26.10.17 20 Coins",
         "row_text": "02 Episode 2 26.10.17 20 Coins"},
    ])
    assert catalog.episodes[0].title == "Episode 1"
    assert catalog.episodes[0].availability is EpisodeAvailability.FREE
    assert catalog.episodes[1].title == "Episode 2"
    assert catalog.episodes[1].availability is EpisodeAvailability.PAID


def test_page_discovery_uses_only_current_work_episode_rows():
    class Page:
        url = WORK

        def goto(self, target, **kwargs):
            self.url = target
            return type("Response", (), {"status": 200})()

        def wait_for_function(self, *args, **kwargs):
            return None

        def wait_for_timeout(self, *args, **kwargs):
            return None

        def evaluate(self, script):
            if "const episode" in script:
                return {"title": "President Longlegs", "rows": [
                    {"url": WORK + "/1", "title": "Episode 1", "row_text": "Free"},
                    {"url": "https://www.lezhinus.com/en/comic/other/1", "title": "Episode 1"},
                ]}
            if "document.documentElement.scrollHeight" in script:
                return {"top": 0, "view": 800, "height": 800}
            return None

    catalog = discover_lezhin_catalog(Page(), WORK)
    assert catalog.manga.title == "President Longlegs"
    assert len(catalog.episodes) == 1
    assert catalog.episodes[0].availability is EpisodeAvailability.FREE


def test_page_discovery_unions_rows_materialized_by_progressive_scroll():
    class ProgressivePage:
        url = WORK

        def __init__(self):
            self.top = 0

        def goto(self, target, **kwargs):
            self.url = target
            return type("Response", (), {"status": 200})()

        def wait_for_function(self, *args, **kwargs):
            return None

        def wait_for_timeout(self, *args, **kwargs):
            return None

        def evaluate(self, script):
            if "const episode" in script:
                count = 1 if self.top < 375 else (2 if self.top < 750 else 3)
                return {"title": "President Longlegs", "rows": [
                    {"url": WORK + f"/{number}", "title": f"Episode {number}",
                     "row_text": "Free" if number == 1 else "20 Coins"}
                    for number in range(1, count + 1)
                ]}
            if "document.documentElement.scrollHeight" in script:
                return {"top": self.top, "view": 500, "height": 1200}
            if "scrollBy" in script:
                self.top += 375
            return None

    catalog = discover_lezhin_catalog(ProgressivePage(), WORK)
    assert [episode.number for episode in catalog.episodes] == [1, 2, 3]


def test_saved_work_catalog_uses_canonical_provider_id_without_rewriting_data():
    assert LEZHIN_PROVIDER_ID == "lezhinus"
    works = list_saved_works(LEZHIN_PROVIDER_ID)
    assert works == [{
        "name": "Benevolent Violence",
        "url": "https://www.lezhinus.com/en/comic/benevolent_violence",
    }]


class _FakePage:
    def __init__(self, url, response_status, cuts=0, body="", redirect=None):
        self.url = url
        self.response_status = response_status
        self.cuts = cuts
        self.body = body
        self.redirect = redirect

    def goto(self, target, **kwargs):
        self.url = self.redirect or target
        return type("Response", (), {"status": self.response_status})()

    def wait_for_selector(self, *args, **kwargs):
        return None

    def wait_for_function(self, *args, **kwargs):
        return None

    def locator(self, selector):
        if selector == "[data-cut-index]":
            return type("Locator", (), {"count": lambda _self: self.cuts})()
        return type("Locator", (), {
            "count": lambda _self: int(bool(self.body)),
            "inner_text": lambda _self, **kwargs: self.body,
        })()


@pytest.mark.parametrize("page,expected", [
    (_FakePage(WORK + "/1", 200, cuts=1), EpisodeAvailability.ACCESSIBLE),
    (_FakePage(WORK + "/1", 200, body="This episode is locked"), EpisodeAvailability.UNAVAILABLE),
    (_FakePage("", 200, redirect="https://www.lezhinus.com/en/login"), EpisodeAvailability.AUTH_REQUIRED),
])
def test_access_probe_does_not_equate_listing_with_access(page, expected):
    assert verify_lezhin_episode_access(page, WORK + "/1") is expected

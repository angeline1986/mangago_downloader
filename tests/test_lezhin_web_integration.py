from pathlib import Path
from types import SimpleNamespace

import pytest

from src.lezhin.catalog import EpisodeAvailability, build_catalog
from src.lezhin.web import _profile_path
from webapp import lezhin_routes


WORK = "https://www.lezhinus.com/en/comic/sample"
EPISODE = WORK + "/1"


class SessionContext:
    def __init__(self, url="about:blank"):
        self.page = SimpleNamespace(url=url)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_lezhin_session_endpoint_reports_provider_status(monkeypatch):
    monkeypatch.setattr(lezhin_routes, "lezhin_session_status", lambda: {
        "chrome_state": "connected", "session_state": "not_verified"})
    status, body = lezhin_routes.handle_get("/api/lezhinus/session")
    assert status == 200
    assert body["chrome_state"] == "connected"
    assert body["session_state"] == "not_verified"


def test_chrome_start_uses_exclusive_pilot_profile(monkeypatch):
    monkeypatch.delenv("LEZHIN_CHROME_PROFILE", raising=False)
    assert str(_profile_path()) == "/private/tmp/lezhin_pilot_profile_20261020"
    monkeypatch.setenv("LEZHIN_CHROME_PROFILE", str(Path.home() / "Library/Application Support/Google/Chrome/Profile 1"))
    with pytest.raises(RuntimeError, match="exclusivo"):
        _profile_path()


def test_discovery_requires_manual_authentication(monkeypatch):
    monkeypatch.setattr(lezhin_routes, "lezhin_cdp_session", lambda: SessionContext("https://www.lezhinus.com/en/login"))
    status, body = lezhin_routes.handle_post("/api/lezhinus/chapters", {"url": WORK}, lambda *_: "job")
    assert status == 401
    assert body["code"] == "AUTH_REQUIRED"


def test_discovery_route_serializes_all_169_sorted_chapters(monkeypatch):
    catalog = build_catalog(WORK, "Sample", [
        {"url": f"{WORK}/{number}", "title": f"Episode {number}",
         "row_text": f"Episode {number}", "markers": "Free"}
        for number in range(169, 0, -1)
    ])
    monkeypatch.setattr(lezhin_routes, "lezhin_cdp_session", lambda: SessionContext("https://www.lezhinus.com/en"))
    monkeypatch.setattr(lezhin_routes, "discover_lezhin_catalog", lambda *_: catalog)
    status, body = lezhin_routes.handle_post("/api/lezhinus/chapters", {"url": WORK}, lambda *_: "job")
    episodes = body["chapters"]
    assert status == 200
    assert len(episodes) == 169
    assert [episode["number"] for episode in episodes] == list(range(1, 170))
    assert len({episode["url"] for episode in episodes}) == 169
    assert all(episode["chapter_compatible"] for episode in episodes)
    assert all(episode["availability"] == "free" for episode in episodes)


@pytest.mark.parametrize("availability", [
    EpisodeAvailability.FREE, EpisodeAvailability.PAID,
    EpisodeAvailability.LISTED, EpisodeAvailability.UNAVAILABLE,
])
def test_unverified_or_unavailable_episode_never_enters_queue(monkeypatch, availability):
    monkeypatch.setattr(lezhin_routes, "lezhin_cdp_session", lambda: SessionContext())
    monkeypatch.setattr(lezhin_routes, "verify_lezhin_episode_access", lambda *_: availability)
    queued = []
    status, body = lezhin_routes.handle_post(
        "/api/lezhinus/downloads",
        {"manga": {"title": "Sample", "url": WORK},
         "chapters": [{"number": 1, "title": "Episode 1", "url": EPISODE}]},
        lambda manga, chapters: queued.append((manga, chapters)) or "job",
    )
    assert status == 409
    assert "não confirmado" in body["error"]
    assert queued == []


def test_auth_required_is_reported_as_failure_and_never_queued(monkeypatch):
    monkeypatch.setattr(lezhin_routes, "lezhin_cdp_session", lambda: SessionContext())
    monkeypatch.setattr(lezhin_routes, "verify_lezhin_episode_access",
                        lambda *_: EpisodeAvailability.AUTH_REQUIRED)
    queued = []
    status, body = lezhin_routes.handle_post(
        "/api/lezhinus/downloads",
        {"manga": {"title": "Sample", "url": WORK},
         "chapters": [{"number": 1, "url": EPISODE}]},
        lambda *_: queued.append(True) or "job",
    )
    assert status == 401
    assert body["code"] == "AUTH_REQUIRED"
    assert queued == []


def test_access_confirmed_episode_uses_shared_enqueue(monkeypatch):
    monkeypatch.setattr(lezhin_routes, "lezhin_cdp_session", lambda: SessionContext())
    monkeypatch.setattr(lezhin_routes, "verify_lezhin_episode_access",
                        lambda *_: EpisodeAvailability.ACCESSIBLE)
    queued = []
    status, body = lezhin_routes.handle_post(
        "/api/lezhinus/downloads",
        {"manga": {"title": "Sample", "url": WORK},
         "chapters": [{"number": 1, "title": "Episode 1", "url": EPISODE,
                       "folder_pattern": "Ch. 01"}]},
        lambda manga, chapters: queued.append((manga, chapters)) or "shared-job",
    )
    assert status == 202
    assert body["job_id"] == "shared-job"
    assert queued[0][0].url == WORK
    assert queued[0][1][0].title == "Episode 1"
    assert queued[0][1][0].folder_pattern == "Ch. 01"


def test_queue_removes_url_query_before_persisting(monkeypatch):
    monkeypatch.setattr(lezhin_routes, "lezhin_cdp_session", lambda: SessionContext())
    monkeypatch.setattr(lezhin_routes, "verify_lezhin_episode_access",
                        lambda *_: EpisodeAvailability.ACCESSIBLE)
    queued = []
    status, _ = lezhin_routes.handle_post(
        "/api/lezhinus/downloads",
        {"manga": {"title": "Sample", "url": WORK},
         "chapters": [{"number": 1, "url": EPISODE + "?temporary=value"}]},
        lambda manga, chapters: queued.append(chapters) or "job",
    )
    assert status == 202
    assert queued[0][0].url == EPISODE


def test_interface_registers_lezhin_without_touching_other_providers():
    root = Path(__file__).resolve().parents[1]
    html = (root / "webapp/templates/index.html").read_text()
    script = (root / "webapp/static/lezhin.js").read_text()
    assert 'data-page="lezhinus"' in html
    assert 'id="page-lezhinus"' in html
    assert "/api/saved-works?provider=lezhinus" in script
    assert "Free · não verificado" in script
    assert "/api/lezhinus/downloads" in script

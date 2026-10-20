import pytest

from src.lezhin.session import get_lezhin_cdp_url, get_lezhin_profile_dir
from src.lezhin.urls import is_lezhin_episode_url, is_lezhin_url, validate_episode_url


def test_episode_url_accepts_observed_route():
    url = "https://www.lezhinus.com/en/comic/presidentlonglegs/1"
    assert is_lezhin_url(url)
    assert is_lezhin_episode_url(url)
    assert validate_episode_url(url) == url


@pytest.mark.parametrize("url", [
    "http://www.lezhinus.com/en/comic/title/1",
    "https://lezhin.com/en/comic/title/1",
    "https://www.lezhinus.com/en/comic/title/not-a-number",
    "https://www.lezhinus.com.evil.test/en/comic/title/1",
    "https://user:secret@www.lezhinus.com/en/comic/title/1",
    "javascript:alert(1)",
])
def test_invalid_episode_urls_are_rejected(url):
    assert not is_lezhin_episode_url(url)
    with pytest.raises(ValueError):
        validate_episode_url(url)


def test_cdp_is_loopback_and_reserved_port(monkeypatch):
    assert get_lezhin_cdp_url() == "http://127.0.0.1:9223"
    monkeypatch.setenv("LEZHIN_CDP_URL", "http://127.0.0.1:9222")
    with pytest.raises(ValueError):
        get_lezhin_cdp_url()


def test_profile_rejects_ridi_and_personal_chrome_paths(tmp_path, monkeypatch):
    ridi = tmp_path / ".cache" / "ridibooks_chrome_profile"
    monkeypatch.setenv("LEZHIN_CHROME_PROFILE", str(ridi))
    with pytest.raises(ValueError):
        get_lezhin_profile_dir(tmp_path)
    personal = tmp_path / "Library" / "Application Support" / "Google" / "Chrome" / "Default"
    monkeypatch.setenv("LEZHIN_CHROME_PROFILE", str(personal))
    with pytest.raises(ValueError):
        get_lezhin_profile_dir(tmp_path)


def test_profile_path_is_dedicated_and_not_created(tmp_path, monkeypatch):
    monkeypatch.delenv("LEZHIN_CHROME_PROFILE", raising=False)
    path = get_lezhin_profile_dir(tmp_path)
    assert path == tmp_path / ".mangago_downloader" / "lezhin-chrome-profile"
    assert not path.exists()

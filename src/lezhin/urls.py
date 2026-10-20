"""Strict URL checks for Lezhin title and episode pages."""
from __future__ import annotations

from urllib.parse import urlsplit


LEZHIN_HOSTS = {"lezhinus.com", "www.lezhinus.com"}
LEZHIN_PROVIDER_ID = "lezhinus"


def is_lezhin_url(url: str | None) -> bool:
    """Accept HTTPS pages on the official Lezhin host only."""
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname in LEZHIN_HOSTS
                and parsed.port in {None, 443}
                and not parsed.username and not parsed.password)
    except ValueError:
        return False


def is_lezhin_episode_url(url: str | None) -> bool:
    """Recognize the observed /{locale}/comic/{slug}/{episode} route."""
    if not is_lezhin_url(url):
        return False
    parts = [part for part in urlsplit(url).path.split("/") if part]
    return (
        len(parts) == 4
        and parts[1] == "comic"
        and bool(parts[2])
        and bool(parts[3])
        and parts[3].isdigit()
    )


def is_lezhin_work_url(url: str | None) -> bool:
    """Recognize canonical work pages, excluding episode routes."""
    if not is_lezhin_url(url):
        return False
    parts = [part for part in urlsplit(url).path.split("/") if part]
    return (len(parts) == 3 and parts[1] == "comic"
            and bool(parts[0]) and bool(parts[2]))


def validate_work_url(url: str) -> str:
    """Validate and normalize a Lezhin work URL without query or fragment."""
    if not is_lezhin_work_url(url):
        raise ValueError("Expected an HTTPS Lezhin work URL")
    parsed = urlsplit(url)
    return f"https://www.lezhinus.com{parsed.path.rstrip('/')}"


def validate_episode_url(url: str) -> str:
    """Return a canonical URL or raise without echoing potentially signed data."""
    if not is_lezhin_episode_url(url):
        raise ValueError("Expected an HTTPS Lezhin episode URL")
    parsed = urlsplit(url)
    if parsed.username or parsed.password:
        raise ValueError("Episode URL must not contain embedded credentials")
    return url

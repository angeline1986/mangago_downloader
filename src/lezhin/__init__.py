"""Core primitives for the isolated Lezhin provider pilot."""

from .capture import CaptureResult, capture_episode
from .downloader import download_lezhin_chapter
from .urls import is_lezhin_episode_url, validate_episode_url

__all__ = ["CaptureResult", "capture_episode", "download_lezhin_chapter",
           "is_lezhin_episode_url", "validate_episode_url"]
from .catalog import EpisodeAvailability, LezhinCatalog, LezhinEpisode
from .discovery import discover_lezhin_catalog, verify_lezhin_episode_access
from .urls import LEZHIN_PROVIDER_ID, is_lezhin_work_url, validate_work_url

__all__ = [
    "EpisodeAvailability", "LEZHIN_PROVIDER_ID", "LezhinCatalog", "LezhinEpisode",
    "discover_lezhin_catalog", "is_lezhin_work_url", "validate_work_url",
    "verify_lezhin_episode_access",
]

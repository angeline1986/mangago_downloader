"""Structural validation for downloaded chapter image sets."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from PIL import Image, UnidentifiedImageError


PAGE_FILE_RE = re.compile(r"^page-(\d+)\.[^.]+$", re.IGNORECASE)
DOWNLOAD_COMPLETE_FILE = ".download-complete.json"
DOWNLOAD_IN_PROGRESS_FILE = ".download-in-progress.json"


def _write_marker_atomic(marker: Path, payload: dict) -> Path:
    """Write a JSON state marker atomically."""
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_name(f"{marker.name}.tmp")

    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(marker)
    return marker


def write_download_in_progress_marker(
    chapter_dir: str | Path,
    expected_pages: int = 0,
) -> Path:
    """Persist evidence that this chapter is currently being downloaded."""
    directory = Path(chapter_dir)
    marker = directory / DOWNLOAD_IN_PROGRESS_FILE

    payload = {
        "status": "downloading",
        "expected_pages": max(0, int(expected_pages)),
    }

    return _write_marker_atomic(marker, payload)


def remove_download_in_progress_marker(chapter_dir: str | Path) -> None:
    """Remove the active-download marker."""
    marker = Path(chapter_dir) / DOWNLOAD_IN_PROGRESS_FILE
    try:
        marker.unlink()
    except FileNotFoundError:
        pass


def write_download_complete_marker(
    chapter_dir: str | Path,
    expected_pages: int,
) -> Path:
    """Persist evidence that the chapter finished structural validation."""
    directory = Path(chapter_dir)
    marker = directory / DOWNLOAD_COMPLETE_FILE

    payload = {
        "status": "completed",
        "expected_pages": int(expected_pages),
    }

    written = _write_marker_atomic(marker, payload)
    remove_download_in_progress_marker(directory)
    return written


def remove_download_complete_marker(chapter_dir: str | Path) -> None:
    """Remove stale completion evidence before/retrying a chapter download."""
    marker = Path(chapter_dir) / DOWNLOAD_COMPLETE_FILE
    try:
        marker.unlink()
    except FileNotFoundError:
        pass


@dataclass
class ChapterValidationResult:
    valid: bool
    expected_pages: int
    found_pages: int
    valid_pages: int
    missing_pages: List[int] = field(default_factory=list)
    invalid_pages: List[int] = field(default_factory=list)
    duplicate_pages: List[int] = field(default_factory=list)


def validate_chapter_images(
    chapter_dir: str | Path,
    expected_pages: int,
) -> ChapterValidationResult:
    """Validate the structural integrity of a downloaded chapter.

    Only files named ``page-NNN.<ext>`` directly inside ``chapter_dir`` are
    considered chapter pages. Subdirectories, PDFs and unrelated files are
    ignored.
    """
    directory = Path(chapter_dir)
    expected = max(0, int(expected_pages))

    files_by_page: dict[int, list[Path]] = {}

    if directory.exists():
        for path in directory.iterdir():
            if not path.is_file():
                continue

            match = PAGE_FILE_RE.match(path.name)
            if not match:
                continue

            page_number = int(match.group(1))
            files_by_page.setdefault(page_number, []).append(path)

    duplicate_pages = sorted(
        number
        for number, paths in files_by_page.items()
        if len(paths) > 1
    )

    expected_numbers = set(range(1, expected + 1))
    found_numbers = set(files_by_page)

    missing_pages = sorted(expected_numbers - found_numbers)

    invalid_pages: list[int] = []
    valid_pages = 0

    for page_number in sorted(found_numbers):
        paths = files_by_page[page_number]

        # A duplicate page number is structurally ambiguous even if both files
        # are individually valid.
        if len(paths) != 1:
            continue

        path = paths[0]

        try:
            with Image.open(path) as probe:
                probe.verify()

            with Image.open(path) as image:
                width, height = image.size
                if width <= 0 or height <= 0:
                    raise ValueError("invalid image dimensions")
                image.load()

            valid_pages += 1

        except (UnidentifiedImageError, OSError, ValueError):
            invalid_pages.append(page_number)

    found_pages = len(found_numbers)

    valid = (
        expected > 0
        and found_pages == expected
        and valid_pages == expected
        and not missing_pages
        and not invalid_pages
        and not duplicate_pages
        and found_numbers == expected_numbers
    )

    return ChapterValidationResult(
        valid=valid,
        expected_pages=expected,
        found_pages=found_pages,
        valid_pages=valid_pages,
        missing_pages=missing_pages,
        invalid_pages=sorted(invalid_pages),
        duplicate_pages=duplicate_pages,
    )

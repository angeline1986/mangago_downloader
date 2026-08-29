"""Structural validation for downloaded chapter image sets."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from PIL import Image, UnidentifiedImageError


PAGE_FILE_RE = re.compile(r"^page-(\d+)\.[^.]+$", re.IGNORECASE)


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

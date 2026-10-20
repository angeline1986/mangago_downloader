"""Final-set validation for indexed Lezhin cuts."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, UnidentifiedImageError


_PAGE_RE = re.compile(r"^page-(\d+)\.(webp|jpg|png|gif)$", re.I)


@dataclass(frozen=True)
class CaptureValidation:
    valid: bool
    expected_indexes: tuple[int, ...]
    found_indexes: tuple[int, ...]
    missing_indexes: tuple[int, ...] = field(default_factory=tuple)
    duplicate_indexes: tuple[int, ...] = field(default_factory=tuple)
    invalid_indexes: tuple[int, ...] = field(default_factory=tuple)
    extra_indexes: tuple[int, ...] = field(default_factory=tuple)


def validate_capture(directory: str | Path, expected_indexes: tuple[int, ...]) -> CaptureValidation:
    """Require exactly one decodable final image for each expected zero-based index."""
    expected = tuple(expected_indexes)
    if expected != tuple(range(len(expected))):
        raise ValueError("Expected indexes must be continuous and start at zero")
    files: dict[int, list[Path]] = {}
    for path in Path(directory).iterdir() if Path(directory).exists() else ():
        match = _PAGE_RE.match(path.name)
        if path.is_file() and match:
            files.setdefault(int(match.group(1)) - 1, []).append(path)
    found = tuple(sorted(files))
    missing = tuple(index for index in expected if index not in files)
    extra = tuple(index for index in found if index not in expected)
    duplicates = tuple(index for index, paths in files.items() if len(paths) != 1)
    invalid: list[int] = []
    for index, paths in files.items():
        if len(paths) != 1:
            continue
        try:
            with Image.open(paths[0]) as image:
                extension = paths[0].suffix.lower().lstrip(".")
                expected_extension = "jpg" if image.format == "JPEG" else (image.format or "").lower()
                if extension != expected_extension:
                    raise ValueError("file extension does not match image format")
                image.verify()
            with Image.open(paths[0]) as image:
                image.load()
        except (UnidentifiedImageError, OSError, ValueError):
            invalid.append(index)
    return CaptureValidation(
        valid=bool(expected) and not missing and not extra and not duplicates and not invalid,
        expected_indexes=expected, found_indexes=found, missing_indexes=missing,
        duplicate_indexes=tuple(sorted(duplicates)), invalid_indexes=tuple(sorted(invalid)),
        extra_indexes=extra,
    )


def file_sha256(path: str | Path) -> str:
    """Hash a file incrementally without retaining its contents in memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

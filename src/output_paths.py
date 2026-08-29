"""Canonical output paths for downloaded chapters and generated files."""
from __future__ import annotations

from pathlib import Path


def chapter_image_dir(
    download_root: str | Path,
    provider: str,
    manga_name: str,
    chapter_name: str,
) -> Path:
    """Return the canonical image directory for a chapter."""
    return (
        Path(download_root)
        / provider
        / manga_name
        / "IMG"
        / chapter_name
    )


def chapter_pdf_dir_from_image_dir(chapter_dir: str | Path) -> Path:
    """Return the canonical PDF directory corresponding to an IMG chapter."""
    chapter = Path(chapter_dir)

    if chapter.parent.name == "IMG":
        manga_dir = chapter.parent.parent
        return manga_dir / "PDF" / chapter.name

    # Legacy compatibility: old layouts kept artifacts inside the chapter.
    return chapter


def chapter_pdf_path(chapter_dir: str | Path) -> Path:
    """Return the canonical PDF path for a chapter image directory."""
    chapter = Path(chapter_dir)
    return chapter_pdf_dir_from_image_dir(chapter) / f"{chapter.name}.pdf"


def chapter_cbz_path(chapter_dir: str | Path) -> Path:
    """Return the canonical CBZ path for a chapter image directory."""
    chapter = Path(chapter_dir)
    return chapter_pdf_dir_from_image_dir(chapter) / f"{chapter.name}.cbz"

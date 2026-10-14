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
    root = Path(download_root) / provider / manga_name / "IMG"
    target = root / chapter_name
    if provider in {"comix", "mangago"} and not target.exists() and root.is_dir():
        try:
            chapter_number = float(chapter_name)
        except ValueError:
            chapter_number = None
        if chapter_number is not None:
            import re
            for existing in root.iterdir():
                if not existing.is_dir() or existing.is_symlink():
                    continue
                match = re.fullmatch(r"(?i:ch)\.?\s*(\d+(?:\.\d+)?)", existing.name)
                if match and float(match.group(1)) == chapter_number:
                    raise FileExistsError(
                        f"Capítulo {chapter_name} já existe como {existing.name}; "
                        "revise os arquivos antes de baixar novamente."
                    )
    return target


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

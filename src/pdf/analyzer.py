"""Reusable image analysis for PDF generation decisions."""
from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, Tuple, Union

from PIL import Image


SUPPORTED_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff")


def analyze_images(paths: Iterable[Union[str, Path]]) -> Dict[str, object]:
    """Return structural information about image files without printing."""
    total = 0
    errors = 0
    sizes: Counter[Tuple[int, int]] = Counter()
    modes: Counter[str] = Counter()
    alpha_count = 0
    exif_rotation_count = 0

    for path in paths:
        total += 1
        try:
            with Image.open(path) as img:
                sizes[img.size] += 1
                modes[img.mode] += 1
                if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                    alpha_count += 1
                try:
                    if img.getexif().get(274, 1) in (3, 6, 8):
                        exif_rotation_count += 1
                except Exception:
                    pass
        except Exception:
            errors += 1

    return {
        "total": total,
        "errors": errors,
        "sizes": dict(sizes),
        "modes": dict(modes),
        "alpha_count": alpha_count,
        "exif_rotation_count": exif_rotation_count,
        "distinct_size_count": len(sizes),
        "needs_normalization": alpha_count > 0 or exif_rotation_count > 0,
    }


def analyze_directory(root: Union[str, Path], extensions: Tuple[str, ...] = SUPPORTED_IMAGE_EXTS) -> Dict[str, object]:
    """Analyze supported images below a directory."""
    root = Path(root)
    image_paths = []
    if root.exists():
        for current_root, _, files in os.walk(root):
            for name in files:
                if name.startswith("."):
                    continue
                if name.lower().endswith(extensions):
                    image_paths.append(Path(current_root) / name)
    return analyze_images(image_paths)


"""Image normalization helpers used by PDF generation fallbacks."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple, Union

from PIL import Image


def fix_exif_orientation(img: Image.Image) -> Image.Image:
    """Apply EXIF orientation when present."""
    try:
        orientation = img.getexif().get(274)
        if orientation == 3:
            return img.rotate(180, expand=True)
        if orientation == 6:
            return img.rotate(270, expand=True)
        if orientation == 8:
            return img.rotate(90, expand=True)
    except Exception:
        pass
    return img


def ensure_rgb(img: Image.Image, background: Tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    """Return an RGB image, flattening transparency on the given background."""
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGBA", img.size, (*background, 255))
        img = Image.alpha_composite(bg, img.convert("RGBA"))
        return img.convert("RGB")
    return img.convert("RGB")


def normalize_for_pdf(
    img: Image.Image,
    target_size: Optional[Tuple[int, int]] = None,
    background: Tuple[int, int, int] = (255, 255, 255),
    padding: int = 0,
) -> Image.Image:
    """Center an RGB image on a canvas for PDF fallback generation."""
    img = ensure_rgb(img, background=background)

    if target_size is None:
        target_size = img.size

    canvas_w, canvas_h = target_size
    if padding > 0:
        canvas_w = max(canvas_w, img.width + padding * 2)
        canvas_h = max(canvas_h, img.height + padding * 2)

    canvas = Image.new("RGB", (canvas_w, canvas_h), background)
    x = (canvas_w - img.width) // 2
    y = (canvas_h - img.height) // 2
    canvas.paste(img, (x, y))
    return canvas


def image_needs_normalization(path: Union[str, Path]) -> bool:
    """Detect whether a file needs Pillow normalization before PDF generation."""
    try:
        with Image.open(path) as img:
            if img.mode in ("RGBA", "LA"):
                return True
            if img.mode == "P" and "transparency" in img.info:
                return True
            try:
                if img.getexif().get(274, 1) in (3, 6, 8):
                    return True
            except Exception:
                return False
    except Exception:
        return True
    return False


def load_normalized_image(
    path: Union[str, Path],
    background: Tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    """Open one image and return a detached normalized RGB copy."""
    with Image.open(path) as img:
        img = fix_exif_orientation(img)
        img = ensure_rgb(img, background=background)
        return img.copy()


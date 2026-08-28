"""PDF generation backend for downloaded chapter image folders."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

import img2pdf
from PIL import Image

from .image_normalizer import image_needs_normalization, load_normalized_image, normalize_for_pdf


def generate_pdf_from_images(
    image_files: Iterable[Union[str, Path]],
    output_path: Union[str, Path],
    resolution: float = 300.0,
    background: Tuple[int, int, int] = (255, 255, 255),
    padding: int = 0,
) -> Optional[str]:
    """Generate a chapter PDF, using img2pdf unless images need normalization."""
    image_paths = [Path(path) for path in image_files]
    if not image_paths:
        return None

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not any(image_needs_normalization(path) for path in image_paths):
        output_path.write_bytes(img2pdf.convert([path.read_bytes() for path in image_paths]))
        return str(output_path)

    images: List[Image.Image] = []
    normalized: List[Image.Image] = []
    try:
        images = [load_normalized_image(path, background=background) for path in image_paths]
        if padding > 0:
            target_size = max((img.width, img.height) for img in images)
            normalized = [
                normalize_for_pdf(img, target_size=target_size, background=background, padding=padding)
                for img in images
            ]
        else:
            normalized = [
                normalize_for_pdf(img, target_size=img.size, background=background, padding=0)
                for img in images
            ]

        first, rest = normalized[0], normalized[1:]
        first.save(output_path, "PDF", resolution=resolution, save_all=True, append_images=rest)
        return str(output_path)
    finally:
        for img in normalized + images:
            try:
                img.close()
            except Exception:
                pass

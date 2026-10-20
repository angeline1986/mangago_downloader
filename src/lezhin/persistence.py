"""Atomic, byte-preserving persistence for one indexed reader cut."""
from __future__ import annotations

import hashlib
import io
import os
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .errors import LezhinCaptureError


_FORMATS = {"WEBP": ("webp", "image/webp"), "JPEG": ("jpg", "image/jpeg"),
            "PNG": ("png", "image/png"), "GIF": ("gif", "image/gif")}
_MIME_ALIASES = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg"}
_NAME_RE = re.compile(r"^page-(\d+)\.(webp|jpg|png|gif)$", re.I)


@dataclass(frozen=True)
class PersistedCut:
    index: int
    path: Path
    mime_type: str
    image_format: str
    width: int
    height: int
    size: int
    sha256: str


def inspect_image(content: bytes, content_type: str) -> tuple[str, str, int, int, str]:
    """Validate image bytes against declared MIME and return format metadata."""
    mime = _MIME_ALIASES.get(content_type.split(";", 1)[0].strip().lower(),
                             content_type.split(";", 1)[0].strip().lower())
    try:
        with Image.open(io.BytesIO(content)) as image:
            fmt = image.format or ""
            width, height = image.size
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise LezhinCaptureError("Image response is invalid or truncated") from exc
    supported = _FORMATS.get(fmt)
    if not supported or supported[1] != mime or width < 1 or height < 1:
        raise LezhinCaptureError("Image format, MIME, or dimensions are unsupported")
    return supported[0], mime, width, height, hashlib.sha256(content).hexdigest()


def _final_path(directory: Path, index: int, extension: str) -> Path:
    return directory / f"page-{index + 1:03d}.{extension}"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def persist_cut(directory: str | Path, index: int, content: bytes,
                content_type: str) -> PersistedCut:
    """Validate then atomically promote one response, retaining its original bytes."""
    if index < 0:
        raise LezhinCaptureError("Cut index must be non-negative")
    extension, mime, width, height, digest = inspect_image(content, content_type)
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    target = _final_path(destination, index, extension)
    other = [path for path in destination.glob(f"page-{index + 1:03d}.*")
             if _NAME_RE.match(path.name) and path != target]
    if other:
        raise LezhinCaptureError(f"Cut {index} already exists with a different format")
    if target.exists():
        if _file_sha256(target) != digest:
            raise LezhinCaptureError(f"Cut {index} conflicts with an existing valid file")
    else:
        temporary = target.with_name(target.name + ".part")
        with temporary.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        with Image.open(temporary) as image:
            image.verify()
        if _file_sha256(temporary) != digest:
            raise LezhinCaptureError(f"Cut {index} changed while being persisted")
        os.replace(temporary, target)
        try:
            descriptor = os.open(destination, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError:
            pass
    return PersistedCut(index, target, mime, extension, width, height, len(content), digest)

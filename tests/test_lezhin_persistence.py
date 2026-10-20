import io
import os

import pytest
from PIL import Image

from src.lezhin.errors import LezhinCaptureError
from src.lezhin.persistence import inspect_image, persist_cut
from src.lezhin.validation import file_sha256, validate_capture


def image_bytes(fmt="WEBP"):
    stream = io.BytesIO()
    Image.new("RGB", (7, 9), "red").save(stream, format=fmt)
    return stream.getvalue()


@pytest.mark.parametrize("fmt,mime", [
    ("WEBP", "image/webp"), ("JPEG", "image/jpeg"), ("PNG", "image/png")
])
def test_supported_formats_and_original_bytes(tmp_path, fmt, mime):
    raw = image_bytes(fmt)
    saved = persist_cut(tmp_path, 0, raw, mime)
    assert saved.path.read_bytes() == raw
    assert saved.path.suffix == "." + saved.image_format
    assert saved.width == 7 and saved.height == 9
    assert file_sha256(saved.path) == saved.sha256


def test_invalid_bytes_and_mime_mismatch_rejected():
    with pytest.raises(LezhinCaptureError):
        inspect_image(b"not an image", "image/webp")
    with pytest.raises(LezhinCaptureError):
        inspect_image(image_bytes("PNG"), "image/webp")


def test_duplicate_event_is_idempotent_and_conflict_fails(tmp_path):
    raw = image_bytes()
    first = persist_cut(tmp_path, 2, raw, "image/webp")
    second = persist_cut(tmp_path, 2, raw, "image/webp")
    assert first.path == second.path
    with pytest.raises(LezhinCaptureError):
        persist_cut(tmp_path, 2, image_bytes("PNG"), "image/png")


def test_interruption_before_atomic_rename_leaves_no_final_file(tmp_path, monkeypatch):
    def interrupted(*args):
        raise OSError("simulated interruption")
    monkeypatch.setattr(os, "replace", interrupted)
    with pytest.raises(OSError):
        persist_cut(tmp_path, 0, image_bytes(), "image/webp")
    assert not list(tmp_path.glob("page-001.webp"))
    assert list(tmp_path.glob("page-001.webp.part"))


def test_resume_replaces_partial_and_final_set_reports_missing_duplicate_invalid(tmp_path):
    (tmp_path / "page-001.webp.part").write_bytes(b"partial")
    persist_cut(tmp_path, 0, image_bytes(), "image/webp")
    incomplete = validate_capture(tmp_path, (0, 1))
    assert incomplete.missing_indexes == (1,)
    (tmp_path / "page-001.png").write_bytes(image_bytes("PNG"))
    (tmp_path / "page-002.webp").write_bytes(b"broken")
    checked = validate_capture(tmp_path, (0, 1))
    assert checked.duplicate_indexes == (0,)
    assert checked.invalid_indexes == (1,)

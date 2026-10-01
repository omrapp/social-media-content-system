"""
classify_vision._video_path resolution tests.

Regression: local_path is stored RELATIVE to ORGANIZED_DIR (see index_content.py),
but _video_path used to os.path.exists() it verbatim — so every raw clip was
silently skipped inside the container ("scored 0, skipped N"). It must now
re-anchor a relative local_path against ORGANIZED_DIR.
"""
import os

from backend.pipeline import classify_vision
from backend.config import ORGANIZED_DIR


def test_relative_local_path_resolved_against_organized_dir(tmp_path, monkeypatch):
    """A relative local_path is found by anchoring it to ORGANIZED_DIR."""
    rel = "Greece/stories/clip.mp4"
    abs_path = os.path.join(str(ORGANIZED_DIR), rel)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as fh:
        fh.write(b"x")
    try:
        assert classify_vision._video_path({"local_path": rel}) == abs_path
    finally:
        os.remove(abs_path)


def test_absolute_local_path_used_as_is(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    assert classify_vision._video_path({"local_path": str(f)}) == str(f)


def test_r2_url_fallback_when_no_local_file():
    item = {"local_path": "missing/nope.mp4", "r2_url": "https://cdn.example/x.mp4"}
    assert classify_vision._video_path(item) == "https://cdn.example/x.mp4"


def test_no_path_returns_none():
    assert classify_vision._video_path({"local_path": "missing/nope.mp4"}) is None
    assert classify_vision._video_path({}) is None


def test_disabled_skips_without_touching_media(monkeypatch):
    monkeypatch.setattr(classify_vision, "get_setting", lambda *a, **k: {"enabled": False})
    out = classify_vision.run()
    assert out == {"skipped": True, "reason": "vision disabled"}

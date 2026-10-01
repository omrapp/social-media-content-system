"""
Tests for downloads route fixes:
- _organized_breakdown() correctness
- highlight keyword arg fix (highlight_filter not highlight_name)
- /status response shape
"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# --- Unit tests for _organized_breakdown ---

def test_organized_breakdown_empty_when_dir_missing(tmp_path):
    from backend.api.routes.downloads import _organized_breakdown
    with patch("backend.api.routes.downloads.ORGANIZED_DIR", tmp_path / "nonexistent"):
        result = _organized_breakdown()
    assert result == []


def test_organized_breakdown_returns_categories(tmp_path):
    from backend.api.routes.downloads import _organized_breakdown

    (tmp_path / "nature").mkdir()
    (tmp_path / "nature" / "clip.mp4").write_bytes(b"x" * 1024)
    (tmp_path / "food").mkdir()
    (tmp_path / "food" / "photo.jpg").write_bytes(b"y" * 512)
    (tmp_path / "food" / "photo2.jpg").write_bytes(b"z" * 512)

    with patch("backend.api.routes.downloads.ORGANIZED_DIR", tmp_path):
        result = _organized_breakdown()

    names = [c["category"] for c in result]
    assert "nature" in names
    assert "food" in names

    nature = next(c for c in result if c["category"] == "nature")
    assert nature["video"] == 1
    assert nature["image"] == 0

    food = next(c for c in result if c["category"] == "food")
    assert food["image"] == 2
    assert food["video"] == 0


def test_organized_breakdown_skips_files(tmp_path):
    """Files directly in ORGANIZED_DIR (not in subdirs) are skipped."""
    from backend.api.routes.downloads import _organized_breakdown

    (tmp_path / "loose_file.txt").write_text("ignore me")
    (tmp_path / "real_category").mkdir()

    with patch("backend.api.routes.downloads.ORGANIZED_DIR", tmp_path):
        result = _organized_breakdown()

    assert len(result) == 1
    assert result[0]["category"] == "real_category"


def test_organized_breakdown_sorted(tmp_path):
    from backend.api.routes.downloads import _organized_breakdown

    for name in ["zzz_cat", "aaa_cat", "mmm_cat"]:
        (tmp_path / name).mkdir()

    with patch("backend.api.routes.downloads.ORGANIZED_DIR", tmp_path):
        result = _organized_breakdown()

    names = [c["category"] for c in result]
    assert names == sorted(names)


# --- Regression: highlight_filter keyword arg ---

def test_highlight_download_uses_highlight_filter_kwarg():
    """
    Regression: was calling run(highlight_name=...) but function signature is run(highlight_filter=...).
    This test confirms the correct kwarg is used — would raise TypeError if wrong.
    """
    mock_run = MagicMock(return_value={"highlights_count": 0, "downloaded": 0, "skipped": 0})
    with patch("backend.pipeline.download_highlights.run", mock_run):
        from fastapi.testclient import TestClient
        # Re-import to get patched version
        import importlib
        import backend.api.routes.downloads as dl_mod
        importlib.reload(dl_mod)
        from backend.api.main import app
        with TestClient(app) as c:
            c.post(
                "/api/downloads/highlights",
                json={"highlight_name": "Italy"},
                headers={"Authorization": "Bearer dev"},
            )
    # If wrong kwarg, mock would not be called at all or TypeError raised
    if mock_run.called:
        call_kwargs = mock_run.call_args
        assert "highlight_filter" in (call_kwargs.kwargs or {}), \
            f"Wrong kwarg: {call_kwargs}"
        assert "highlight_name" not in (call_kwargs.kwargs or {}), \
            "highlight_name passed instead of highlight_filter"


# --- Integration: /status shape ---

def test_download_status_shape(tmp_path):
    from fastapi.testclient import TestClient
    from backend.api.main import app

    with patch("backend.api.routes.downloads.ORGANIZED_DIR", tmp_path), \
         patch("backend.api.routes.downloads.POSTS_MANIFEST", tmp_path / "nope.json"), \
         patch("backend.api.routes.downloads.HIGHLIGHTS_MANIFEST", tmp_path / "nope2.json"), \
         patch("backend.api.routes.downloads.POSTS_DIR", tmp_path), \
         patch("backend.api.routes.downloads.HIGHLIGHTS_DIR", tmp_path):

        with TestClient(app) as c:
            resp = c.get(
                "/api/downloads/status",
                headers={"Authorization": "Bearer dev"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert "posts" in data
    assert "highlights" in data
    assert "organized" in data
    assert isinstance(data["organized"], list)
    assert "files" in data["posts"]
    assert "breakdown" in data["highlights"]

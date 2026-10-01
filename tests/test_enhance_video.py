"""
Tests for enhance_video pipeline stage.
- build_filter_complex: pure function for all watermark positions
- find_resize_source: filesystem lookup priority
- enhance_single: mocked ffmpeg subprocess
- run: batch orchestration, media_id single path
- enhance stage registered in orchestrator STAGE_MODULES
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── build_filter_complex ──────────────────────────────────────────────────────

def test_filter_complex_no_watermark():
    from backend.pipeline.enhance_video import build_filter_complex
    fc, vmap = build_filter_complex(duration=10.0, remove_watermarks=False, watermark_position="bottom")
    assert "[vout]" in fc
    assert vmap == "[vout]"
    assert "boxblur" not in fc
    assert "unsharp" in fc
    assert "eq=" in fc
    assert "fade=t=in" in fc
    assert "fade=t=out" in fc


def test_filter_complex_bottom_watermark():
    from backend.pipeline.enhance_video import build_filter_complex, BOTTOM_Y, STRIP_H, VIDEO_W
    fc, vmap = build_filter_complex(duration=10.0, remove_watermarks=True, watermark_position="bottom")
    assert "boxblur" in fc
    assert f"overlay=0:{BOTTOM_Y}" in fc
    assert f"crop={VIDEO_W}:{STRIP_H}:0:{BOTTOM_Y}" in fc
    assert vmap == "[vout]"


def test_filter_complex_top_watermark():
    from backend.pipeline.enhance_video import build_filter_complex, STRIP_H, VIDEO_W
    fc, vmap = build_filter_complex(duration=10.0, remove_watermarks=True, watermark_position="top")
    assert "boxblur" in fc
    assert "overlay=0:0" in fc
    assert f"crop={VIDEO_W}:{STRIP_H}:0:0" in fc


def test_filter_complex_both_watermarks():
    from backend.pipeline.enhance_video import build_filter_complex, BOTTOM_Y
    fc, vmap = build_filter_complex(duration=10.0, remove_watermarks=True, watermark_position="both")
    assert "boxblur" in fc
    assert "overlay=0:0" in fc
    assert f"overlay=0:{BOTTOM_Y}" in fc
    assert "split=3" in fc


def test_filter_complex_short_video_fade_clamp():
    """Very short video: fade_out_start must not go negative."""
    from backend.pipeline.enhance_video import build_filter_complex
    fc, _ = build_filter_complex(duration=0.3, remove_watermarks=False, watermark_position="bottom")
    assert "fade=t=out:st=0.00" in fc


# ── find_resize_source ────────────────────────────────────────────────────────

def test_find_resize_source_9x16_exists(tmp_path):
    from backend.pipeline.enhance_video import find_resize_source
    mid = "abc123"
    f = tmp_path / f"{mid}_9x16.mp4"
    f.write_bytes(b"x")
    with patch("backend.pipeline.enhance_video.REELS_READY_DIR", tmp_path):
        result = find_resize_source(mid, "/some/other/path.mp4")
    assert result == f


def test_find_resize_source_fallback_to_reel_path(tmp_path):
    from backend.pipeline.enhance_video import find_resize_source
    mid = "abc123"
    fallback = tmp_path / "fallback.mp4"
    fallback.write_bytes(b"y")
    with patch("backend.pipeline.enhance_video.REELS_READY_DIR", tmp_path):
        result = find_resize_source(mid, str(fallback))
    assert result == fallback


def test_find_resize_source_none_when_missing(tmp_path):
    from backend.pipeline.enhance_video import find_resize_source
    with patch("backend.pipeline.enhance_video.REELS_READY_DIR", tmp_path):
        result = find_resize_source("nope", "/nonexistent/file.mp4")
    assert result is None


# ── enhance_single ────────────────────────────────────────────────────────────

def _make_media(tmp_path, mid="m1"):
    src = tmp_path / f"{mid}_9x16.mp4"
    src.write_bytes(b"fake_video")
    return {"id": mid, "media_type": "VIDEO", "reel_ready_path": str(src)}


def test_enhance_single_no_source_returns_error(tmp_path):
    from backend.pipeline.enhance_video import enhance_single
    item = {"id": "missing", "media_type": "VIDEO", "reel_ready_path": None}
    with patch("backend.pipeline.enhance_video.REELS_READY_DIR", tmp_path), \
         patch("backend.pipeline.enhance_video.update_media") as mock_um:
        result = enhance_single(item)
    assert result["status"] == "error"
    assert result["reason"] == "source_not_found"
    mock_um.assert_called_once_with("missing", {"status": "raw", "reel_ready_path": None})


def test_enhance_single_ffmpeg_success(tmp_path):
    from backend.pipeline.enhance_video import enhance_single
    item = _make_media(tmp_path)
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = b"15.0\n"
    mock_proc.stderr = b""

    with patch("backend.pipeline.enhance_video.REELS_READY_DIR", tmp_path), \
         patch("backend.pipeline.enhance_video.update_media") as mock_um, \
         patch("backend.pipeline.enhance_video._use_supabase", return_value=False), \
         patch("subprocess.run", return_value=mock_proc):
        result = enhance_single(item, settings={"stabilize": False, "remove_watermarks": False, "watermark_position": "bottom"})

    assert result["status"] == "enhanced"
    assert result["id"] == "m1"
    mock_um.assert_called_once()
    call_args = mock_um.call_args[0]
    assert call_args[1]["status"] == "enhanced"


def test_enhance_single_ffmpeg_failure(tmp_path):
    from backend.pipeline.enhance_video import enhance_single
    item = _make_media(tmp_path)
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stdout = b""
    mock_proc.stderr = b"ffmpeg error"

    with patch("backend.pipeline.enhance_video.REELS_READY_DIR", tmp_path), \
         patch("backend.pipeline.enhance_video.update_status") as mock_us, \
         patch("subprocess.run", return_value=mock_proc):
        result = enhance_single(item, settings={"stabilize": False, "remove_watermarks": False, "watermark_position": "bottom"})

    assert result["status"] == "error"
    assert result["reason"] == "ffmpeg_failed"
    mock_us.assert_called_with("m1", "error", "enhance_ffmpeg_failed")


# ── run (batch) ───────────────────────────────────────────────────────────────

def test_run_batch_skips_non_video(tmp_path):
    from backend.pipeline.enhance_video import run
    items = [
        {"id": "img1", "media_type": "IMAGE", "reel_ready_path": None},
    ]
    with patch("backend.pipeline.enhance_video.get_setting", return_value={}), \
         patch("backend.pipeline.enhance_video.get_media", return_value=items):
        result = run()
    assert result["enhanced"] == 0
    assert result["failed"] == 0
    assert result["total"] == 1


def test_run_single_media_id_not_found():
    from backend.pipeline.enhance_video import run
    with patch("backend.pipeline.enhance_video.get_setting", return_value={}), \
         patch("backend.pipeline.enhance_video.get_media_by_id", return_value=None):
        result = run(media_id="nonexistent")
    assert result["enhanced"] == 0
    assert result["failed"] == 1


# ── orchestrator registration ─────────────────────────────────────────────────

def test_enhance_stage_in_orchestrator():
    from backend.pipeline.orchestrator import STAGE_MODULES, DEFAULT_PIPELINE
    assert "enhance" in STAGE_MODULES
    assert STAGE_MODULES["enhance"] == "backend.pipeline.enhance_video"
    assert "enhance" in DEFAULT_PIPELINE


def test_enhance_stage_dispatch_via_pipeline(client, auth_headers):
    """POST /api/pipeline/enhance resolves to enhance_video.run, not unknown stage."""
    mock_result = {"enhanced": 0, "failed": 0, "total": 0}
    with patch("backend.pipeline.enhance_video.run", return_value=mock_result):
        resp = client.post(
            "/api/pipeline/enhance",
            json={},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["stage"] == "enhance"
